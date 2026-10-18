"""Head-end for the OrcXM CAS reference implementation.

Holds the root secret and produces the broadcast: EMMs addressed to individual
receivers, ECMs carouselled to everyone, and content scrambled under the
current control word.

Deliberately separated from ``receiver.py`` so that the two sides cannot
accidentally share state. In a real system they never talk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cw import ControlWordSchedule
from .keys import (CardKey, ServiceKey, derive_service_key, new_master_secret)
from .messages import (ECMPayload, EMMPayload, seal_content, seal_ecm,
                       seal_emm)


@dataclass
class HeadEnd:
    """The broadcast side. One root secret, no knowledge of any card key."""

    master: bytes = field(default_factory=new_master_secret)
    schedule: ControlWordSchedule = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.schedule is None:
            self.schedule = ControlWordSchedule(self.master)

    def service_key(self, key_id: int) -> ServiceKey:
        return derive_service_key(self.master, key_id)

    def make_emm(self, card: CardKey, key_id: int, tier_mask: int) -> bytes:
        """Address a service key to one receiver, at a given tier.

        ``tier_mask=0`` is the revocation form: it re-delivers the key with no
        authorisation attached.
        """
        sk = self.service_key(key_id)
        payload = EMMPayload(key_id, tier_mask, sk.key)
        return seal_emm(card.key, card.card_id, payload)

    def make_ecm(self, key_id: int, epoch: int, tiers_required: int) -> bytes:
        """Carousel one ECM for an epoch. Broadcast to everybody."""
        sk = self.service_key(key_id)
        payload = ECMPayload(key_id, epoch, tiers_required,
                             self.schedule.cw(epoch))
        return seal_ecm(sk.key, key_id, epoch, payload)

    def scramble(self, key_id: int, epoch: int, plaintext: bytes) -> bytes:
        """Encrypt content under the epoch's control word."""
        return seal_content(self.schedule.cw(epoch), key_id, epoch, plaintext)
