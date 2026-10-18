#!/usr/bin/env python3
"""Self-test for the OrcXM conditional-access reference implementation.

Run this before trusting anything in ``docs/cas-design-2026-10-17.md``:

    python tools/orc_cas/selftest.py

Exit code 0 means every property the design claims actually holds. Each check
below corresponds to a countermeasure in the design document's checklist, and
each one would fail if that countermeasure were removed.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orc_cas import keys, messages                      # noqa: E402
from orc_cas.cw import ControlWordSchedule              # noqa: E402
from orc_cas.headend import HeadEnd                     # noqa: E402
from orc_cas.keys import CasError                       # noqa: E402
from orc_cas.messages import (ECMPayload, EMMPayload, seal,  # noqa: E402
                              seal_ecm, seal_emm, unseal)
from orc_cas.receiver import Receiver                   # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        _failures.append(name)


def rejects(fn, *args) -> bool:
    """True when the call fails closed with CasError."""
    try:
        fn(*args)
    except CasError:
        return True
    except Exception:
        return False
    return False


KEY_ID = 1
TIER_BASIC = 0b01
TIER_PREMIUM = 0b10
CONTENT = b"OrcXM transport payload, not the real thing"


def main() -> int:
    print("OrcXM conditional-access self-test\n")
    he = HeadEnd()
    entitled = Receiver(keys.new_card_key(), name="entitled")
    other = Receiver(keys.new_card_key(), name="other-card")

    # --- 1. the happy path -----------------------------------------------------
    print("1. entitled receiver")
    entitled.install_emm(he.make_emm(entitled.card, KEY_ID, TIER_BASIC))
    epoch = 42
    ecm = he.make_ecm(KEY_ID, epoch, TIER_BASIC)
    blob = he.scramble(KEY_ID, epoch, CONTENT)
    got = entitled.decrypt(KEY_ID, epoch, ecm, blob)
    check("content round-trips", got == CONTENT,
          f"recovered {len(got)} bytes, matches plaintext")

    # --- 2. an unentitled receiver gets nothing -------------------------------
    print("\n2. unentitled receiver")
    check("no entitlement means no control word",
          rejects(other.open_ecm, KEY_ID, epoch, ecm),
          "failed closed before touching the ciphertext")

    # --- 3. card binding ------------------------------------------------------
    print("\n3. card binding")
    for_card = he.make_emm(entitled.card, KEY_ID, TIER_BASIC)
    check("an EMM addressed to another card is rejected",
          rejects(other.install_emm, for_card),
          "card key mismatch; AEAD refused it")

    # With per-card unique keys the key alone does that job, so the check above
    # passes even if the card id is not bound into the AAD. The binding only
    # carries weight when one key is shared across a group of cards, which is a
    # real deployment model -- so test that case explicitly.
    shared_key = keys.new_card_key().key
    card_a = keys.CardKey(b"cardAAAA", shared_key)
    card_b = keys.CardKey(b"cardBBBB", shared_key)
    recv_b = Receiver(card_b, name="group-b")
    check("with a shared group key, card id still separates receivers",
          rejects(recv_b.install_emm, he.make_emm(card_a, KEY_ID, TIER_BASIC)),
          "same key, different card id; the AAD binding is what refuses it")

    # --- 4. integrity ---------------------------------------------------------
    print("\n4. integrity")
    flipped = bytearray(ecm)
    flipped[-1] ^= 0x01
    check("a tampered ECM is rejected",
          rejects(entitled.open_ecm, KEY_ID, epoch, bytes(flipped)),
          "tag check failed")
    flipped_content = bytearray(blob)
    flipped_content[16] ^= 0x01
    check("tampered content is rejected",
          rejects(entitled.decrypt, KEY_ID, epoch, ecm, bytes(flipped_content)),
          "tag check failed")
    check("a truncated blob is rejected",
          rejects(unseal, entitled.entitlements[KEY_ID].service_key,
                  b"x", ecm[:20]),
          "length or tag check failed")

    # --- 5. replay ------------------------------------------------------------
    print("\n5. replay")
    check("an ECM cannot be replayed at a later epoch",
          rejects(entitled.open_ecm, KEY_ID, epoch + 1, ecm),
          "epoch is bound into the AAD")
    check("content cannot be replayed at a later epoch",
          rejects(entitled.decrypt, KEY_ID, epoch + 1, ecm, blob),
          "epoch is bound into the AAD")

    # --- 6. tier enforcement --------------------------------------------------
    print("\n6. tier enforcement")
    premium_only = he.make_ecm(KEY_ID, epoch, TIER_PREMIUM)
    check("a tier the receiver lacks is refused",
          rejects(entitled.open_ecm, KEY_ID, epoch, premium_only),
          f"required 0x{TIER_PREMIUM:x}, receiver has 0x{entitled.tiers:x}")

    # --- 7. revocation --------------------------------------------------------
    print("\n7. revocation")
    revoke = he.make_emm(entitled.card, KEY_ID, 0)
    state = entitled.install_emm(revoke)
    check("a zero tier mask revokes", state == "revoked", f"state={state}")
    check("a revoked receiver cannot open an ECM",
          rejects(entitled.open_ecm, KEY_ID, epoch, he.make_ecm(KEY_ID, epoch, TIER_BASIC)),
          "revocation checked before any crypto")
    check("a revoked receiver cannot decrypt content",
          rejects(entitled.decrypt, KEY_ID, epoch,
                  he.make_ecm(KEY_ID, epoch, TIER_BASIC), blob),
          "fails closed end to end")

    # --- 8. control-word schedule --------------------------------------------
    print("\n8. control-word schedule")
    sched = ControlWordSchedule(he.master, rotation_s=10.0)
    cw_a, cw_b = sched.cw(1000), sched.cw(1001)
    check("epochs have independent control words",
          cw_a != cw_b and len(cw_a) == keys.CW_LEN,
          f"cw(1000) != cw(1001), {len(cw_a)} bytes each")
    check("the schedule is deterministic",
          sched.cw(1000) == cw_a, "same epoch returns the same CW")
    ep, start, end = sched.window(1234.5)
    check("time maps to an epoch window",
          ep == 123 and start <= 1234.5 < end,
          f"t=1234.5s -> epoch {ep}, window [{start:.0f},{end:.0f})")
    other_master = HeadEnd()
    check("a different root secret yields different control words",
          ControlWordSchedule(other_master.master).cw(1000) != cw_a,
          "CW schedule is bound to the head-end secret")

    # --- 9. freshness ---------------------------------------------------------
    print("\n9. nonce freshness")
    a = seal(sched.cw(1000), b"aad", b"same plaintext")
    b = seal(sched.cw(1000), b"aad", b"same plaintext")
    check("sealing the same plaintext twice differs", a != b,
          "fresh nonce per message, so a carousel does not repeat ciphertext")
    check("both decrypt to the same plaintext",
          unseal(sched.cw(1000), b"aad", a) == unseal(sched.cw(1000), b"aad", b),
          "freshness does not cost correctness")

    # --- 10. payload encoding -------------------------------------------------
    print("\n10. payload round-trip")
    emm_p = EMMPayload(KEY_ID, TIER_BASIC, keys.new_card_key().key)
    ecm_p = ECMPayload(KEY_ID, epoch, TIER_BASIC, sched.cw(epoch))
    check("EMM payload survives encode/decode",
          EMMPayload.from_bytes(emm_p.to_bytes()) == emm_p, "byte-identical")
    check("ECM payload survives encode/decode",
          ECMPayload.from_bytes(ecm_p.to_bytes()) == ecm_p, "byte-identical")
    check("a malformed payload is rejected rather than half-parsed",
          rejects(EMMPayload.from_bytes, b"\x00" * 7), "length checked")

    print()
    if _failures:
        print(f"FAILED: {len(_failures)} check(s): " + ", ".join(_failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
