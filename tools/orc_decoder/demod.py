"""QPSK demodulator for the SDARS satellite waveform.

1.64 Msym/s, root-raised-cosine 0.15, root-raised-cosine matched filter,
Gardner symbol-timing recovery on a cubic interpolator, decision-directed
Costas carrier recovery, and a coarse carrier-offset estimate from the
fourth-power spectral line.

This replaces the hard slicer the pipeline used to ship.  The slicer was
valid because a Pluto TX/RX loop cable shares one clock: there was no
carrier offset to track and no timing offset to recover, and the symbols
happened to land on sample boundaries the generator chose.  None of that
holds for a real signal, so this module recovers all three quantities
instead of assuming them.
"""

import math

import numpy as np

from .interp import interp_cubic, interp_one
from .rrc import rrc_taps

# Loop signs. Gardner's detector output grows with symbol energy, so the
# error is normalised by the tracked amplitude before it reaches the loop
# filter; these signs are then pure convention, pinned by ``selftest.py``.
# The measured S-curve slope is 0.43 per symbol with its zero crossing
# exactly on the ISI-free instant, so the detector itself is unbiased.
_TED_SIGN = -1.0
_PED_SIGN = 1.0


def matched_filter(iq, sps=4, alpha=0.15, span=10):
    """Cascade the RX root-raised-cosine with the transmit one."""
    return np.convolve(np.asarray(iq, dtype=np.complex128),
                       rrc_taps(sps, alpha, span), mode="same")


def estimate_cfo(mf, sym_rate=1.64e6, sps=4, search_hz=250e3):
    """Coarse carrier offset from the fourth-power spectral line.

    For QPSK the fourth power removes the modulation (all four constellation
    points map to the same phase), leaving a line at ``4 * cfo``.  The
    estimate is taken from a decimated copy of the matched-filter output,
    where the residual ISI is small enough that the line is not buried by
    the envelope's own spectrum.

    Returns ``(cfo_hz, confidence)`` where confidence is the peak-to-median
    ratio of the search band.
    """
    sym = np.asarray(mf)[::sps]
    if len(sym) < 64:
        return 0.0, 0.0
    w = np.fft.fft(sym.astype(np.complex128) ** 4)
    freqs = np.fft.fftfreq(len(w), d=1.0 / sym_rate)
    band = np.abs(freqs) <= 4.0 * search_hz
    if not np.any(band):
        return 0.0, 0.0
    mag = np.abs(w)
    idx = np.flatnonzero(band)
    k = idx[int(np.argmax(mag[idx]))]
    median = float(np.median(mag[idx])) or 1e-30
    k0, k1, k2 = (k - 1) % len(w), k, (k + 1) % len(w)
    a, b, c = mag[k0], mag[k1], mag[k2]
    denom = a - 2.0 * b + c
    delta = 0.5 * (a - c) / denom if abs(denom) > 1e-30 else 0.0
    step = sym_rate / len(w)
    return float((freqs[k] + delta * step) / 4.0), float(b / median)


def estimate_initial_timing(mf, sps=4, span=10, window_symbols=400,
                            steps_per_symbol=16):
    """Find the sampling phase that maximises mean symbol energy.

    For a Nyquist pulse the ISI-free instant carries the most energy, so the
    maximum of ``mean |y|^2`` over one symbol period is a standard and cheap
    initial timing estimate.  Without it the tracking loop has to walk in
    from wherever it starts, and that acquisition transient is the dominant
    contribution to measured EVM: on a clean signal the first 500 symbols
    sit at ~46% EVM against ~6% once locked.
    """
    base = int(span * sps)
    n = min(len(mf) - base - 4, int(window_symbols * sps))
    if n < sps * 8:
        return float(base)
    seg = mf[base:base + n + 4]
    step = float(sps) / steps_per_symbol
    best_off, best_val = 0.0, -1.0
    for k in range(steps_per_symbol):
        off = k * step
        idx = np.arange(off, n, float(sps))
        vals = interp_cubic(seg, idx)
        val = float(np.mean(np.abs(vals) ** 2))
        if val > best_val:
            best_val, best_off = val, off
    return float(base) + best_off


