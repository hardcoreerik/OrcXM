"""Key material for the OrcXM conditional-access reference implementation.

This is *our own* key hierarchy, for a system we design. It models the
three tiers every broadcast CAS converged on:

    card key (per receiver, long-lived)
      -> service key (per service, rotated)
        -> control word (per epoch, rotated fast)

The design rules here come from ``docs/cas-design-2026-10-17.md``. The two
that shape this module:

* Every tier is derived through HKDF-SHA256, so keys are one-way. Holding a
  control word tells you nothing about any other epoch, and holding a service
  key tells you nothing about the card key that delivered it.
* Nothing is a raw shared secret reused across purposes. A key id and an epoch
  are bound in, so a key for one purpose cannot be substituted for another.

This is a reference implementation, not a shipped product. See ``selftest.py``
for the properties it actually proves.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

LABEL = b"orc-cas-v1"
KEY_LEN = 32
CW_LEN = 32
CARD_ID_LEN = 8


class CasError(Exception):
    """Any conditional-access failure. Never partial: nothing is released."""


def _hkdf(ikm: bytes, info: bytes, length: int = KEY_LEN) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=LABEL,
                info=info).derive(ikm)


def new_master_secret() -> bytes:
    """The head-end's root secret. Never leaves the head-end."""
    return secrets.token_bytes(KEY_LEN)


def new_card_id() -> bytes:
    return secrets.token_bytes(CARD_ID_LEN)


@dataclass(frozen=True)
class CardKey:
    """A per-receiver long-lived key, provisioned at manufacture.

    This is the tier the whole design cannot protect: it lives in hardware the
    customer owns. Everything else here is arranged so that its compromise is
    bounded and revocable rather than fatal.
    """

    card_id: bytes
    key: bytes

    def __post_init__(self) -> None:
        if len(self.card_id) != CARD_ID_LEN:
            raise ValueError(f"card_id must be {CARD_ID_LEN} bytes")
        if len(self.key) != KEY_LEN:
            raise ValueError(f"key must be {KEY_LEN} bytes")


@dataclass(frozen=True)
class ServiceKey:
    """A per-service key, delivered to a card inside an EMM."""

    key_id: int
    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) != KEY_LEN:
            raise ValueError(f"key must be {KEY_LEN} bytes")


def new_card_key(card_id: bytes | None = None) -> CardKey:
    return CardKey(card_id if card_id is not None else new_card_id(),
                   secrets.token_bytes(KEY_LEN))


def derive_service_key(master: bytes, key_id: int) -> ServiceKey:
    """Head-end derivation for a service key. One-way from ``master``."""
    return ServiceKey(key_id,
                      _hkdf(master, LABEL + b"|service|" + key_id.to_bytes(4, "big")))


def derive_cw(master: bytes, epoch: int) -> bytes:
    """Control word for one epoch.

    Derived rather than stored, so the head-end holds one secret instead of a
    table, and so epochs are independent: a leaked control word reveals nothing
    about the epoch before or after it.
    """
    return _hkdf(master, LABEL + b"|cw|" + epoch.to_bytes(8, "big"), CW_LEN)
