# Phase 0 session — 2026-10-10

Spectrum presence only. No demodulation, no frame sync, no payload work.
The kill criterion in `phase0-test-plan.md` was **not** met, because no
external antenna and no powered LNA were in the chain.

## What was on the bench

COM36 is a WCH CH343 UART (`USB\VID_1A86&PID_55D3\5B5E123426`), not the
ESP32-S3 native USB Serial/JTAG. `esptool` identified:

- ESP32-S3 (QFN56), revision v0.2, 40 MHz crystal
- 16 MB flash, 8 MB embedded PSRAM (AP_3v3)
- MAC `ac:a7:04:2c:5f:04`

Before this session the app was a factory image that printed `RGB Demo`
at 115200 baud and failed its own SHA-256 check. That image was replaced
with the ESPARGOS ESP-SDR `esp32s3` build from
`https://espargos.net/espsdr/app/firmware/manifest.json`, git
`e74f2a470972ec163c247f1fe88d32e08579242a`, build 2026-10-08T12:20:54Z.
Part hashes matched the manifest before flashing. `esptool` verified the
write.

Native USB did not enumerate on this connector. COM13 and COM17
(`VID_303A&PID_1001`) were already present before the flash and were not
touched. ESP-SDR's on-chip `SPEC` stream advertises `transports: ["USB"]`
only, so this session used CRC-checked `CAP16` snapshots on the UART and
FFTs on the host.

## Corrections to the written test plan

Verified against this firmware, not assumed:

- `FREQ` accepts integer MHz only. `FREQ 2333.465` returns `ERR command`.
  `RANGE?` is `RANGE 100 6000 1`. The six published centers were observed
  through the nearest integer tune. At 16 MS/s a 0.5 MHz offset still
  leaves a 1.84 MHz carrier inside the window.
- `BANDWIDTH` minimum is 13 MHz (`LIMITS?`: `[13,69,1,0]`). The plan's
  `BANDWIDTH 4` and `BANDWIDTH 2` are below the firmware limit. 0 means
  widest, not bypass.
- UART protocol baud is 2,000,000 (`TRANSPORT UART 2000000`). Capture
  rate index 6 is 16 MS/s. `INFO` reports `S3SDR 6 burst 16380`.
- `GAIN?` in hardware-AGC mode answered `GAIN HARDWARE -1 0 82 0` at
  every tune. It does not report the live AGC index, so AGC runs cannot
  be compared by RMS. Manual index 82 clips (28% of samples at |x|≥120
  on 2437 MHz). Index 70 was the highest gain that stayed near linear
  (clip fraction under 2% on Wi-Fi, zero on the XM tunes).

## Measurement

`CAP16 8192 6`, CRC32 checked on every payload (zlib CRC32 matched the
header). DC removed per capture. Fixed `GAIN MANUAL 70`, `BANDWIDTH 20`,
six captures averaged per tune. Power is uncalibrated ADC counts, not dBm.

RMS of the capture (median of the six), same gain:

| Tune (MHz) | What it is | RMS (counts) |
|---|---|---|
| 2324 | below the XM band | 31.3 |
| 2333 | Sat1A grid | 28.0 (2334) |
| 2338 | mid-band | 25.4 |
| 2344 | Sat1B grid | 24.7 |
| 2350 | above the band | 26.8 |
| 2412 | Wi-Fi channel 1 | 45.1 |
| 2437 | Wi-Fi channel 6 | 41.3 |
| 2462 | Wi-Fi channel 11 | 26.9 |

From 2324 to 2360 MHz in 2 MHz steps the RMS is a smooth slope, minimum
near 2344 MHz. No step on a carrier center.

Carrier-region SNR (mean power within ±0.92 MHz of the published center,
versus bins 3.2–6.2 MHz from the integer tune), hardware AGC, 12 captures:
about 0 dB on all six (Sat1A +0.37, Sat2A +0.05, TerrA +0.37, TerrB +0.34,
Sat2B +0.14, Sat1B +0.27). A 10 dB carrier would have shown up. The same
null holds at manual gain 82, which is clipped and only useful as a check
that more gain does not reveal a shape.

One real in-band feature: with the tune at 2437 MHz, mean and max-hold
both show a narrow bursty rise near +5 MHz (about 2442 MHz), roughly
10 dB in the mean and much taller in max-hold. It is absent when tuned
to 2412 or 2338, so it is not a fixed baseband spur. It is also not a
20 MHz Wi-Fi plateau. 2412 MHz is louder in total power and spectrally
flat, which fits energy that fills the 16 MHz window. 2462 MHz matches
the 2.33 GHz floor.

A tilt appears when tuned to 2350–2360 MHz (low side hotter by about
5 dB at 2350, sign flips by 2360). It is not 1.8 MHz wide and it does
not sit on a published center. 2348 MHz max-hold also showed a comb of
narrow lines. Neither is an XM carrier shape. Cause unknown.

Plots and `summary.json` are in `bench/phase0-2026-10-10/`.

## Report block

```
Phase 0 report — 2026-10-10
Board: ESP32-S3 rev v0.2, 16 MB flash, 8 MB PSRAM, MAC ac:a7:04:2c:5f:04, on COM36 (CH343 UART)
Antenna: none external identified (module antenna, if the board has one)
LNA: none
Location: indoor bench, city not recorded
ESP-SDR version: e74f2a4, profile esp32s3, build 2026-10-08, protocol 6

Step 0 (2437 MHz sanity): WEAK PASS
  Same manual gain: 2412 = 45 counts, 2437 = 41 counts with a burst near 2442 MHz,
  2462 = 27 counts. Path, tune, and capture work. Not a textbook Wi-Fi plateau.
Step 1 repeaters (2337.49 / 2340.02): N, carrier-region SNR ~0 dB, no flat plateau
Step 2 satellites:
  2333.465: N
  2335.305: N
  2342.205: N
  2344.045: N
Tune-away checks performed: Y (2324–2360 MHz sweep plus 2462 MHz)
Verdict: INCONCLUSIVE — do not kill the S3 path
Notes: no antenna, no LNA, so the kill criterion was not tested.
  FREQ is 1 MHz steps. SPEC needs native USB, which this connector does not expose.
  Previous firmware was an RGB demo and was overwritten.
```

## What would actually answer Phase 0

Repeat the fixed-gain sweep (`GAIN MANUAL 60` or `70`, `CAP16` at 16 MS/s)
with a 2.3 GHz antenna and a powered LNA at the antenna. Vertical whip
first, on 2337 and 2340. LHCP (or a linear patch) aimed at 85°W or 115°W
for the satellite centers. A carrier is a ~1.8 MHz bump that disappears
when the tune moves 10 MHz and comes back when it returns, at least
~10 dB above the surrounding bins. Until that hardware is on the cable,
a flat 2.33 GHz spectrum is not a kill.
