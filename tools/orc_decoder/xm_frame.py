"""XM-accurate transmit chain simulator.

Implements the frame structure documented in XM's own patents
(US20080311845, US7653088, US6229824B1):

  Master frame (432 ms):
    MFP (128 bits) | 205 x sub-frame (6912 bits) | PAD (192 bits)

  Sub-frame (6912 bits):
    FSP (64-bit fast sync preamble) | payload (6848 bits)

  FEC chain:
    payload -> RS(255,223) -> byte interleave -> conv rate 1/3 K=7 -> QPSK

The actual bit patterns of FSP/MFP/PAD are unpublished ("known preamble
sequences" per the patents). We use stand-in patterns with the correct
lengths and repetition rates — the decoder's job is to recover the real
ones from captures via blind_sync.

Bit rate: 3.28 Mbps | Symbol rate: 1.64 Msps QPSK | RRC 0.15
"""

import numpy as np


# ---------------------------------------------------------------------------
# Frame constants from patents
# ---------------------------------------------------------------------------
FSP_LEN = 64            # fast sync preamble, every sub-frame
SUBFRAME_LEN = 6912     # bits per TDM sub-frame
SUBFRAME_PAYLOAD = SUBFRAME_LEN - FSP_LEN  # 6848
SUBFRAMES_PER_MASTER = 205
MFP_LEN = 128           # master frame preamble
PAD_LEN = 192           # PAD sync at master frame tail
MASTER_FRAME_BITS = MFP_LEN + SUBFRAMES_PER_MASTER * SUBFRAME_LEN + PAD_LEN
SUBFRAME_HZ = 474.5     # sub-frame repetition rate

# Stand-in sync patterns (real ones unpublished; lengths and rates are exact).
# Chosen to have good autocorrelation properties.
_FSP_STANDIN = 0x1ACFFC1D4E2B5A69
_MFP_STANDIN = 0x9D8C7B6A5F4E3D2C1B0A98766543210F
_PAD_STANDIN = 0xF0E1D2C3B4A59687766554433221100F0E1D2C3B4A59687


def _bits_of(value, nbits):
    return np.array([(value >> i) & 1 for i in range(nbits - 1, -1, -1)],
                    dtype=np.uint8)


FSP_BITS = _bits_of(_FSP_STANDIN, FSP_LEN)
MFP_BITS = _bits_of(_MFP_STANDIN, MFP_LEN)
PAD_BITS = _bits_of(_PAD_STANDIN, PAD_LEN)


# ---------------------------------------------------------------------------
# Reed-Solomon (255,223) — byte-oriented, matches XM/Sirius primitive poly
# ---------------------------------------------------------------------------
_RS_N = 255
_RS_K = 223
_RS_POLY = 0x11D  # x^8 + x^4 + x^3 + x^2 + 1

_gf_exp = [0] * 512
_gf_log = [0] * 256


def _gf_init():
    x = 1
    for i in range(255):
        _gf_exp[i] = x
        _gf_log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _RS_POLY
    for i in range(255, 512):
        _gf_exp[i] = _gf_exp[i - 255]


_gf_init()


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _gf_exp[_gf_log[a] + _gf_log[b]]


def _rs_gen_poly():
    """Generator polynomial for RS(255,223): 32 parity symbols."""
    g = [1]
    for i in range(_RS_N - _RS_K):
        g = _gf_poly_mul(g, [1, _gf_exp[i]])
    return g


def _gf_poly_mul(a, b):
    r = [0] * (len(a) + len(b) - 1)
    for i, ca in enumerate(a):
        for j, cb in enumerate(b):
            r[i + j] ^= _gf_mul(ca, cb)
    return r


_RS_GEN = _rs_gen_poly()


def rs_encode_block(data223):
    """Encode 223 data bytes -> 255 code bytes (systematic)."""
    assert len(data223) == _RS_K
    parity = [0] * (_RS_N - _RS_K)
    for byte in data223:
        fb = byte ^ parity[0]
        parity = parity[1:] + [0]
        if fb:
            for i in range(_RS_N - _RS_K):
                parity[i] ^= _gf_mul(_RS_GEN[_RS_N - _RS_K - 1 - i], fb)
    return bytes(data223) + bytes(parity)


