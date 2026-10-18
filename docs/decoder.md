# OrcXM Decoder (v0.2) — software side

**Status:** real QPSK demodulator plus frame sync, validated against an
adversarial channel model. Nothing here has yet seen an over-the-air SDARS
signal; see "What is *not* proven" below before reading any number as a
result about SiriusXM.

## Layout

`tools/orc_decoder/`:
- `rrc.py` — root-raised-cosine taps. Single source of truth for the
  matched pair, so a transmitter and a receiver cannot disagree about `alpha`.
- `interp.py` — cubic (Catmull-Rom) fractional-delay interpolation, used by
  the timing loop.
- `channel.py` — adversarial channel: sample-rate offset, carrier offset,
  carrier phase, fractional symbol-timing offset, AWGN. `apply()` returns
  `(impaired, truth)`. This is what makes the demodulator test non-tautological.
- `demod.py` — matched filter, coarse carrier estimate, acquisition timing,
  Gardner timing loop, decision-directed Costas loop, `qpsk_demod`.
- `frame_sync.py` — sync-word correlator (`find_sync`, `sync_word` is required),
  false-alarm arithmetic, lock-quadrant search, frame period estimation,
  frame extraction, counter-continuity verification.
- `pipeline.py` — decode pipeline: IQ → demodulator → bits → frames.
- `selftest.py` — the gate. **Exit code 0 means every check passed.**

## Running the gate

```
python tools/orc_decoder/selftest.py
```

There is no "close enough": a failing gate is a real failure. The tests exist
because this code was previously validated only against a loop-cable carrier
where carrier offset, symbol timing and sample clock were all exactly zero by
construction — a condition that cannot occur on a received signal.

## Measured performance envelope

Steady state, first 2000 bits excluded, 4 samples/symbol:

| Impairment | EVM | BER |
|---|---|---|
| clean | 6.14% | 0 |
| CFO ±60 kHz | 6.7% | 0 |
| CFO +150 kHz | 13.3% | 0 |
| symbol timing off 0.40 / 0.75 | 6.2% | 0 |
| clock ±20 / −25 ppm | 6.2% / 11.3% | 0 |
| SNR 20 / 12 / 8 / 6 dB (Es/N0 +6 dB) | 8.0 / 14.2 / 21.1 / 25.9% | 0 / 0 / 0 / 6.8e-5 |
| 60 kHz + 0.4 sym + 20 ppm + 10 dB | 17.7% | 0 |

Matched-filter EVM floor is **4.10%**, set by truncating the RRC to 10 symbols;
it is not zero and should not be read as an impairment.

Coarse carrier estimation is accurate to **< 2.3 Hz** up to ±150 kHz, and the
timing loop's fitted drift reads back the injected sample-rate offset to
0.1 ppm, so both are usable as bench measurements rather than only as loop
state.

## Two designs that were rejected

Recorded because both look correct and both fail quietly.

**Hard slicer every 4th sample.** With an integer samples-per-symbol and a
loop-cable transmitter this gives BER 0, so it appears to work. It has no
carrier recovery and no timing recovery: it survives only while the sample
clock and the carrier are locked to the transmitter, which is the definition of
a test that cannot fail.

**Un-normalised fourth-moment lock score.** The natural discriminator for a
QPSK lock is `-Re(mean(z^4))/mean(|z|^2)^2`. Two interpolation artefacts at the
edge of the record, reaching `|z|` about ten times the mean, were enough to
drive this to **−0.81 on a perfectly good lock** (EVM 11.25%, BER 0) and to
trigger a destructive 45° de-rotation. The per-symbol-normalised form
`-Re(mean((z/|z|)^4))` is scale-invariant and separates cleanly: ≈ +0.98 for a
true lock down to +0.74 at 6 dB SNR, and ≈ +0.00 for noise.

## Two loop signs are empirical, not derived

