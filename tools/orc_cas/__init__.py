"""OrcXM conditional-access reference implementation (our own design).

Not a model of anyone else's system. This is the counterpart to
``docs/cas-design-2026-10-17.md``: the doc says what to build and why, this
package builds it so the claims can be tested instead of asserted.

    keys.py      the card -> service -> control-word hierarchy (HKDF-SHA256)
    cw.py        control-word rotation schedule
    messages.py  ECM/EMM/content sealing (AES-256-GCM, context-bound)
    headend.py   the broadcast side
    receiver.py  the receiver side
    harness.py   end-to-end scenario
    selftest.py  the gate; exit 0 means every property holds

Run ``python tools/orc_cas/selftest.py`` before trusting any claim here.

Dependency: ``cryptography`` (>= 3.4 for AESGCM). No crypto is implemented in
this package; it only composes primitives.
"""

from . import cw, headend, keys, messages, receiver

__all__ = ["cw", "headend", "keys", "messages", "receiver"]
