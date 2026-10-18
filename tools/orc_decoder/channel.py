"""Adversarial channel model for the OrcXM test carrier.

The point of this module is to make the test signal stop being a closed
loop.  A Pluto TX/RX loop cable shares one reference clock and one sample
clock, so the received test carrier has *exactly zero* carrier offset, zero
symbol-timing offset and zero sample-rate offset.  A demodulator running
under those conditions has never been tested on any of the three things
that make demodulation hard.

This module injects all three, plus noise, so that the demodulator can be
measured against ground truth before anything is pointed at the sky.

Impairments are always applied in this order:

    sample-rate offset -> carrier frequency offset -> carrier phase
    -> symbol-timing delay -> AWGN

Order matters slightly (SRO before CFO means the CFO is applied on the
already time-scaled signal) but any fixed order is fine as long as callers
know it.

Noise convention
----------------
``snr_db`` is the ratio of *mean signal power* to *noise power over the
full sampled bandwidth*.  Because the signal is confined to roughly one
symbol rate and the noise is spread over ``sps`` times that, the per-symbol
ratio is higher by ``10*log10(sps)``:

    Es/N0 (dB) = snr_db + 10*log10(sps)

Use :func:`snr_to_esn0_db` rather than doing the arithmetic by hand.
"""

import numpy as np

from .interp import interp_cubic

DEFAULT_SYM_RATE = 1.64e6
DEFAULT_SPS = 4


def snr_to_esn0_db(snr_db, sps=DEFAULT_SPS):
    """Convert the full-bandwidth SNR used here to a per-symbol Es/N0."""
    return snr_db + 10.0 * np.log10(sps)


def add_sample_rate_offset(iq, ppm):
    """Time-scale the signal by 1 + ppm*1e-6, as a real receiver's clock drift does.

    This is what a sample-rate offset actually is: the receiver's ADC clock
    is not the transmitter's, so the symbol period drifts slowly.  After a
    second at 20 ppm the sampling instant has moved by about 26 samples at
    4 samples/symbol, which is 6.5 symbols.  Any timing loop that cannot
    absorb that will lose lock.
    """
    if ppm == 0.0:
        return np.asarray(iq, dtype=np.complex128)
    n = len(iq)
    t = np.arange(n, dtype=np.float64) / (1.0 + ppm * 1e-6)
    return interp_cubic(iq, t)


def add_cfo(iq, cfo_hz, fs, phase0=0.0):
    """Multiply by a complex exponential: a carrier frequency offset in Hz."""
    if cfo_hz == 0.0 and phase0 == 0.0:
        return np.asarray(iq, dtype=np.complex128)
    n = np.arange(len(iq), dtype=np.float64)
    return np.asarray(iq, dtype=np.complex128) * np.exp(
        1j * (2.0 * np.pi * cfo_hz * n / fs + phase0))


def add_timing_offset(iq, delay_samples):
    """Delay by a possibly fractional number of samples (band-limited)."""
    if delay_samples == 0.0:
        return np.asarray(iq, dtype=np.complex128)
    t = np.arange(len(iq), dtype=np.float64) - delay_samples
    return interp_cubic(iq, t)


def add_awgn(iq, snr_db, seed=0):
    """Add complex circular Gaussian noise at the requested full-band SNR."""
    iq = np.asarray(iq, dtype=np.complex128)
    p_sig = float(np.mean(np.abs(iq) ** 2))
    p_noise = p_sig / (10.0 ** (snr_db / 10.0))
    rng = np.random.default_rng(seed)
    noise = np.sqrt(p_noise / 2.0) * (
        rng.standard_normal(len(iq)) + 1j * rng.standard_normal(len(iq)))
    return iq + noise


def apply(iq, sym_rate=DEFAULT_SYM_RATE, sps=DEFAULT_SPS,
          cfo_hz=0.0, phase_deg=0.0, timing_off_symbols=0.0,
          ppm=0.0, snr_db=None, seed=0):
    """Apply the full impairment set in the documented order.

    Returns ``(impaired_iq, truth)`` where ``truth`` records exactly what was
    applied, so a test can report it rather than assume it.
    """
    fs = sym_rate * sps
    out = add_sample_rate_offset(iq, ppm)
    out = add_cfo(out, cfo_hz, fs, phase0=np.deg2rad(phase_deg))
    out = add_timing_offset(out, timing_off_symbols * sps)
    if snr_db is not None:
        out = add_awgn(out, snr_db, seed=seed)
    truth = {
        "cfo_hz": cfo_hz,
        "phase_deg": phase_deg,
        "timing_off_symbols": timing_off_symbols,
        "ppm": ppm,
        "snr_db": snr_db,
        "esn0_db": None if snr_db is None else snr_to_esn0_db(snr_db, sps),
        "seed": seed,
    }
    return out, truth
