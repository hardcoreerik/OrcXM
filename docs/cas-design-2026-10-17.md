# Conditional access: what 2000s-era broadcast CAS teaches, and what OrcXM should do instead

**Scope.** This is a design study drawn from published standards, published
analysis, and published post-mortems. It covers conditional-access
*architecture* — how a broadcast system distributes keys, why those designs
failed, and what a new system should do differently.

It is **not** a guide to attacking any deployed system, and it contains no
key-recovery technique, no exploit construction and nothing specific to any
operator's live service. The lessons here are the ones the industry published
about itself, after the fact, and they are the input to designing OrcXM's own
access control if it ever has one.

Related: [the SDARS system survey](siriusxm-research-2026-10-17.md) describes
where conditional access sits in a satellite radio stack, architecturally.
This document is about how to build such a thing properly.

---

## 1. The problem broadcast CAS was solving

A satellite or terrestrial broadcast has **no return path**. The operator
transmits once, to everyone, and cannot address an individual receiver
interactively. Yet it must:

- deliver content only to subscribers,
- add and remove subscribers without touching their hardware,
- and do all of it using equipment that costs as little as possible.

Those constraints are what produce the architecture. They are also what
doomed it.

## 2. The key hierarchy

Every broadcast CAS from that era converged on the same three-tier structure,
because each tier exists to work around a limit of the one below it.

```
 content ──encrypted under──> Control Word (CW)
                                 │  rotated every ~10–30 s
                                 │  too expensive to send per-subscriber
                                 ▼
                              ECM  (Entitlement Control Message)
                                 │  carries the CW + access criteria
                                 │  encrypted under a service key
                                 ▼
                              EMM  (Entitlement Management Message)
                                 │  carries subscriber rights
                                 │  encrypted under a per-card key
                                 ▼
                          smartcard (long-lived key burned in at manufacture)
```

- **Control Word** — a short block that actually scrambles the content. Rotated
  frequently so that any single leak has a bounded lifetime.
