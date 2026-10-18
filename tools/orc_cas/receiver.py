"""Receiver-side state machine for the OrcXM CAS reference implementation.

A receiver holds one card key and learns everything else from the broadcast.
That is the whole point of the hierarchy: the head-end never addresses a
receiver interactively, it just re-broadcasts.

The property this class exists to demonstrate is **bounded damage**. A receiver
here can be revoked (tier mask 0), can fail closed on any authentication error,
and cannot open a message sealed for anyone else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .keys import CardKey, CasError
from .messages import (ECMPayload, EMMPayload, open_content, open_ecm,
                       open_emm)


@dataclass
class Entitlement:
    key_id: int
    tier_mask: int
    service_key: bytes


@dataclass
class Receiver:
    """One receiver. Starts entitled to nothing; the broadcast fills it in."""

    card: CardKey
    name: str = "receiver"
    entitlements: dict[int, Entitlement] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    @property
    def tiers(self) -> int:
        """Union of authorised tiers across all installed services."""
        mask = 0
        for ent in self.entitlements.values():
            mask |= ent.tier_mask
        return mask

    def _note(self, msg: str) -> None:
        self.log.append(msg)

    def install_emm(self, blob: bytes) -> str:
        """Open a broadcast EMM and adopt its entitlement.

        A zero tier mask revokes: the service key is still stored, but the
        receiver is no longer authorised to use it.
        """
        try:
            payload = open_emm(self.card.key, self.card.card_id, blob)
        except CasError as exc:
            self._note(f"EMM rejected: {exc}")
            raise
        self.entitlements[payload.key_id] = Entitlement(
            payload.key_id, payload.tier_mask, payload.service_key)
        state = "revoked" if payload.tier_mask == 0 else f"tiers=0x{payload.tier_mask:x}"
        self._note(f"EMM accepted for key {payload.key_id}: {state}")
        return state

    def open_ecm(self, key_id: int, epoch: int, blob: bytes) -> bytes:
        """Recover the control word for one epoch, or fail closed."""
        ent = self.entitlements.get(key_id)
        if ent is None:
            self._note(f"no entitlement for key {key_id}")
            raise CasError(f"not entitled to key {key_id}")
        if ent.tier_mask == 0:
            self._note("entitlement revoked")
            raise CasError("entitlement revoked")
        try:
            payload: ECMPayload = open_ecm(ent.service_key, key_id, epoch, blob)
        except CasError as exc:
            self._note(f"ECM rejected: {exc}")
            raise
        if (payload.tiers_required & self.tiers) == 0:
            self._note(f"tier required 0x{payload.tiers_required:x}, have 0x{self.tiers:x}")
            raise CasError("insufficient tier")
        self._note(f"ECM opened for epoch {epoch}")
        return payload.cw

    def decrypt(self, key_id: int, epoch: int, ecm_blob: bytes,
                content_blob: bytes) -> bytes:
        """Full receive path: ECM -> control word -> content."""
        cw = self.open_ecm(key_id, epoch, ecm_blob)
        try:
            return open_content(cw, key_id, epoch, content_blob)
        except CasError as exc:
            self._note(f"content rejected: {exc}")
            raise
