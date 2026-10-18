"""Frame synchronisation for the OrcXM decoder.

Two distinct jobs live here, and keeping them apart matters:

* **Marker search** (:func:`find_sync`) — correlate hard bits against a sync
  word.  Useful only on a signal whose marker you already know, i.e. the
  test carrier we build ourselves.  There is deliberately **no default sync
  word**: the previous default was ``0x1ACFFC1D``, the CCSDS attached sync
  marker, which SDARS does not use.  Searching a real SDARS capture for it
  cannot succeed and produces false-alarm sets that look like data.

* **Marker-free periodicity** (:func:`find_frame_period`) — look for the
  published XM master-frame period (432 ms) directly in a per-symbol
  feature series.  This is the only framing test that can work on a real
  capture, because it assumes nothing about a bit pattern.
"""

import math

import numpy as np


def sync_bits(sync_word, sync_len):
    """Sync word as an array of 0/1, MSB first."""
    return np.array([(sync_word >> i) & 1 for i in range(sync_len - 1, -1, -1)],
                    dtype=np.uint8)


def false_alarm_rate(sync_len=32, max_errors=0, bit_rate=1.64e6):
    """Expected random-match rate for a marker search.

    A 32-bit marker searched with two bit errors tolerated matches noise
    roughly every five seconds at 1.64 Mbit/s, which is why ``max_errors``
    must never be chosen by feel.  Callers should compute this before
    trusting any hit set.
    """
    hits = sum(math.comb(sync_len, k) for k in range(max_errors + 1))
    p = hits / float(2 ** sync_len)
    per_second = p * bit_rate
    return {
        "p_per_bit": p,
        "hits_per_second": per_second,
        "seconds_per_hit": (1.0 / per_second) if per_second > 0 else float("inf"),
    }


def required_sync_len(bit_rate=1.64e6, max_seconds_per_hit=3600.0):
    """Shortest marker, with zero bit errors tolerated, that is worth using."""
    if bit_rate <= 0 or max_seconds_per_hit <= 0:
        raise ValueError("bit_rate and max_seconds_per_hit must be positive")
    return int(math.ceil(math.log2(bit_rate * max_seconds_per_hit)))


