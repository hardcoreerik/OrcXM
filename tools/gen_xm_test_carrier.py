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


def rrc_taps(sps, alpha, span_symbols):
    """Root-raised-cosine FIR taps, unity energy."""
    n = span_symbols * sps
    t = (np.arange(n) - n / 2) / sps  # time in symbols
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
    h = h / np.sqrt(np.sum(h ** 2))  # unity energy
    return h


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
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    n_sym = int(args.duration * args.sym_rate)

    # Random bits -> Gray-coded QPSK, unit energy
    bits = rng.integers(0, 2, 2 * n_sym)
    sym = (1 - 2 * bits[0::2]) + 1j * (1 - 2 * bits[1::2])
    sym = sym / np.sqrt(2)

    # Upsample and shape
    up = np.zeros(n_sym * args.sps, dtype=complex)
    up[::args.sps] = sym
    taps = rrc_taps(args.sps, args.alpha, args.span)
    shaped = np.convolve(up, taps, mode="same")

    # Trim filter transients, normalize to target RMS
    trim = len(taps) // 2
    shaped = shaped[trim:-trim] if trim else shaped
    shaped = shaped * (args.rms / np.sqrt(np.mean(np.abs(shaped) ** 2)))

    shaped.astype(np.complex64).tofile(args.output)
    fs = args.sym_rate * args.sps
    print(f"wrote {args.output}: {len(shaped)} samples, "
          f"{len(shaped) / fs:.3f} s at {fs / 1e6:.2f} Msps, "
          f"RMS {np.sqrt(np.mean(np.abs(shaped) ** 2)):.3f}")


if __name__ == "__main__":
    main()