def _loop_gains(bn_t, zeta):
    th = bn_t
    d = 1.0 + 2.0 * zeta * th + th * th
    return 4.0 * zeta * th / d, 4.0 * th * th / d


def _lock_angle_deg(symbols):
    """``arg(mean(z^4))`` in degrees.

    ~180 degrees means a true QPSK lock; ~0 degrees means the 45 degree
    false lock where the constellation sits on the axes.  Immune to the
    four-fold quadrant ambiguity, because any 90 degree rotation moves the
    argument by a full turn.
    """
    if len(symbols) == 0:
        return float("nan")
    return float(np.degrees(np.angle(np.mean(symbols ** 4))))


def _lock_score(symbols):
    """+1 at a true QPSK lock, -1 at the 45 degree null, ~0 for garbage.

    Computed on unit-modulus symbols, so it is scale-invariant.  Using the
    raw fourth moment is not safe: a couple of edge-of-buffer interpolation
    artefacts with |z| ten times the mean were enough to invert the sign of
    a perfectly good lock.
    """
    if len(symbols) == 0:
        return 0.0
    mag = np.abs(symbols)
    keep = mag > 0.0
    if not np.any(keep):
        return 0.0
    u = symbols[keep] / mag[keep]
    return float(-np.real(np.mean(u ** 4)))


def _track(mf, sps, kp_ph, ki_ph, kp_t, ki_t, n_sym_max, phase0=0.0,
           t0=None):
    """Run the timing and carrier loops once and return the recovered symbols."""
    half = 0.5 * sps
    t_samp = t0 if t0 is not None else float(sps * 10)
    t_int = 0.0
    phi = phase0
    phi_int = 0.0
    amp = None
    y_prev = 0j
    symbols = np.empty(n_sym_max, dtype=np.complex128)
    times = np.empty(n_sym_max, dtype=np.float64)
    n_out = 0

    while n_out < n_sym_max and t_samp + 3.0 < len(mf):
        t_used = t_samp
        y_c = interp_one(mf, t_used)
        y_m = interp_one(mf, t_used - half)

        if amp is None:
            amp = max(abs(y_c), 1e-12)
        a2 = max(amp * amp, 1e-18)

        e_t = _TED_SIGN * ((y_c - y_prev) * y_m.conjugate()).real / a2
        e_t = max(-4.0, min(4.0, e_t))

        d = y_c * complex(math.cos(phi), -math.sin(phi))
        dr, di = d.real, d.imag
        e_p = _PED_SIGN * (math.copysign(1.0, dr) * di
                           - math.copysign(1.0, di) * dr) / max(abs(dr) + abs(di), 1e-12)
        e_p = max(-4.0, min(4.0, e_p))

        amp += 0.001 * (abs(d) - amp)
        phi_int += ki_ph * e_p
        phi += kp_ph * e_p + phi_int
        t_int += ki_t * e_t
        t_samp += sps + kp_t * e_t + t_int

        symbols[n_out] = d
        times[n_out] = t_used
        n_out += 1
        y_prev = y_c

    return symbols[:n_out], times[:n_out]


