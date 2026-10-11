"""XM-like transmit chain simulator for the OrcXM decoder.

Generates realistic IQ with a full transmit chain, so the decoder can
be developed and tested without waiting on hardware captures:

    payload -> framing -> FEC -> interleave -> QPSK -> RRC -> channel -> IQ

Every stage is invertible, and the ground truth (original payload bits)
is available for scoring the decoder.
"""

import numpy as np


SYNC_WORD = 0x1ACFFC1D
SYNC_LEN = 32


def _bits_of(value, nbits):
    return [(value >> i) & 1 for i in range(nbits - 1, -1, -1)]


def convolutional_encode(bits, constraint=7, poly1=0o171, poly2=0o133):
    """Rate 1/2 convolutional encoder (DVB-style polynomials).

    This is a stand-in for XM's actual FEC (unknown). The decoder
    doesn't need to know the exact code — it needs to handle the
    *concept* of coded bits.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    state = 0
    out = []
    mask = (1 << (constraint - 1)) - 1
    for b in bits:
        state = ((state << 1) | b) & ((1 << constraint) - 1)
        # Two parity outputs
        p1 = bin(state & poly1).count("1") % 2
        p2 = bin(state & poly2).count("1") % 2
        out += [p1, p2]
    # Flush
    for _ in range(constraint - 1):
        state = (state << 1) & ((1 << constraint) - 1)
        p1 = bin(state & poly1).count("1") % 2
        p2 = bin(state & poly2).count("1") % 2
        out += [p1, p2]
    return np.array(out, dtype=np.uint8)


def block_interleave(bits, rows=32):
    """Simple block interleaver (rows x cols)."""
    bits = np.asarray(bits, dtype=np.uint8)
    cols = (len(bits) + rows - 1) // rows
    padded = np.zeros(rows * cols, dtype=np.uint8)
    padded[:len(bits)] = bits
    matrix = padded.reshape(rows, cols)
    return matrix.T.flatten()


def block_deinterleave(bits, rows=32):
    """Inverse of block_interleave."""
    bits = np.asarray(bits, dtype=np.uint8)
    cols = len(bits) // rows
    matrix = bits.reshape(cols, rows)
    return matrix.T.flatten()


def rrc_taps(sps, alpha, span_symbols):
    """Root-raised-cosine FIR taps, unity energy."""
    n = span_symbols * sps
    t = (np.arange(n) - n / 2) / sps
    h = np.zeros(n)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-10:
            h[i] = 1.0 + alpha * (4 / np.pi - 1)
        elif abs(abs(ti) - 1 / (4 * alpha)) < 1e-10:
            h[i] = (alpha / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))
                + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha))
            )
        else:
            num = (np.sin(np.pi * ti * (1 - alpha))
                   + 4 * alpha * ti * np.cos(np.pi * ti * (1 + alpha)))
            den = np.pi * ti * (1 - (4 * alpha * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt(np.sum(h ** 2))


class XMEncoder:
    """Full XM-like transmit chain simulator."""

    def __init__(self, sym_rate=1.64e6, sps=4, alpha=0.15,
                 frame_payload_bits=1024, seed=0):
        self.sym_rate = sym_rate
        self.sps = sps
        self.alpha = alpha
        self.frame_payload = frame_payload_bits
        self.rng = np.random.default_rng(seed)
        self.taps = rrc_taps(sps, alpha, 10)

    def encode(self, duration_s, snr_db=float("inf"), freq_offset_hz=0,
               phase_noise_deg=0):
        """Generate IQ for duration_s seconds with channel impairments.

        Returns (iq, ground_truth) where ground_truth has the original
        payload bits per frame for decoder scoring.
        """
        frame_bits = SYNC_LEN + 16 + self.frame_payload
        n_frames = max(1, int(duration_s * self.sym_rate * 2 // frame_bits // 2))

        all_coded = []
        ground_truth = []
        for fc in range(n_frames):
            # Frame: sync + counter + payload
            payload = self.rng.integers(0, 2, self.frame_payload)
            frame = (_bits_of(SYNC_WORD, SYNC_LEN)
                     + _bits_of(fc % 65536, 16)
                     + payload.tolist())
            ground_truth.append({
                "counter": fc % 65536,
                "payload": np.array(payload, dtype=np.uint8),
            })
            # FEC + interleave (sync/counter go through uncoded for simplicity;
            # real systems differ, but this tests the decoder's framing)
            coded_payload = convolutional_encode(np.array(frame, dtype=np.uint8))
            interleaved = block_interleave(coded_payload)
            all_coded.append(interleaved)

        bits = np.concatenate(all_coded)
        # QPSK map (int8 to avoid uint8 underflow)
        bi = bits[0::2].astype(np.int8)
        bq = bits[1::2].astype(np.int8)
        # Handle odd length
        n_sym = min(len(bi), len(bq))
        sym = ((1 - 2 * bi[:n_sym]) + 1j * (1 - 2 * bq[:n_sym])) / np.sqrt(2)

        # RRC shaping
        up = np.zeros(n_sym * self.sps, dtype=complex)
        up[::self.sps] = sym
        shaped = np.convolve(up, self.taps, mode="same")
        trim = len(self.taps) // 2
        shaped = shaped[trim:-trim]

        # Channel: frequency offset
        if freq_offset_hz:
            t = np.arange(len(shaped)) / (self.sym_rate * self.sps)
            shaped = shaped * np.exp(2j * np.pi * freq_offset_hz * t)

        # Channel: phase noise (random walk)
        if phase_noise_deg:
            pn = np.cumsum(self.rng.normal(
                0, np.deg2rad(phase_noise_deg), len(shaped)))
            shaped = shaped * np.exp(1j * pn)

        # Channel: AWGN
        if np.isfinite(snr_db):
            sig_pwr = np.mean(np.abs(shaped) ** 2)
            noise_pwr = sig_pwr / (10 ** (snr_db / 10))
            noise = (self.rng.normal(0, np.sqrt(noise_pwr / 2), len(shaped))
                     + 1j * self.rng.normal(0, np.sqrt(noise_pwr / 2), len(shaped)))
            shaped = shaped + noise

        # Normalize
        shaped = shaped * (0.18 / np.sqrt(np.mean(np.abs(shaped) ** 2)))
        return shaped.astype(np.complex64), ground_truth
