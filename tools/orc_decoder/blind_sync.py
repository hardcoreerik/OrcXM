"""Blind frame-sync search for the OrcXM decoder.

Problem: XM's real sync word and frame length are unknown. Given a
demodulated bitstream, find candidate frame periods and recover the
sync pattern — without knowing what to look for.

Method:
1. Autocorrelation finds repeating structure -> candidate periods.
2. For each period, bits at fixed offsets mod period: sync positions
   have low entropy (same value every frame), data positions ~50%.
3. Low-entropy runs spell out the sync word.
"""

import numpy as np


def find_periods(bits, min_period=64, max_period=8192, top_n=5):
    """Find candidate frame periods via autocorrelation.

    Returns list of (period, score) sorted by score descending.
    Score is the normalized autocorrelation peak height.
    """
    bits = np.asarray(bits, dtype=np.float64)
    # Bipolar for autocorrelation: 0 -> -1, 1 -> +1
    x = 2 * bits - 1
    n = len(x)
    # Only compute lags in range
    scores = []
    # Use FFT-based autocorrelation for speed
    f = np.fft.rfft(x, n=n + max_period)
    acf = np.fft.irfft(f * np.conj(f), n=n + max_period)[:max_period + 1]
    acf = acf / acf[0]  # normalize
    for p in range(min_period, max_period + 1):
        scores.append((p, float(acf[p])))
    scores.sort(key=lambda t: -t[1])
    # Filter harmonics: keep a period only if it's not a multiple of a
    # stronger shorter period
    kept = []
    for p, s in scores:
        if len(kept) >= top_n:
            break
        if any(p % kp == 0 for kp, _ in kept):
            continue
        kept.append((p, s))
    return kept


def bit_entropy(bits_at_offset):
    """Binary entropy of bits observed at one offset across frames."""
    p1 = np.mean(bits_at_offset)
    if p1 <= 0 or p1 >= 1:
        return 0.0
    return -(p1 * np.log2(p1) + (1 - p1) * np.log2(1 - p1))


def recover_sync(bits, period, entropy_thresh=0.2, min_run=16):
    """Recover candidate sync word at a given period.

    Returns list of (offset, sync_bits) for low-entropy runs of at
    least min_run bits.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    n_frames = len(bits) // period
    if n_frames < 4:
        return []
    trimmed = bits[:n_frames * period].reshape(n_frames, period)
    # Entropy per offset
    ent = np.array([bit_entropy(trimmed[:, i]) for i in range(period)])
    # Majority vote per offset
    vote = (np.mean(trimmed, axis=0) > 0.5).astype(np.uint8)
    # Find low-entropy runs
    runs = []
    i = 0
    while i < period:
        if ent[i] < entropy_thresh:
            j = i
            while j < period and ent[j] < entropy_thresh:
                j += 1
            if j - i >= min_run:
                runs.append((i, vote[i:j].copy()))
            i = j
        else:
            i += 1
    return runs


def blind_search(bits, min_period=64, max_period=8192, top_n=3):
    """Full blind search: periods -> sync candidates.

    Returns dict: {period: [(offset, sync_bits), ...]}.
    """
    result = {}
    for period, score in find_periods(bits, min_period, max_period, top_n):
        runs = recover_sync(bits, period)
        if runs:
            result[period] = {"score": score, "syncs": runs}
    return result
