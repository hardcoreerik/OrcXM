"""OrcXM decoder pipeline (v0.1).

IQ -> [demodulator: Erik's side] -> bits -> frame_sync -> frames -> demux.

This module owns the software side: frame synchronization and the
pipeline scaffolding. Demodulation (QPSK: RRC, timing, Costas) lives
on the signal side; drop a demodulator in via `set_demodulator`.
"""

from . import frame_sync


_demodulator = None


def set_demodulator(fn):
    """Register a demodulator: fn(iq_samples) -> bit array (0/1)."""
    global _demodulator
    _demodulator = fn


def ideal_demodulator(iq):
    """Reference QPSK slicer for testing (no carrier/timing recovery).

    Only valid on clean, synchronized captures (e.g. the lab test
    carrier). Real captures need the full DSP chain.
    """
    import numpy as np
    iq = np.asarray(iq)
    # 4 samples/symbol; generator places symbol centers at indices
    # 0, 4, 8, ... after RRC + trimming, so sample there.
    sps = 4
    syms = iq[0::sps]
    bits = np.zeros(2 * len(syms), dtype=np.uint8)
    bits[0::2] = (syms.real < 0).astype(np.uint8)
    bits[1::2] = (syms.imag < 0).astype(np.uint8)
    return bits


def decode_file(path, sps=4, sync_word=frame_sync.DEFAULT_SYNC_WORD,
                frame_len_bits=None, max_errors=2):
    """Run the pipeline on a complex64 IQ file.

    Returns dict with hits, period, frames, and verification stats.
    """
    import numpy as np
    iq = np.fromfile(path, dtype=np.complex64)
    demod = _demodulator or ideal_demodulator
    bits = demod(iq)
    hits = frame_sync.find_sync(bits, sync_word=sync_word,
                                max_errors=max_errors)
    period = frame_sync.frame_period(hits)
    result = {"n_bits": len(bits), "hits": hits, "period": period,
              "frames": [], "n_ok": 0, "n_bad": 0, "drops": 0}
    if frame_len_bits and len(hits):
        frames = frame_sync.extract_frames(bits, hits, frame_len_bits)
        n_ok, n_bad, drops, _ = frame_sync.verify_frames(frames)
        result.update(frames=frames, n_ok=n_ok, n_bad=n_bad, drops=drops)
    return result
