"""Pulse-shaping filters shared by the generator and the demodulator.

Single source of truth: the transmit filter and the receive matched filter
must be the same root-raised-cosine, or the cascade is not a Nyquist
pulse and the eye is not open at the symbol instants.
"""

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