def rs_encode_bits(bits):
    """RS(255,223) encode a bit array (pads to byte/codeword boundary)."""
    bits = np.asarray(bits, dtype=np.uint8)
    # Pad to whole bytes
    n_bytes = (len(bits) + 7) // 8
    padded = np.zeros(n_bytes * 8, dtype=np.uint8)
    padded[:len(bits)] = bits
    data = bytes(int("".join(map(str, padded[i:i + 8])), 2)
                 for i in range(0, len(padded), 8))
    # Pad to whole codewords
    n_cw = (len(data) + _RS_K - 1) // _RS_K
    data = data + bytes(n_cw * _RS_K - len(data))
    out = bytearray()
    for i in range(n_cw):
        out += rs_encode_block(data[i * _RS_K:(i + 1) * _RS_K])
    # Back to bits
    return np.array([int(b) for byte in out for b in f"{byte:08b}"],
                    dtype=np.uint8)[:n_cw * _RS_N * 8]


# ---------------------------------------------------------------------------
# Convolutional code: rate 1/3, constraint length 7
# Polynomials per XM patent (octal): 171, 133, 165
# ---------------------------------------------------------------------------
_CONV_POLYS = (0o171, 0o133, 0o165)
_CONV_K = 7


def conv_encode_13(bits):
    """Rate 1/3, K=7 convolutional encoder."""
    bits = np.asarray(bits, dtype=np.uint8)
    state = 0
    out = []
    for b in bits:
        state = ((state << 1) | int(b)) & ((1 << _CONV_K) - 1)
        for poly in _CONV_POLYS:
            out.append(bin(state & poly).count("1") % 2)
    # Flush
    for _ in range(_CONV_K - 1):
        state = (state << 1) & ((1 << _CONV_K) - 1)
        for poly in _CONV_POLYS:
            out.append(bin(state & poly).count("1") % 2)
    return np.array(out, dtype=np.uint8)


