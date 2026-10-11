"""S3 hardware IQ unpacker.

Reverse-engineered from ESP32-S3 libphy.a (phy_debug.o) via disassembly.
The S3's radio exposes raw IQ through a 16-bit register; get_iq_value()
unpacks it. This module replicates that unpacking so the decoder can
read S3 captures directly.
"""

import numpy as np


def unpack_iq(raw16, mode=1):
    """Unpack S3 raw IQ register values to signed I/Q.

    Args:
        raw16: array of uint16 raw register values
        mode: 0 = 5-bit I, 1 = 6-bit I (matches get_iq_value's mode arg)

    Returns:
        complex64 array, normalized to [-1, 1]
    """
    raw16 = np.asarray(raw16, dtype=np.uint16)

    # Q: bits [0:5], 6-bit signed
    q = (raw16 & 0x3F).astype(np.int16)
    q = np.where(q > 31, q - 64, q)

    # I: bits [6:11] (mode 0) or [6:12] (mode 1)
    if mode == 0:
        i = ((raw16 >> 6) & 0x1F).astype(np.int16)
        i = np.where(i > 15, i - 32, i)
        scale = 16.0
    else:
        i = ((raw16 >> 6) & 0x3F).astype(np.int16)
        i = np.where(i > 31, i - 64, i)
        scale = 32.0

    # Normalize: Q is always 6-bit, I depends on mode
    q_norm = q.astype(np.float32) / 32.0
    i_norm = i.astype(np.float32) / scale
    return (i_norm + 1j * q_norm).astype(np.complex64)


def unpack_dc(raw32):
    """Unpack S3 DC offset register (matches get_dc_value).

    Returns (i_dc, q_dc) as signed 16-bit ints.
    """
    raw32 = np.asarray(raw32, dtype=np.uint32)
    i_dc = ((raw32 >> 16) & 0xFFFF).astype(np.int16)
    q_dc = (raw32 & 0xFFFF).astype(np.int16)
    return i_dc, q_dc
