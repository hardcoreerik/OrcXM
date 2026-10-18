#!/usr/bin/env python3
"""Generate an XM-like QPSK test carrier (baseband IQ file).

Produces random QPSK at 1.64 Msym/s, root-raised-cosine 0.15 — the
satellite waveform per the R&S XM-Radio manual — as complex64 IQ,
ready to transmit from the Pluto's TX at 2.33 GHz (or to use as a
known-good reference for the demodulator).

Conducted use only: feed it to the receiver over a cable/attenuator.
Do NOT radiate this in the 2.3 GHz S-band.

Usage:
    python gen_xm_test_carrier.py -o xm_test.iq -d 1.0
    python gen_xm_test_carrier.py -o xm_test.iq -d 0.5 --sps 2 --seed 7

Transmit (example, GNU Radio): File Source (complex64) -> PlutoSDR Sink,
LO at 2333 MHz, sample rate = 1.64e6 * sps.
"""

import argparse
import numpy as np

from orc_decoder.rrc import rrc_taps

# Arbitrary marker used *only* to exercise frame_sync on a signal we build
# ourselves.  It is the CCSDS attached sync marker, which SDARS is not —
# it is deliberately NOT a default anywhere in the decoder, because
# searching a real SDARS capture for this value cannot succeed and would
# only produce false alarm sets.
TEST_SYNC_WORD = 0x1ACFFC1D
SYNC_LEN = 32
COUNTER_LEN = 16


def _bits_of(value, nbits):
    return [(value >> i) & 1 for i in range(nbits - 1, -1, -1)]


def build(duration=1.0, sym_rate=1.64e6, sps=4, alpha=0.15, span=10,
          seed=0, rms=0.18, framed=False, frame_payload=1024):
    """Build the test carrier as ``(iq, bits)``.

    ``bits`` is the exact transmitted bit sequence, so a demodulator test can
    measure BER instead of eyeballing a constellation.
    """
    rng = np.random.default_rng(seed)

    if framed:
        frame_len = SYNC_LEN + COUNTER_LEN + frame_payload
        n_frames = max(1, int(duration * sym_rate) // frame_len)
        n_sym = n_frames * frame_len
        bits = []
        for fc in range(n_frames):
            bits += _bits_of(TEST_SYNC_WORD, SYNC_LEN)
            bits += _bits_of(fc % 65536, COUNTER_LEN)
            bits += rng.integers(0, 2, frame_payload).tolist()
        bits = np.array(bits[:2 * (n_sym // 2)], dtype=np.uint8)
        n_sym = len(bits) // 2
    else:
        n_sym = int(duration * sym_rate)
        bits = rng.integers(0, 2, 2 * n_sym).astype(np.uint8)

    # Bits -> QPSK, unit energy. (cast to int8 first: uint8 underflows on
    # 1-2*1 -> 255, not -1)
    bi = bits[0::2].astype(np.int8)
    bq = bits[1::2].astype(np.int8)
    sym = (1 - 2 * bi) + 1j * (1 - 2 * bq)
    sym = sym / np.sqrt(2)

    # Upsample and shape
    up = np.zeros(n_sym * sps, dtype=complex)
    up[::sps] = sym
    taps = rrc_taps(sps, alpha, span)
    shaped = np.convolve(up, taps, mode="same")

    # Trim filter transients, normalize to target RMS
    trim = len(taps) // 2
    shaped = shaped[trim:-trim] if trim else shaped
    shaped = shaped * (rms / np.sqrt(np.mean(np.abs(shaped) ** 2)))
    return shaped.astype(np.complex64), bits


def main():
    ap = argparse.ArgumentParser(description="XM-like QPSK test carrier generator")
    ap.add_argument("-o", "--output", required=True, help="output .iq file (complex64)")
    ap.add_argument("-d", "--duration", type=float, default=1.0, help="seconds of IQ (default 1.0)")
    ap.add_argument("--sym-rate", type=float, default=1.64e6, help="symbol rate (default 1.64e6)")
    ap.add_argument("--sps", type=int, default=4, help="samples per symbol (default 4)")
    ap.add_argument("--alpha", type=float, default=0.15, help="RRC roll-off (default 0.15)")
    ap.add_argument("--span", type=int, default=10, help="RRC span in symbols (default 10)")
    ap.add_argument("--seed", type=int, default=0, help="PRNG seed (default 0)")
    ap.add_argument("--rms", type=float, default=0.18, help="output RMS amplitude (default 0.18)")
    ap.add_argument("--framed", action="store_true",
                    help="embed sync word + 16-bit frame counter (for frame-sync testing)")
    ap.add_argument("--frame-payload", type=int, default=1024,
                    help="payload bits per frame when --framed (default 1024)")
    args = ap.parse_args()

    shaped, bits = build(duration=args.duration, sym_rate=args.sym_rate,
                         sps=args.sps, alpha=args.alpha, span=args.span,
                         seed=args.seed, rms=args.rms, framed=args.framed,
                         frame_payload=args.frame_payload)

    shaped.tofile(args.output)
    fs = args.sym_rate * args.sps
    print(f"wrote {args.output}: {len(shaped)} samples, "
          f"{len(shaped) / fs:.3f} s at {fs / 1e6:.2f} Msps, "
          f"RMS {np.sqrt(np.mean(np.abs(shaped) ** 2)):.3f}, "
          f"{len(bits)} bits")


if __name__ == "__main__":
    main()
