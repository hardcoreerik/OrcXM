# Tune-range survey — 2026-10-10

ESP-SDR `e74f2a4` on the ESP32-S3 at COM36 (CH343, 2 Mbaud).
`GAIN MANUAL 70`, `BANDWIDTH 20`, `CAP16` at 16 MS/s.
369 tunes from 100 to 5988 MHz in 16 MHz steps, every one accepted.
`FREQ 100` and `FREQ 6000` also return captures. Plots are in
`bench/tune-range/`.

The command range and the useful range are different things.

## What the level does

RMS of one 2048-sample capture, same gain:

| Span (MHz) | Median RMS (counts) | What it looks like |
|---|---|---|
| 100–900 | 8.4 | Flat. One narrow spike at 420 (24 counts) |
| 900–1050 | 12, peak 48 | Strong narrow occupants near 948–1012 |
| 1050–1840 | 12–15 | Raised, with streaks that move across the window as the tune steps |
| 1842–2209 | 5.1 | Hole. Deepest near 2000–2100. This is the firmware's 5/6 LO mode |
| 2276–2644 | 19–36 | Continuous sensitive span. Peak 55 counts near 2388 |
| 2380–2520 | 36 | Loudest stretch, covers the 2.4 GHz ISM band |
| 2720–4800 | 7.4 | Back to a flat floor |
| 5200–6000 | 3.5 | Lowest floor. Commands still return IQ |

XM at 2332–2345 MHz sits on the shoulder of that sensitive span:
2340 MHz measured 27 counts, against 45 at 2436 and 5 inside the 5/6 hole.

## Reading it

The walls of the hole land on the firmware's 5/6 LO boundaries (1842 and
2209 MHz), so that dip is the divider mode, not the antenna. Direct-PLL
tuning on either side of the hole is louder. The hump from about 2.28 to
2.65 GHz, peaked on the ISM band, is the direct PLL plus this module's
2.4 GHz antenna.

Below about 900 MHz and above about 2.7 GHz the spectrum stops changing
with the tune. The capture there is a flat floor. Strong signals still
poke through between 0.9 and 1.8 GHz (the moving streaks in
`shape-1600-2900.png`). That is real RF, at worse sensitivity than 2.4 GHz.

Time waterfalls (`waterfall-2338.png`, `waterfall-2437.png`) are 36 gapped
snapshots, 256 µs each. 2437 MHz is a bright raised floor. 2338 MHz is the
same texture and quieter, with no standing stripe on the six XM centers.
An occasional full-width bright row is one loud snapshot, not a carrier.

## 905.875 MHz dwell

A LoRa channel was reported near 905.875 MHz. The sweep's loud patch in
this neighborhood was 948–1012 MHz, not 906. The 900 MHz survey row
(one 128 µs snapshot) had 905.875 only 0.9 dB over its own median.

A follow-up parked on `FREQ 906` (integer MHz only; 905.875 is 125 kHz
below that center) for 50 snapshots at gain 70 and 50 at gain 82.
See `bench/tune-range/lora-905.png`.

- Gain 70: RMS stuck at 7.1 counts. The channel was +0.5 dB over the floor.
- Gain 82: the floor rose to 28 counts, so the receiver is running. The
  mean spectrum is flat at 905.875. A thin line sits on 906.000 exactly,
  the tune center. One snapshot was loud across the whole window.

No 125 kHz-wide burst landed on 905.875 in that listen. LoRa is intermittent,
so this does not prove the channel is empty. It does separate it from the
948–1012 MHz energy in the sweep.

## Heltec V4 on COM24

That port is a Heltec V4 running Meshtastic 2.8.0, region US, LongFast.
With an empty channel name and frequency slot 0, the firmware hashes to
slot 20, center **906.875 MHz**, 250 kHz wide. 905.875 is 1 MHz low.