def qpsk_demod(iq, sps=4, alpha=0.15, span=10, sym_rate=1.64e6,
               cfo_search_hz=250e3, estimate_carrier=True,
               use_initial_timing=True,
               bn_t_phase=0.02, bn_t_timing=0.01, zeta=0.707,
               max_symbols=None, max_hypotheses=2):
    """Demodulate a QPSK carrier and recover bits.

    Returns ``symbols``, ``bits``, the coarse carrier estimate, EVM, the
    fitted timing drift (a direct read-out of the sample-rate offset the loop
    had to absorb), and which phase hypothesis won.

    A decision-directed Costas loop has an unstable equilibrium at 45
    degrees, where its detector reads exactly zero.  On a signal with no
    noise and no frequency offset the loop can settle there and stay: the
    four constellation points land on the axes, a quarter of the bits slice
    as noise, and EVM still looks acceptable.  The fix is not a better
    detector but a second hypothesis: if the first attempt locks near the
    null, re-run the loop started a quarter turn away and keep whichever
    attempt looks more like a real QPSK lock.
    """
    iq = np.asarray(iq, dtype=np.complex128)
    fs = sym_rate * sps
    mf = matched_filter(iq, sps=sps, alpha=alpha, span=span)

    cfo_est, cfo_conf = 0.0, 0.0
    if estimate_carrier:
        cfo_est, cfo_conf = estimate_cfo(mf, sym_rate=sym_rate, sps=sps,
                                         search_hz=cfo_search_hz)
        n = np.arange(len(mf), dtype=np.float64)
        mf = mf * np.exp(-2j * np.pi * cfo_est * n / fs)

    kp_ph, ki_ph = _loop_gains(bn_t_phase, zeta)
    kp_t, ki_t = _loop_gains(bn_t_timing, zeta)
    kp_t *= sps
    ki_t *= sps

    n_sym_max = max_symbols or (len(mf) // sps)
    t0 = (estimate_initial_timing(mf, sps=sps, span=span)
          if use_initial_timing else float(span * sps))

    symbols, times = _track(mf, sps, kp_ph, ki_ph, kp_t, ki_t, n_sym_max, 0.0, t0)
    best_score = _lock_score(symbols)
    hypothesis_deg = 0.0

    for attempt in range(1, max_hypotheses):
        if best_score >= 0.5:
            break
        alt_phase = attempt * math.pi / 4.0
        alt_sym, alt_t = _track(mf, sps, kp_ph, ki_ph, kp_t, ki_t,
                                n_sym_max, alt_phase, t0)
        alt_score = _lock_score(alt_sym)
        if alt_score > best_score:
            symbols, times = alt_sym, alt_t
            best_score = alt_score
            hypothesis_deg = math.degrees(alt_phase)

    derotated_45 = False
    if best_score < -0.5:
        # Every hypothesis sat on the null; rotate the constellation back.
        symbols = symbols * complex(math.cos(math.pi / 4.0),
                                   -math.sin(math.pi / 4.0))
        best_score = _lock_score(symbols)
        derotated_45 = True

    lock_angle = _lock_angle_deg(symbols)

    n_out = len(symbols)
    bits = np.empty(2 * n_out, dtype=np.uint8)
    bits[0::2] = (symbols.real < 0).astype(np.uint8)
    bits[1::2] = (symbols.imag < 0).astype(np.uint8)

    return {
        "symbols": symbols,
        "bits": bits,
        "n_symbols": n_out,
        "cfo_hz_est": cfo_est,
        "cfo_confidence": cfo_conf,
        "fs_hz": fs,
        "sps": sps,
        "evm_pct": _evm_pct(symbols),
        "lock_angle_deg": lock_angle,
        "lock_score": best_score,
        "initial_phase_deg": hypothesis_deg,
        "derotated_45deg": derotated_45,
        "timing_drift_ppm": _drift_ppm(times, sps, sym_rate),
    }


def _evm_pct(symbols):
    """RMS error-vector magnitude against an ideal unit-RMS QPSK set."""
    if len(symbols) == 0:
        return float("nan")
    s = symbols - np.mean(symbols)
    rms = float(np.sqrt(np.mean(np.abs(s) ** 2)))
    if rms <= 0.0:
        return float("nan")
    s = s / rms
    ideal = (np.sign(s.real) + 1j * np.sign(s.imag)) / math.sqrt(2.0)
    return 100.0 * float(np.sqrt(np.mean(np.abs(s - ideal) ** 2)))


def _drift_ppm(times, sps, sym_rate):
    """Fit the sampling instants against symbol index to read off the clock skew."""
    n = len(times)
    if n < 16:
        return float("nan")
    i = np.arange(n, dtype=np.float64)
    resid = times - (times[0] + i * sps)
    slope = float(np.polyfit(i, resid, 1)[0])
    return 1e6 * slope / sps
