# Presence metric v2 and the off-centre dial plan — 2026-10-17

Still presence only: no demodulation, no transport work, no cipher.
This note covers the detector and the tuning geometry, not the sky.

## Why the dials moved

The receiver's own spur sits on the dial at +4 to +7 dB over the floor,
and the carrier window throws away ±150 kHz around it. Where a carrier
lands depends on the inversion, so the offset that matters is
`|dial - center|`, and for three of the six carriers that was inside the
exclusion:

| Carrier | Center MHz | Old dial | Offset | In spur window | New dial | Offset |
|---|---|---|---|---|---|---|
| Sat1A | 2333.465 | 2333 | 0.465 | no | 2331 | 2.465 |
| Sat2A | 2335.305 | 2335 | 0.305 | no | 2332 | 3.305 |
| TerrA | 2337.490 | 2337 | 0.490 | no | 2334 | 3.490 |
| TerrB | 2340.020 | 2340 | 0.020 | **yes** | 2343 | 2.980 |
| Sat2B | 2342.205 | 2342 | 0.205 | **yes** | 2345 | 2.795 |
| Sat1B | 2344.045 | 2344 | 0.045 | **yes** | 2342 | 2.045 |

For those three the window median was taken over the carrier's skirts
only, so `excess` was the level of the shoulders rather than of the
plateau. The new dials come from `bench/xm_metrics.py:dial_plan()`,
which among the integer dials leaving a 2.0–3.5 MHz offset picks the one
with the most clean out-of-band floor to measure against. Every carrier
now sits at least 2.0 MHz off its dial, so the exclusion is never
touched. `bench/outdoor_capture.py --legacy-dials` reproduces the old
geometry for comparison.

## What the metric reports that it did not

The estimator itself is unchanged — a median of the carrier window over
a median of the symmetric `|baseband|` 4–7.5 MHz floor. Four fields are
new, and the rise gate now uses one of them:

- `gate` — `max(3 dB, tilt)`. `tilt` is how far the two halves of the
  floor disagree, so a capture with a 5 dB tilt cannot pass a 3 dB rise
  as evidence.
- `tilt` — that disagreement, measured, not modelled.
- `spur` — the spur peak above the floor, on the same 150 kHz-smoothed
  spectrum the carrier is scored on (so it reads +1.0 to +2.1 dB, not
  the +4 to +7 dB of the raw peak).
- `mask` — true when the carrier sits inside the spur exclusion. If a
  run ever prints this, the dial is wrong for that carrier.

## Two ideas that did not survive measurement

Recorded so they are not tried again:

- **Masking the neighbouring carriers out of the floor.** Dropped. The
  floor has 3586 bins and two overlapping neighbours occupy about a
  quarter of it, so the median was already robust: with one neighbour at
  +10 dB the error stayed within 1.3 dB, and with two it stayed within
  1.3 dB as well. Masking only removed one side of the floor and made
  TerrB worse by 0.8 dB.
- **Fitting a line to the one clean floor band and extrapolating across
  the dial.** Rejected. Only one of the two floor bands is ever outside
  the XM band, so the fit is one-sided; across the six archived captures
  it was off by −2.9 dB on three carriers and −27.3 dB on TerrB.

## What the metric does on known input

`bench/metric_selftest.py` adds a flat-topped plateau 1.89 MHz wide at
the position the inversion model predicts, into the archived spectra, and
scores it:

- recovery of an injected 3–12 dB plateau: mean +0.89 dB, rms 0.92 dB,
  worst 1.31 dB — the same as the 2026-10-10 metric, as expected, since
  the estimator did not change;
- on the un-injected spectra the largest reading is 1.31 dB, i.e. the
  gate is not tripped by noise alone.

## Re-score of the archived captures

`bench/rescore_phase0.py` re-runs the metric on the 2026-10-10 spectra and
writes `bench/phase0-2026-10-10/metrics-v2.json`. `published` is the
`snr_db` from `summary.json`, which came from the capture script's own
metric, so the two columns are not the same estimator:

| Capture | Carrier | published | v2 excess | gate | tilt | spur | mask |
|---|---|---|---|---|---|---|---|
| sat2333 | Sat1A | +0.37 | +1.03 | 3.0 | 1.09 | 1.50 | no |
| sat2333-g82 | Sat1A | +0.28 | +1.11 | 3.0 | 1.56 | 1.80 | no |
| sat2335 | Sat2A | +0.05 | +0.70 | 3.0 | 1.19 | 1.27 | no |
| terr2337 | TerrA | +0.37 | +1.01 | 3.0 | 1.16 | 1.46 | no |
| terr2337-g82 | TerrA | +0.10 | +0.42 | 3.0 | 1.05 | 1.00 | no |
| terr2340 | TerrB | +0.34 | +1.31 | 3.0 | 1.52 | 2.12 | **yes** |
| sat2342 | Sat2B | +0.14 | +0.57 | 3.0 | 0.78 | 1.63 | **yes** |
| sat2344 | Sat1B | +0.27 | +0.81 | 3.0 | 0.82 | 1.34 | **yes** |

**The verdict does not change: no carrier-shaped rise at any of the six
centers, with every reading far below even the 3 dB gate.** What changes
is that three of the eight readings are now flagged as having lost their
middle bins, and the two halves of the floor are shown to disagree by
0.8–1.6 dB, which is the size of the systematic the old table hid.

The inversion itself was also re-checked against the archive before this
work: scoring the six spectra at the published center and at the mirrored
position gives the same answer on both sides (Sat1A +0.35 vs +0.30 dB,
TerrB +0.35 vs +0.35 dB, and so on for all six), so the mirror is not
what makes the band look empty.

## Limits

- Presence only. A plateau-shaped rise is not audio, not a frame, and
  not proof of a lock.
- The metric cannot separate "no carrier" from "the PLL did not lock at
  this dial". Nothing in the firmware reports lock. A conducted tone at
  each of the new dials is still the test that settles it.
- The Wi-Fi sanity rows still test 2412 and 2437 on their own dials,
  where the mirror has no effect, so they prove the chain is live but
  say nothing about the axis.