- **ECM** — broadcast to everyone, carrying the current CW sealed under a
  service key, together with the access criteria ("this programme needs
  subscription tier X"). Everyone receives it; only entitled cards can open it.
- **EMM** — addressed to individual cards, carrying entitlement changes:
  subscribe, unsubscribe, tier updates, key updates.

The hierarchy is sound engineering given the constraints. The failure was never
the layering — it was the premise underneath it.

## 3. The 2000s landscape

The market settled into a handful of vendors, each shipping a proprietary
scheme: **Nagravision**, **Irdeto**, **Viaccess**, **Conax**, **MediaGuard**,
**Cryptoworks**. Interoperability was handled by **SimulCrypt**
(ETSI TS 103 197), which let several vendors' systems share one multiplex by
having each seal the same CW for its own subscriber base.

The content scrambler was DVB's **Common Scrambling Algorithm** (DVB-CSA), a
1994-era construction with a 64-bit block. It was, initially, kept
confidential.

## 4. The structural failure

> **The trust anchor lived inside the attacker's equipment.**

Everything else follows from that one sentence. The per-card key had to be
present in a smartcard the customer physically possessed, in their home, with
unlimited time and whatever laboratory they cared to bring.

No amount of protocol design fixes this. Any secret that must reside in
customer-controlled hardware is, given sufficient motivation, extractable —
through memory recovery, fault injection, side channels, or simply a bug in the
card's own firmware. Broadcast CAS spent roughly fifteen years engineering
around an unsolvable premise, and the industry eventually stopped trying.

Three consequences followed mechanically rather than from any individual
mistake:

**One extraction is global.** A recovered card key can be served to everyone at
once. This is why *cardsharing* existed: because the CW must physically reach
the card, the card could be networked, and a single compromised subscription
became an unbounded service. The architecture guaranteed the market for it.

**Revocation was mostly theatre.** One-way broadcast lets you push new keys, but
you cannot confirm the old ones are dead, and you cannot distinguish a cloned
card from the genuine one. Revocation was a hope, not a mechanism.

**Obscurity was load-bearing.** Keeping DVB-CSA secret was meant to add
strength. It was reconstructed and published, and it is weak by modern
standards. The secrecy bought a few years and cost the industry the ability to
migrate: with an unpublished cipher, you cannot commission public analysis, and
without public analysis you cannot find out you are broken until you are.

## 5. Failure catalogue

Grouped by where the weakness lived, because that is what makes them reusable
as design warnings.

| Layer | Failure | Why it kept happening |
|---|---|---|
| **Cipher** | Bespoke, secret algorithms; short blocks; dated constructions | Belief that secrecy adds strength, and that a non-standard cipher is harder to attack. The reverse is true. |
| **Key management** | Long-lived shared secrets; no per-session keys; no forward secrecy | Simpler to manufacture and to operate. Cheap hardware forced a single static secret. |
| **Protocol** | Unauthenticated ECM/EMM; replay; weak or predictable CW generation | The entitlement protocol received far less scrutiny than the cipher, and was often the softer target. |
| **Deployment** | 10–20 year set-top box lifetimes; crypto unchangeable after shipment | Procurement cycles. A box you cannot update is a permanent liability. |
| **Architecture** | No return path, so no real revocation and no way to detect cloning | Inherited from broadcast, treated as an unchangeable constraint rather than a design choice. |

Note the shape: **the cipher was rarely the weakest link.** Across that era, the
compromises clustered in key management, entitlement protocols and deployment
lifetimes. Teams spent their effort on the cipher and lost through everything
around it.

## 6. What modern design does instead

The industry did not fix broadcast CAS — it **abandoned** it. The migration to
DRM with a back channel, and to network-delivered content, was driven by the
recognition that a bidirectional client can do what one-way broadcast
structurally cannot.

- **Standard AEAD only.** AES-GCM (NIST SP 800-38D) or ChaCha20-Poly1305
  (RFC 8439). Published, analysed, implemented in hardware, and free of the
  failure modes that come from rolling your own.
- **Per-session keys with a real handshake.** Ephemeral key agreement, so a
  compromise is bounded to a session rather than a subscription lifetime.
- **Assume the client will be compromised.** Design for what happens *after*,
  rather than betting it won't.
- **Revocation as a first-class mechanism.** With a return path you can
  de-authorise, detect anomalies, and force re-keying.
- **A migration path.** Version the crypto, plan the rotation, and make sure you
  can replace it before you need to.
- **Kerckhoffs's principle.** Publish the design; keep only the key secret. This
  is what makes public analysis possible, and public analysis is how you learn
  you are broken while it is still cheap to fix.
- **Hardware root of trust as a cost, not a fix.** A secure element or TEE
  raises the attacker's cost. It does not close the hole. Treat it as one layer.

## 7. Design checklist

Each historical failure, with the countermeasure to adopt up front.

| # | Do not | Do instead |
|---|---|---|
| 1 | Invent a cipher | AES-GCM or ChaCha20-Poly1305 |
| 2 | Rely on algorithm secrecy | Publish the design and the protocol |
| 3 | Put a long-lived secret in customer hardware as the only defence | Per-session keys; short-lived entitlements |
| 4 | Rotate keys slowly because hardware is slow | Rotate as fast as the link allows; measure it |
| 5 | Leave entitlement messages unauthenticated | Authenticate everything, including metadata |
| 6 | Ship crypto you cannot update | Version and sign the crypto; plan rotation |
| 7 | Treat revocation as a future problem | Define it before the first shipment |
| 8 | Assume the client is honest | Assume it is compromised; limit the blast radius |
| 9 | Design for a 15-year deployed life | Design for replacement |
| 10 | Spend the security budget on the cipher | Spend it on key management and protocol |

## 8. What this means for OrcXM

The architecture decision dominates everything else. Cipher choice is almost
irrelevant by comparison.

**Option A — one-way broadcast only (satellite downlink, no return path).**

You inherit the full historical problem set: static secrets in customer
hardware, no effective revocation, cloned receivers indistinguishable from real
ones. Your only levers are short key rotation (bounded damage per leak) and
accepting that compromise is permanent. This is the weakest option and it is
chosen by the physics, not by preference.

**Option B — satellite downlink plus any return path, even occasional.**

An SMS message, a Wi-Fi sync, a monthly network check-in. Once a return path
exists, revocation and per-session keys become possible, and the cipher stops
being the interesting part. This is the single highest-value architectural
change available.

**Option C — two-way delivery.**

A standard modern problem with well-trodden solutions. Note that this is exactly
what the industry concluded: content over a bidirectional link, DRM on top.

**A concrete recommendation for a hobbyist link:** do not build a CAS at all
until there is something worth protecting. If OrcXM ever carries traffic that
needs access control, use Option B if any return path can be arranged, keep the
crypto to AES-GCM with a per-session key, and spend the effort on the waveform
and the link budget instead. A hobbyist satellite link's hard problems are the
modulation, the FEC and the link margin — conditional access is the part you can
get right in an afternoon, and the part most likely to be wasted effort if the
link never closes.

## 9. Where the real engineering is

Worth stating plainly, because it reorders priorities:

- **Waveform and spectral mask** — the six-carrier tiling arithmetic is in the
  [research dump](siriusxm-research-2026-10-17.md) §4.
- **FEC** — published standards (DVB-S2 LDPC+BCH, CCSDS) beat anything
  reverse-engineered, and are free to use.
- **Link budget** — the number that decides whether any of it is possible.
- **Framing and sync** — CCSDS ASM `0x1ACFFC1D` is a public standard marker and
  entirely appropriate for a system you design deliberately.
- **Conditional access** — last, and smallest.

## 10. Sources

Standards and primary references for the claims above:

- **ETSI TS 103 197** — DVB SimulCrypt head-end implementation. The
  multi-vendor key-sharing architecture.
- **DVB Common Scrambling Algorithm (DVB-CSA, and later CSA3)** — the era's
  content scrambler, subsequently reverse-engineered and published, which is
  itself the case study in why secrecy is not strength.
- **NIST SP 800-38D** — Galois/Counter Mode (AES-GCM).
- **RFC 8439** — ChaCha20 and Poly1305 for IETF protocols.
- **ETSI EN 302 307** — DVB-S2, for LDPC + BCH FEC parameters.
- **CCSDS 131.0-B** — TM Synchronization and Channel Coding, including the
  attached sync marker.

### Caveats

- Vendor-specific compromise histories are described here only at the level of
  *failure class*. Specific attack techniques are deliberately omitted; the
  design lessons do not require them, and this document is not a route to any
  deployed system.
- No claim here is about SiriusXM's implementation. The survey document covers
  that system's architecture; this one is about the general problem and about
  what OrcXM should build if it ever needs access control.
- Standards citations are by document number and subject; verify current
  revisions before designing against them.
