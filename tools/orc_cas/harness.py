#!/usr/bin/env python3
"""End-to-end walkthrough of the OrcXM CAS reference implementation.

    python tools/orc_cas/harness.py

Shows the whole cycle on one console: a head-end broadcasts, an entitled
receiver plays, a bystander gets nothing, and then the entitled receiver is
revoked mid-session and stops playing. This is the behaviour that
``docs/cas-design-2026-10-17.md`` argues for, made runnable.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orc_cas import keys                       # noqa: E402
from orc_cas.headend import HeadEnd            # noqa: E402
from orc_cas.keys import CasError              # noqa: E402
from orc_cas.receiver import Receiver          # noqa: E402

KEY_ID = 1
TIER = 0b01
EPOCH = 7
CONTENT = b"the transport frame that only a paying receiver may read"


def attempt(label: str, fn, *args) -> None:
    try:
        out = fn(*args)
        shown = out if isinstance(out, str) else f"{len(out)} bytes recovered"
        print(f"  {label:<34} OK      {shown}")
    except CasError as exc:
        print(f"  {label:<34} DENIED  {exc}")


def main() -> int:
    print("OrcXM conditional access: end-to-end walkthrough\n")
    he = HeadEnd()

    paying = Receiver(keys.new_card_key(), name="subscriber")
    bystander = Receiver(keys.new_card_key(), name="bystander")

    print(f"control word rotates every {he.schedule.rotation_s:.0f} s; "
          f"epoch {EPOCH} is scrambled under CW {he.schedule.cw(EPOCH)[:4].hex()}...\n")

    ecm = he.make_ecm(KEY_ID, EPOCH, TIER)
    content = he.scramble(KEY_ID, EPOCH, CONTENT)

    print("1. before anyone is authorised")
    attempt("subscriber reads", paying.decrypt, KEY_ID, EPOCH, ecm, content)

    print("\n2. head-end addresses an EMM to the subscriber")
    attempt("subscriber installs EMM", paying.install_emm,
            he.make_emm(paying.card, KEY_ID, TIER))
    attempt("subscriber reads", paying.decrypt, KEY_ID, EPOCH, ecm, content)

    print("\n3. a bystander with no EMM, same broadcast")
    attempt("bystander reads", bystander.decrypt, KEY_ID, EPOCH, ecm, content)

    print("\n4. subscriber is revoked mid-session (tier mask 0)")
    attempt("subscriber installs revocation", paying.install_emm,
            he.make_emm(paying.card, KEY_ID, 0))
    attempt("subscriber reads", paying.decrypt, KEY_ID, EPOCH, ecm, content)

    print("\n5. what each receiver recorded")
    for rx in (paying, bystander):
        print(f"  {rx.name}:")
        for line in rx.log:
            print(f"    - {line}")

    print("\nNote: revocation happened without the head-end knowing anything "
          "about the receiver\nbeyond its card key, and without any return path "
          "for this particular step --\nwhich is exactly why a periodic return "
          "path is the one architectural upgrade\nworth making.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
