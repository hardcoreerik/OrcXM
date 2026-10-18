"""OrcXM decoder pipeline.

    IQ -> qpsk_demod -> bits -> frame_sync -> frames -> demux

The demodulator is real: root-raised-cosine matched filter, coarse carrier
offset from the fourth-power line, Gardner symbol-timing recovery on a
cubic interpolator, and a decision-directed Costas loop.  It replaces the
hard slicer that used to sit here and sample every fourth input sample.

That slicer was only ever valid because a Pluto loop-cable test shares one
clock with its receiver: no carrier offset to track, no timing offset to
recover, and symbols sitting on the sample boundaries the generator chose.
None of that is true of a real signal, which is why the substitution
matters more than it looks.

``set_demodulator`` remains as a test hook for injecting a different
demodulator; nothing in normal use should need it.
"""

import numpy as np

from . import demod as demod_mod
from . import frame_sync

_demodulator = None


def set_demodulator(fn):
    """Override the demodulator: ``fn(iq, **kwargs) -> {"bits": ..., ...}``."""
    global _demodulator
    _demodulator = fn


def demodulate(iq, sps=4, **kwargs):
    """Run the QPSK demodulator (or the override) over complex IQ samples."""
    fn = _demodulator or demod_mod.qpsk_demod
    return fn(iq, sps=sps, **kwargs)


def decode_bits(bits, sync_word, sync_len=None, frame_len_bits=None,
                max_errors=0, try_rotations=True):
    """Search a bit stream for the marker and slice frames.

    ``sync_word`` is required: there is no default, because a wrong marker
    silently produces a false-alarm set rather than an obvious failure.
    """
    if try_rotations:
        attempts = frame_sync.find_sync_with_rotation(
            bits, sync_word, sync_len=sync_len, max_errors=max_errors)
        best = attempts[0]
        bits = best["bits"]
        hits = best["hits"]
        quadrant = {"quarter_turns": best["quarter_turns"],
                    "swap": best["swap"],
                    "n_hits": best["n_hits"]}
    else:
        hits = frame_sync.find_sync(bits, sync_word, sync_len=sync_len,
                                    max_errors=max_errors)
        quadrant = None

    result = {
        "hits": hits,
        "n_hits": int(len(hits)),
        "period": frame_sync.frame_period(hits),
        "quadrant": quadrant,
        "frames": [],
        "n_ok": 0,
        "n_bad": 0,
        "drops": 0,
    }
    if frame_len_bits and len(hits):
        frames = frame_sync.extract_frames(bits, hits, frame_len_bits)
        n_ok, n_bad, drops, _ = frame_sync.verify_frames(
            frames, sync_word, sync_len=sync_len)
        result.update(frames=frames, n_ok=n_ok, n_bad=n_bad, drops=drops)
    return result


def decode_file(path, sync_word, sps=4, frame_len_bits=None, max_errors=0,
                n_bits=None):
    """Demodulate a complex64 IQ file and frame-sync the result."""
    iq = np.fromfile(path, dtype=np.complex64)
    d = demodulate(iq, sps=sps)
    bits = d["bits"] if n_bits is None else d["bits"][:n_bits]
    out = decode_bits(bits, sync_word, frame_len_bits=frame_len_bits,
                      max_errors=max_errors)
    out["demod"] = {k: v for k, v in d.items()
                    if k not in ("symbols", "bits")}
    return out
