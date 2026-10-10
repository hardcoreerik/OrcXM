"""Frame synchronization for the OrcXM decoder.

Finds frame boundaries in a demodulated bitstream by correlating against
a known sync word. Works on hard bits (0/1); soft-bit support can be
added when the demodulator provides LLRs.
"""

import numpy as np

DEFAULT_SYNC_WORD = 0x1ACFFC1D  # 32-bit, recognizable in hex dumps
DEFAULT_SYNC_LEN = 32


def _sync_bits(sync_word=DEFAULT_SYNC_WORD, sync_len=DEFAULT_SYNC_LEN):
    """Sync word as array of 0/1, MSB first."""
    return np.array([(sync_word >> i) & 1 for i in range(sync_len - 1, -1, -1)],
                    dtype=np.uint8)


def find_sync(bits, sync_word=DEFAULT_SYNC_WORD, sync_len=DEFAULT_SYNC_LEN,
              max_errors=2):
    """Locate sync word positions in a bit array.

    Returns array of start indices where the sync word matches with at
    most max_errors bit errors. Uses vectorized Hamming distance.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    sync = _sync_bits(sync_word, sync_len)
    n = len(bits) - sync_len + 1
    if n <= 0:
        return np.array([], dtype=np.int64)
    # Hamming distance at each position
    dist = np.zeros(n, dtype=np.int32)
    for i in range(sync_len):
        dist += (bits[i:i + n] != sync[i])
    hits = np.where(dist <= max_errors)[0]
    # De-duplicate overlapping hits (keep the first of a cluster)
    if len(hits) == 0:
        return hits
    keep = [hits[0]]
    for h in hits[1:]:
        if h - keep[-1] >= sync_len:
            keep.append(h)
    return np.array(keep, dtype=np.int64)


def frame_period(hits):
    """Estimate the frame period (in bits) from sync positions.

    Returns the median spacing, or None if fewer than 2 hits.
    """
    if len(hits) < 2:
        return None
    return int(np.median(np.diff(hits)))


def extract_frames(bits, hits, frame_len_bits):
    """Slice the bitstream into frames starting at sync positions.

    Returns list of bit arrays, one per complete frame.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    frames = []
    for h in hits:
        if h + frame_len_bits <= len(bits):
            frames.append(bits[h:h + frame_len_bits])
    return frames


def verify_frames(frames, sync_word=DEFAULT_SYNC_WORD,
                  sync_len=DEFAULT_SYNC_LEN, counter_offset=32,
                  counter_len=16):
    """Check sync word and frame counter continuity.

    Assumes frame layout: [sync (32b)][counter (16b)][payload...].
    Returns (n_ok, n_bad) and the list of observed counters.
    """
    sync = _sync_bits(sync_word, sync_len)
    counters = []
    n_ok = n_bad = 0
    for f in frames:
        if np.array_equal(f[:sync_len], sync):
            counters.append(int("".join(map(str, f[counter_offset:
                                                   counter_offset + counter_len])), 2))
            n_ok += 1
        else:
            n_bad += 1
    # Check counter continuity
    drops = sum(1 for a, b in zip(counters, counters[1:])
                if (b - a) % 65536 != 1)
    return n_ok, n_bad, drops, counters
