"""Control-word rotation for the OrcXM CAS reference implementation.

The control word is the short-lived key that actually scrambles content. Its
rotation period is the bound on how much a single leak is worth: whatever is
scrambled under one epoch is exposed if that epoch's CW escapes, and nothing
else is.

The schedule here is derived from the head-end's master secret by epoch index,
which gives two useful properties for free:

* the head-end stores no CW table, and
* epochs are cryptographically independent, so a recovered CW says nothing
  about adjacent epochs. (This matters: some historical systems derived the
  next CW from the last one, which turned one leak into a permanent one.)
"""

from __future__ import annotations

from .keys import derive_cw


class ControlWordSchedule:
    """Maps a time or an epoch index to a control word."""

    def __init__(self, master: bytes, rotation_s: float = 10.0) -> None:
        if rotation_s <= 0:
            raise ValueError("rotation_s must be positive")
        self._master = master
        self.rotation_s = rotation_s

    def epoch_at(self, t_s: float) -> int:
        return int(t_s // self.rotation_s)

    def cw(self, epoch: int) -> bytes:
        return derive_cw(self._master, epoch)

    def window(self, t_s: float) -> tuple[int, float, float]:
        """``(epoch, start_s, end_s)`` for the epoch containing ``t_s``."""
        epoch = self.epoch_at(t_s)
        start = epoch * self.rotation_s
        return epoch, start, start + self.rotation_s
