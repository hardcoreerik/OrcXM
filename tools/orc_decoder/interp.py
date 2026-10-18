"""Catmull-Rom interpolation at fractional sample positions.

Shared by the demodulator (symbol-timing recovery) and the channel model
(sample-rate offset, fractional delay), so that both treat the signal the
same way.
"""

import math

import numpy as np


def interp_cubic(y, t):
    """Interpolate complex array ``y`` at real positions ``t``.

    Catmull-Rom (cardinal cubic).  Positions within one sample of either end
    are clipped to the first/last valid cubic, which is why callers should
    leave the filter transients alone.
    """
    y = np.asarray(y, dtype=np.complex128)
    n = len(y)
    t = np.asarray(t, dtype=np.float64)
    out = np.zeros(len(t), dtype=np.complex128)
    if n < 4:
        return out
    i = np.floor(t).astype(np.int64)
    i = np.clip(i, 1, n - 3)
    f = t - i
    y0, y1, y2, y3 = y[i - 1], y[i], y[i + 1], y[i + 2]
    a = -0.5 * y0 + 1.5 * y1 - 1.5 * y2 + 0.5 * y3
    b = y0 - 2.5 * y1 + 2.0 * y2 - 0.5 * y3
    c = -0.5 * y0 + 0.5 * y2
    return ((a * f + b) * f + c) * f + y1


def interp_one(y, t):
    """Single-sample version of :func:`interp_cubic`, for tight loops."""
    i = int(math.floor(t))
    if i < 1 or i + 2 >= len(y):
        return 0j
    f = t - i
    y0, y1, y2, y3 = y[i - 1], y[i], y[i + 1], y[i + 2]
    a = -0.5 * y0 + 1.5 * y1 - 1.5 * y2 + 0.5 * y3
    b = y0 - 2.5 * y1 + 2.0 * y2 - 0.5 * y3
    c = -0.5 * y0 + 0.5 * y2
    return ((a * f + b) * f + c) * f + y1