# ---------------------------------------------------------------------------
# RRC filter
# ---------------------------------------------------------------------------
def rrc_taps(sps, alpha, span_symbols):
    n = span_symbols * sps
    t = (np.arange(n) - n / 2) / sps
    h = np.zeros(n)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-10:
            h[i] = 1.0 + alpha * (4 / np.pi - 1)
        elif abs(abs(ti) - 1 / (4 * alpha)) < 1e-10:
            h[i] = (alpha / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))
                + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
        else:
            num = (np.sin(np.pi * ti * (1 - alpha))
                   + 4 * alpha * ti * np.cos(np.pi * ti * (1 + alpha)))
            den = np.pi * ti * (1 - (4 * alpha * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt(np.sum(h ** 2))


# ---------------------------------------------------------------------------
# Full XM-like encoder
# ---------------------------------------------------------------------------
class XMFrameEncoder:
    """Generates XM-structured IQ per the patent-documented frame layout."""

    def __init__(self, sps=4, alpha=0.15, seed=0):
        self.sps = sps
        self.alpha = alpha
        self.rng = np.random.default_rng(seed)
        self.taps = rrc_taps(sps, alpha, 10)
        self.sym_rate = 1.64e6

    def build_master_frame(self):
        """Build one 432 ms master frame of coded bits + ground truth.

        Each sub-frame is exactly 6912 bits on the channel:
        64-bit FSP + 6848 coded bits (RS + conv, padded to fit).

        Returns (bits, info) where info describes the frame layout for
        decoder scoring.
        """
        subframe_payloads = []  # original payload bits per sub-frame
        coded_subframes = []

        # Size the info payload so RS+conv fits in 6848 bits.
        # Conv 1/3 K=7: out = 3*(in+6). RS(255,223): out = in*255/223.
        # Target: conv_out = 6848 -> conv_in = 2276 -> rs_out = 2276 bits = 284.5 bytes.
        # Use 284 bytes RS input -> 284*8=2272 bits -> pad to 2276 for conv.
        rs_in_bytes = 284
        info_bits = rs_in_bytes * 8  # 2272

        for sf in range(SUBFRAMES_PER_MASTER):
            # Random payload for this sub-frame
            payload = self.rng.integers(0, 2, info_bits)
            subframe_payloads.append(payload)

            # FEC: RS(255,223) then convolutional rate 1/3
            rs_coded = rs_encode_bits(payload)  # 284 -> ~325 bytes
            # Pad/truncate RS output to 2276 bits for conv input
            if len(rs_coded) < 2276:
                rs_coded = np.concatenate(
                    [rs_coded, np.zeros(2276 - len(rs_coded), dtype=np.uint8)])
            else:
                rs_coded = rs_coded[:2276]
            conv_coded = conv_encode_13(rs_coded)  # 2276 -> 6846 bits
            # Pad to exactly 6848
            if len(conv_coded) < SUBFRAME_PAYLOAD:
                conv_coded = np.concatenate(
                    [conv_coded,
                     np.zeros(SUBFRAME_PAYLOAD - len(conv_coded),
                              dtype=np.uint8)])
            else:
                conv_coded = conv_coded[:SUBFRAME_PAYLOAD]
            coded_subframes.append(conv_coded)

        # Assemble: MFP | [FSP | coded payload] * 205 | PAD
        parts = [MFP_BITS.copy()]
        for csf in coded_subframes:
            parts.append(FSP_BITS.copy())
            parts.append(csf)
        parts.append(PAD_BITS.copy())
        bits = np.concatenate(parts)

        info = {
            "n_subframes": SUBFRAMES_PER_MASTER,
            "fsp_positions": [MFP_LEN + i * (FSP_LEN + len(coded_subframes[0]))
                              for i in range(SUBFRAMES_PER_MASTER)],
            "mfp_position": 0,
            "pad_position": len(bits) - PAD_LEN,
            "payloads": subframe_payloads,
        }
        return bits, info

    def encode(self, n_master_frames=1, snr_db=float("inf"),
               freq_offset_hz=0):
        """Generate IQ for n_master_frames (each 432 ms).

        Returns (iq, infos).
        """
        all_bits = []
        infos = []
        for _ in range(n_master_frames):
            bits, info = self.build_master_frame()
            all_bits.append(bits)
            infos.append(info)
        bits = np.concatenate(all_bits)

        # QPSK (int8 to avoid underflow)
        bi = bits[0::2].astype(np.int8)
        bq = bits[1::2].astype(np.int8)
        n_sym = min(len(bi), len(bq))
        sym = ((1 - 2 * bi[:n_sym]) + 1j * (1 - 2 * bq[:n_sym])) / np.sqrt(2)

        # RRC
        up = np.zeros(n_sym * self.sps, dtype=complex)
        up[::self.sps] = sym
        shaped = np.convolve(up, self.taps, mode="same")
        trim = len(self.taps) // 2
        shaped = shaped[trim:-trim]

        # Freq offset
        if freq_offset_hz:
            t = np.arange(len(shaped)) / (self.sym_rate * self.sps)
            shaped = shaped * np.exp(2j * np.pi * freq_offset_hz * t)

        # AWGN
        if np.isfinite(snr_db):
            sig_pwr = np.mean(np.abs(shaped) ** 2)
            noise_pwr = sig_pwr / (10 ** (snr_db / 10))
            noise = (self.rng.normal(0, np.sqrt(noise_pwr / 2), len(shaped))
                     + 1j * self.rng.normal(0, np.sqrt(noise_pwr / 2),
                                            len(shaped)))
            shaped = shaped + noise

        shaped = shaped * (0.18 / np.sqrt(np.mean(np.abs(shaped) ** 2)))
        return shaped.astype(np.complex64), infos
