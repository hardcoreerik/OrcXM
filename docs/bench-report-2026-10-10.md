# Bench report — 2026-10-10

What the radios on this bench actually did. Spectrum and lab waveforms
only. No frame sync, no transport demux, no cipher, no audio.

The detailed notes are `docs/phase0-session-2026-10-10.md` and
`docs/tune-range-2026-10-10.md`. Plots and captures are under `bench/`.

## Radios

| Radio | Where | What it can tune |
|---|---|---|
| ESP32-S3, ESP-SDR `e74f2a4`, profile `esp32s3` | COM36, CH343 UART, MAC `ac:a7:04:2c:5f:04` | Integer MHz, 100–6000. Useful sensitivity on this module antenna is about 2.28–2.65 GHz |
| RTL-SDR Blog V4, R828D, serial 00000001 | This PC | About 24 MHz–1.766 GHz. Cannot tune to 2.33 GHz |
| Pluto clone, FISH Ball Rev.A, Zynq-7020 + AD9361 | USB Ethernet `ip:192.168.2.1` | About 47 MHz–6 GHz. TX1 is the cabled port |

The S3 was flashed from the ESPARGOS ESP-SDR manifest after the part
hashes matched. The factory image on that module was an "RGB Demo" build
that failed its own SHA-256 check. Captures are CRC-checked `CAP16`
snapshots, not a continuous IQ stream. The longest legal snapshot is
16380 samples, 1.02 ms at 16 MS/s. A long dwell is many of those,
averaged. Opening the CH343 port with DTR or RTS asserted resets the
module.

`FREQ` is integer MHz only. `BANDWIDTH` is 13–69 MHz, and 0 means widest.
`GAIN HARDWARE` does not report the live AGC index, so comparisons used
a fixed manual gain.

## Phase 0 — is an XM carrier on the S3?

Not shown. Not a kill.

At gain 70 the S3 noise floor away from signals is about 8 counts of RMS.
Wi-Fi at 2404, 2436, and 2452 MHz was 39, 45, and 31 counts, so the
2.4 GHz path is alive. The six XM centers near 2.33 GHz were a smooth
slope, about 27 counts at 2340 MHz, with no 1.8 MHz bump. There was no
2.3 GHz antenna and no powered LNA. The kill criterion needs both, and
then still no carrier.

## What else the S3 heard

Commands were accepted from 100 through 6000 MHz, 369 of 369 tunes.
The spectrum does not follow the dial outside a limited span.

- 100–900 MHz was a flat floor, median RMS 8.4. One narrow spike at 420 MHz, about 18 dB above the rest of that window.
- 948, 980, 996, and 1012 MHz were loud across the whole 16 MHz window (RMS 28–48). 964 MHz, between them, was back at the floor.
- 1842–2209 MHz is the firmware's 5/6 LO mode and a sensitivity hole, median RMS 5.1. Do not use it for XM.
- The direct-PLL span that stays above the floor runs from about 2276 to 2644 MHz. XM sits in that window.
- 103.7 MHz was 0.3 dB under the median inside the 100 MHz capture. The RTL-SDR, on the same bench, showed that FM station about 13 dB over its local floor. The station is on the air. This S3 front end did not hear it.

A line that sits exactly on the tune center and moves when the dial moves
is the receiver's own spur, not an external signal.

## LoRa at 906.875 MHz

The S3 did not hear it.

OrcSDR's LongFast default, and the Heltec V4 on COM24 (US, slot 20), is
906.875 MHz, not 905.875. A dwell at 906 MHz was hiss. The bright line in
those plots is the center spur. Two hop-0 text sends from the Heltec did
not raise the S3 RMS and did not make a stripe on 906.875. The RTL-SDR
peak-hold of 904–910 MHz at maximum gain was also flat there: the
906.75–907.00 MHz slice was 2.6 dB over the median. The RTL did clip on
real energy near 886.7 MHz and at 929.601 MHz. The S3 tunes covering
those two frequencies were floor-level.

## Pluto TX1, on a cable

TX1 is the AD9361 `voltage0` output. TX2 was not driven. The transmitter
was muted back to −89.75 dB after each test, and the sample rate was put
back at 30.72 MS/s.

**Tone.** 2333.000 MHz CW, TX hardwaregain −50 dB, digital scale 0.2.
The Pluto receiver saw it at +59 dB for the whole dwell. A short S3
snapshot did not show it. An average of 80 maximum-length frames at
gain 70 did: a one-bin line at +28 dB.

The line is not at 2333 on the S3's raw axis. Tune 2330 put it at
2327.061 MHz, tune 2334 put it at 2335.060, and tune 2326 put it at
2319.060. The label moves by twice the dial step, the other way. That is
spectral inversion. Mirroring each peak around its dial lands on
2332.940 MHz, 60 kHz below the Pluto. Later S3 spectra at 2.33 GHz have
to be read that way. A carrier scored only on the published offset, with
no mirror, is scored on the wrong side.

**Width.** TX1 then sent random QPSK at 1.64 Msym/s, RRC rolloff 0.15,
centered at 2334 MHz. Hardwaregain −40 dB, digital RMS 0.18 of full
scale. The Pluto receiver measured a half-power width of 1.61 MHz. The
S3, tune 2330, gain 70, showed a hump from 2325.191 to 2326.989 MHz:
1.80 MHz wide, about 4 dB above the muted average. That is the mirror of
2334. The same width centered on 2334, the uncorrected side, was flat.

The cable path therefore passes both a tone at 2.33 GHz and the occupied
width of a lab carrier. This was not a satellite signal, and it was not
a packet.

## What is still open

- No XM carrier has been seen over the air, on the S3 or on the Pluto.
- The S3 still needs a 2.3 GHz antenna and a powered LNA before Phase 0 can pass or fail.
- The RTL-SDR cannot check 2.33 GHz unless a downconverter is in front of it.
- Frame sync and demux have not been started. The cipher stays out of scope.