def find_sync(bits, sync_word, sync_len=None, max_errors=0):
    """Locate sync-word positions in a hard-bit array.

    ``sync_word`` is required and ``max_errors`` defaults to zero; see
    :func:`false_alarm_rate` for why.
    """
    if sync_len is None:
        sync_len = max(8, (int(sync_word).bit_length() + 7) // 8 * 8)
    bits = np.asarray(bits, dtype=np.uint8)
    sync = sync_bits(sync_word, sync_len)
    n = len(bits) - sync_len + 1
    if n <= 0:
        return np.array([], dtype=np.int64)
    dist = np.zeros(n, dtype=np.int32)
    for i in range(sync_len):
        dist += (bits[i:i + n] != sync[i])
    hits = np.where(dist <= max_errors)[0]
    if len(hits) == 0:
        return hits
    keep = [hits[0]]
    for h in hits[1:]:
        if h - keep[-1] >= sync_len:
            keep.append(h)
    return np.array(keep, dtype=np.int64)


def frame_period(hits):
    """Median spacing between sync hits, in bits. ``None`` if fewer than two."""
    if len(hits) < 2:
        return None
    return int(np.median(np.diff(hits)))


def rotate_bits(bits, quarter_turns=0, swap=False):
    """Apply one QPSK lock-quadrant convention to a hard-bit stream.

    A decision-directed QPSK Costas loop settles to one of **four equilibria 90
    degrees apart**, so the recovered bit pairs are the true ones rotated by
    some multiple of 90 degrees.  Rotating the constellation by 90 degrees maps
    the bit pair ``(I, Q)`` to ``(not Q, I)``; 180 degrees is a plain inversion;
    270 degrees is ``(Q, not I)``.

    ``swap`` is a *different* error: it models the receiver's I and Q being
    cross-connected.  That is a reflection, not a rotation, and it must not be
    conflated with the lock quadrant.  Searching the two axes independently
    covers both.

    This distinction is not academic.  Searching only ``swap`` and ``invert``
    covers ``{id, (Q,I), (not I,not Q), (not Q,not I)}`` while the four lock
    quadrants are ``{id, (not Q,I), (not I,not Q), (Q,not I)}``: the two sets
    agree on just two of four.  A loop that settled a quarter turn away then
    finds no marker at all and the pipeline reports zero frames, which reads
    as a dead receiver rather than as a convention mismatch.
    """
    b = np.asarray(bits, dtype=np.uint8)
    if len(b) % 2:
        b = b[:-1]
    pairs = b.reshape(-1, 2)
    if swap:
        pairs = pairs[:, ::-1]
    k = quarter_turns % 4
    if k == 0:
        out = pairs
    elif k == 1:
        out = np.stack([1 - pairs[:, 1], pairs[:, 0]], axis=1)
    elif k == 2:
        out = 1 - pairs
    else:
        out = np.stack([pairs[:, 1], 1 - pairs[:, 0]], axis=1)
    return out.reshape(-1)


def find_sync_with_rotation(bits, sync_word, sync_len=None, max_errors=0,
                            try_swap=True):
    """Search every QPSK lock quadrant (and I/Q wiring) and report hits each."""
    results = []
    for swap in ((False, True) if try_swap else (False,)):
        for k in range(4):
            rot = rotate_bits(bits, quarter_turns=k, swap=swap)
            hits = find_sync(rot, sync_word, sync_len=sync_len,
                             max_errors=max_errors)
            results.append({"quarter_turns": k, "swap": swap,
                            "n_hits": int(len(hits)), "hits": hits,
                            "bits": rot})
    results.sort(key=lambda r: -r["n_hits"])
    return results


def extract_frames(bits, hits, frame_len_bits):
    """Slice the bitstream into frames starting at sync positions."""
    bits = np.asarray(bits, dtype=np.uint8)
    return [bits[h:h + frame_len_bits] for h in hits
            if h + frame_len_bits <= len(bits)]


def verify_frames(frames, sync_word, sync_len=None, counter_offset=None,
                  counter_len=16):
    """Check the *synthetic* frame layout: [sync][16-bit counter][payload].

    This layout is OrcXM's own invention, for exercising the pipeline. It is
    not an SDARS frame and nothing here should be read as evidence about
    one.
    """
    if sync_len is None:
        sync_len = max(8, (int(sync_word).bit_length() + 7) // 8 * 8)
    if counter_offset is None:
        counter_offset = sync_len
    sync = sync_bits(sync_word, sync_len)
    counters = []
    n_ok = n_bad = 0
    for f in frames:
        if len(f) < counter_offset + counter_len:
            n_bad += 1
            continue
        if np.array_equal(f[:sync_len], sync):
            chunk = f[counter_offset:counter_offset + counter_len]
            counters.append(int("".join(map(str, chunk)), 2))
            n_ok += 1
        else:
            n_bad += 1
    drops = sum(1 for a, b in zip(counters, counters[1:])
                if (b - a) % 65536 != 1)
    return n_ok, n_bad, drops, counters


def expected_frame_period(sym_rate=1.64e6, frame_ms=432.0):
    """XM master-frame length in symbols, from the published frame duration."""
    return frame_ms * 1e-3 * sym_rate


def periodicity_score(series, lag, max_lag_dev=0.02):
    """Normalised autocorrelation of ``series`` near ``lag``.

    Returns ``(best_lag, score)`` with ``score`` in roughly [-1, 1].
    """
    x = np.asarray(series, dtype=np.float64)
    if len(x) < 8:
        return None, float("nan")
    x = x - np.mean(x)
    n = len(x)
    lag = int(round(lag))
    dev = max(1, int(round(lag * max_lag_dev)))
    lo, hi = max(1, lag - dev), min(n - 2, lag + dev)
    if hi <= lo:
        return None, float("nan")
    denom = float(np.dot(x, x)) or 1e-30
    best_lag, best = None, -2.0
    for L in range(lo, hi + 1):
        val = float(np.dot(x[:-L], x[L:])) / denom
        if val > best:
            best_lag, best = L, val
    return best_lag, best


def find_frame_period(symbol_power, sym_rate=1.64e6, frame_ms=432.0,
                      max_lag_dev=0.02, submultiples=4):
    """Marker-free search for the XM master-frame period.

    ``symbol_power`` is any per-symbol feature series (``|s|^2`` is the
    obvious one).  A real frame structure shows up as a peak at the frame
    period; noise does not.  ``control`` is the same measurement at an
    unrelated lag, so a high score without a low control is not evidence.

    Needs at least two frames of symbols: the 432 ms frame is 708,480
    symbols, so about 1.4 M symbols, i.e. roughly 0.86 s of 1.64 Msym/s
    signal.  This is far beyond what an ESP32-S3 snapshot can hold, which is
    the arithmetic reason the S3 path cannot close framing.
    """
    expected = expected_frame_period(sym_rate, frame_ms)
    lag, score = periodicity_score(symbol_power, expected, max_lag_dev)
    ctrl_lag, ctrl = periodicity_score(symbol_power, expected * 1.37, max_lag_dev)
    subs = []
    for k in range(2, submultiples + 1):
        s_lag, s_score = periodicity_score(symbol_power, expected / k,
                                           max_lag_dev)
        subs.append({"divisor": k, "lag": s_lag, "score": s_score})
    n = len(np.asarray(symbol_power))
    return {
        "frame_ms": frame_ms,
        "expected_lag_symbols": expected,
        "needed_symbols": int(math.ceil(2 * expected)),
        "available_symbols": n,
        "covered": n >= 2 * expected,
        "lag": lag,
        "score": score,
        "control_lag": ctrl_lag,
        "control": ctrl,
        "submultiples": subs,
    }
