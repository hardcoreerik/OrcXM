"""ECM/EMM/EMM message sealing for the OrcXM CAS reference implementation.

Every message is sealed with AES-256-GCM. The properties this module is
responsible for, and the historical failure each one answers:

* **Authenticated, not just encrypted.** A tampered or truncated message is
  rejected outright. (2000s systems shipped unauthenticated entitlement
  protocols and were replayed.)
* **Context-bound.** The additional authenticated data binds a message to its
  receiver and its epoch, so it cannot be replayed at a different time or
  opened by a different card even if the key is somehow known.
* **No partial release.** ``unseal`` either returns the plaintext or raises.
  There is no path that returns a partially-decrypted buffer.

Serialisation is deliberately trivial and fixed-width. A real deployment would
use a versioned, extensible format; the point here is the cryptography and the
binding, not the encoding.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .keys import LABEL, CasError, CW_LEN, CARD_ID_LEN

NONCE_LEN = 12
TAG_LEN = 16

_EMM_PAYLOAD = struct.Struct(">II")            # key_id, tier_mask
_ECM_PAYLOAD = struct.Struct(">IIQ")           # key_id, tiers_required, epoch


def seal(key: bytes, aad: bytes, plaintext: bytes) -> bytes:
    """AES-256-GCM seal. Returns ``nonce || ciphertext || tag``."""
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def unseal(key: bytes, aad: bytes, blob: bytes) -> bytes:
    """Open a sealed blob, or raise ``CasError``. Never returns partial data."""
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise CasError("sealed blob too short")
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    try:
        return AESGCM(key).decrypt(nonce, ct, aad)
    except InvalidTag as exc:
        raise CasError("authentication failed") from exc
    except Exception as exc:  # malformed key length etc.
        raise CasError(f"cannot open: {type(exc).__name__}") from exc


def _aad_emm(card_id: bytes) -> bytes:
    return LABEL + b"|EMM|" + card_id


def _aad_ecm(key_id: int, epoch: int) -> bytes:
    return LABEL + b"|ECM|" + key_id.to_bytes(4, "big") + epoch.to_bytes(8, "big")


def _aad_content(key_id: int, epoch: int) -> bytes:
    return LABEL + b"|content|" + key_id.to_bytes(4, "big") + epoch.to_bytes(8, "big")


@dataclass(frozen=True)
class EMMPayload:
    """Entitlement Management Message: delivers a service key to one card.

    ``tier_mask`` is the set of service tiers the card is authorised for. A
    zero mask is how revocation is expressed: the card still holds the key, but
    is no longer entitled to use it.
    """

    key_id: int
    tier_mask: int
    service_key: bytes

    def to_bytes(self) -> bytes:
        return _EMM_PAYLOAD.pack(self.key_id, self.tier_mask) + self.service_key

    @classmethod
    def from_bytes(cls, raw: bytes) -> "EMMPayload":
        head = _EMM_PAYLOAD.size
        if len(raw) != head + 32:
            raise CasError("malformed EMM payload")
        key_id, tier_mask = _EMM_PAYLOAD.unpack(raw[:head])
        return cls(key_id, tier_mask, raw[head:])


@dataclass(frozen=True)
class ECMPayload:
    """Entitlement Control Message: delivers the control word for one epoch."""

    key_id: int
    epoch: int
    tiers_required: int
    cw: bytes

    def to_bytes(self) -> bytes:
        return _ECM_PAYLOAD.pack(self.key_id, self.tiers_required,
                                 self.epoch) + self.cw

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ECMPayload":
        head = _ECM_PAYLOAD.size
        if len(raw) != head + CW_LEN:
            raise CasError("malformed ECM payload")
        key_id, tiers, epoch = _ECM_PAYLOAD.unpack(raw[:head])
        return cls(key_id, epoch, tiers, raw[head:])


def seal_emm(card_key: bytes, card_id: bytes, payload: EMMPayload) -> bytes:
    """Seal an EMM to one card. Only that card's key can open it."""
    if len(card_id) != CARD_ID_LEN:
        raise CasError("bad card id length")
    return seal(card_key, _aad_emm(card_id), payload.to_bytes())


def open_emm(card_key: bytes, card_id: bytes, blob: bytes) -> EMMPayload:
    return EMMPayload.from_bytes(unseal(card_key, _aad_emm(card_id), blob))


def seal_ecm(service_key: bytes, key_id: int, epoch: int,
             payload: ECMPayload) -> bytes:
    """Seal an ECM for one epoch. The epoch is bound, so it cannot be replayed."""
    return seal(service_key, _aad_ecm(key_id, epoch), payload.to_bytes())


def open_ecm(service_key: bytes, key_id: int, epoch: int,
             blob: bytes) -> ECMPayload:
    return ECMPayload.from_bytes(unseal(service_key,
                                        _aad_ecm(key_id, epoch), blob))


def seal_content(cw: bytes, key_id: int, epoch: int, plaintext: bytes) -> bytes:
    return seal(cw, _aad_content(key_id, epoch), plaintext)


def open_content(cw: bytes, key_id: int, epoch: int, blob: bytes) -> bytes:
    return unseal(cw, _aad_content(key_id, epoch), blob)