Two hop-limited-to-0 text packets (`s3-listen`) were sent while COM36
recorded. Tuned to 907 MHz at gain 45, the bright line in
`lora-tx-test.png` is the receiver's own center at 907.000 (loudest bin
906.996, +19 dB). It was present before either packet. Tuned to 906 MHz
at gain 70, that line moved to 906.000 and the 906.75–907.00 MHz channel
stayed at +1.6 dB (`lora-tx-test-906.png`). Total RMS did not rise when
the packets went out (about 10.0 counts before and after, no clipping).

The S3 did not show the Heltec's transmission in this geometry. A real
catch would be a stripe on 906.875 that appears only at the send marks
and is absent from 905.875.

## RTL-SDR Blog V4 cross-check

A second radio on this PC, RTL-SDR Blog V4 serial 00000001 (Rafael R828D),
looked at the same LoRa channel. OrcSDR's LoRa default is that same
906.875 MHz (`kLoraDefaultHz`). This dongle cannot tune to 2.33 GHz, so it
does not check the XM carriers.

The dongle is working. An FM sweep at tuner gain 19.7 dB clipped on
stations near 93.3, 96.1, 98.9, 99.1, and 102.3 MHz. The bin at 103.703 MHz
was about 13 dB over that hop's median, so 103.7 MHz is on the air. The S3
tune at 100 MHz did not show it.

At gain 40.2 dB, 850–1050 MHz, the strong lines were a clipped cluster
around 886.6–886.9 MHz (850 MHz cellular downlink) and a clip at 929.601 MHz
(929 MHz paging segment). The 904–910 MHz slice sat near −19 dB, and
906.988 MHz was −19.4 dB, level with its neighbors.

A 12 second peak-hold from 904–910 MHz at gain 49.6 dB, 7.8 kHz bins, stayed
flat. Sweep median −36.3 dB. Loudest bin −32.8 dB at 904.469 MHz. The
906.75–907.00 MHz channel's loudest bin was −33.6 dB, 2.6 dB over the
median. No strong line on 906.875 MHz.

CSVs are in `bench/rtl-verify/`. A line that sits exactly on 906.875 only
while OrcSDR is tuned there is that receiver's center spur. These
off-center sweeps do not show a carrier on the LongFast channel.

## Conducted Pluto tone at 2333 MHz

The Pluto TX SMA is on a cable. A CW at 2333.000 MHz, TX hardwaregain
−50 dB and digital scale 0.2, was held on while the S3 took long dwells.
One `CAP16` is at most 16380 samples, 1.02 ms at 16 MS/s. The dwell was
80 of those at gain 70, tune 2330, about 82 ms of RF collected over 20 s.
The Pluto's own receiver showed the tone at +59 dB for the whole dwell.
The transmitter was then muted back to −89.75 dB.

On an uncorrected frequency axis the S3 line is not at 2333. It is a
narrow peak, +28 dB after the average, at 2327.061 MHz. Retunes put that
same peak at 2335.060 when the dial was 2334, and at 2319.060 when the
dial was 2326. The labeled frequency moves by twice the dial step and
the other way, which is spectral inversion. Mirroring each peak around
its dial lands on 2332.940 MHz, 60 kHz below the Pluto's 2333.000.
RMS barely changes, because the tone is one bin wide.

Plot: `bench/pluto-beacon/s3-long-2333.png`.

## Conducted wide signal, 1.64 Msym/s

TX1 sent random QPSK at 1.64 Msym/s, RRC rolloff 0.15, centered at 2334 MHz.
TX hardwaregain −40 dB, digital RMS 0.18 of full scale. The Pluto receiver
measured a half-power width of 1.61 MHz. The transmitter was muted and the
sample rate restored to 30.72 MS/s afterward.

The S3 tune was 2330 MHz, gain 70, 60 frames of 16380 samples. On the raw
axis the energy is a hump from 2325.191 to 2326.989 MHz, 1.80 MHz wide,
about 4 dB above the muted average. That is the mirror of 2334 MHz. The
same width centered on 2334 MHz, the uncorrected side, was flat. A single
bin did not carry it. The S3 passed the occupied width of this lab signal.

Plot: `bench/pluto-beacon/s3-wide-2334.png`.