Both are pinned with comments in `demod.py`; do not "fix" them without
re-measuring.

- `_TED_SIGN = -1.0` — the Gardner detector returns *positive* for late
  sampling on this pipeline.
- `_PED_SIGN = +1.0` — the decision-directed Costas error
  `sign(I)·Q − sign(Q)·I` is *positive* for a positive phase error.

The Gardner S-curve zero crossing sits exactly on the ISI-free instant with a
slope of 0.43 per symbol, which is what the selftest checks.

## The four lock quadrants

A decision-directed QPSK Costas loop has **four stable equilibria, 90° apart**,
and an unstable one at 45°. Two consequences shaped the code:

1. **At 45° the detector reads exactly zero** and a noiseless signal can rest
   there. The four constellation points then land on the axes, so a quarter of
   the bits slice as noise while EVM still looks healthy. `qpsk_demod` handles
   this with a second hypothesis and a signed lock score rather than by trying
   to invent a better detector.
2. **Which of the four stable quadrants the loop picks is arbitrary**, so every
   consumer of the bits must search the rotation group `{id, R90, R180, R270}`.
   Rotating the constellation by 90° maps the bit pair `(I,Q) → (¬Q, I)`.

   Searching `(swap, invert)` does *not* cover this. Those give
   `{id, (Q,I), (¬I,¬Q), (¬Q,¬I)}` while the quadrants are
   `{id, (¬Q,I), (¬I,¬Q), (Q,¬I)}` — the two sets agree on only two of four.
   A loop that settles a quarter turn away therefore scores exactly **0.25 BER**
   (one of the two bits wrong on every symbol) and finds **zero** markers. Both
   look like a dead receiver. `frame_sync.rotate_bits` takes `quarter_turns`
   for the rotation and a separate `swap` flag for a cross-connected I/Q, which
   are genuinely different errors.

## Test carrier framing

`tools/gen_xm_test_carrier.py --framed` embeds:
- 32-bit sync word `0x1ACFFC1D` (see the warning below)
- 16-bit frame counter (wraps at 65536)
- Configurable payload (`--frame-payload`, default 1024 bits)

Frame length = 1072 bits default. The counter gives frame-sync verification a
ground truth: drops = lost frames.

**`0x1ACFFC1D` is the CCSDS attached sync marker, and SDARS does not use it.**
It is the marker this repo's own generator plants, so a marker search for it
can only ever confirm that the generator and the search agree. It is named
`TEST_SYNC_WORD`, it is deliberately not a default anywhere, and no result
obtained with it says anything about a real SiriusXM frame.

## False alarms

A marker search that tolerates errors will match noise. At 1.64 Mbit/s a 32-bit
marker:

- tolerating 2 bit errors matches noise every **5 s**;
- tolerating 0 errors matches noise every **44 min**.

So the frame period is the only trustworthy check, and a marker length worth
trusting for a one-hour mean interval is **33 bits**. The selftest asserts this
behaviour in both directions, including that pure noise yields no frames.

## What is *not* proven

- No over-the-air SDARS energy has been demodulated. Every result above is
  against a synthetic channel, which is a necessary condition, not the claim.
- The real symbol rate, RRC roll-off, preamble and FEC remain as documented in
  [the research dump](siriusxm-research-2026-10-17.md); the loop parameters here
  are tuned for 1.64 Msym/s and RRC 0.15 because that is what the published
  patent table states for XM.
- The native handheld capture path cannot close framing regardless of effort:
  a 16380-sample burst at 16 MS/s is 1.02 ms = 1679 symbols = 0.24% of one
  432 ms master frame, and the bursts are incoherent, so no accumulation is
  possible. Frame timing needs a continuous capture.

## What's next

- A continuous wideband capture at 2338.755 MHz, then the 432 ms
  autocorrelation probe (see the research dump, §13).
- TDM structure research → `demux.py`
- Soft-bit support in `frame_sync.py` when LLRs are available

