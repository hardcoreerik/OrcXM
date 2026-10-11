# T-Display live scan — 2026-10-10

Spectrum presence only. These listens do not demodulate, and they do not
close Phase 0.

## What was measured

LilyGO T-Display-S3 on COM3, MAC `b4:3a:45:a1:a6:0c`, handheld image
(not the ESP-SDR text protocol). Gain 70, 20 MHz bandwidth, 12 snapshots,
1024-point FFT. The T-Shield microSD holds the reports at
`/sdcard/orcxm/sNNNN.txt`. The card is not a Windows drive. Serial `d`
prints them. COM36 was not reflashed.

The antenna on these listens was a 2.4 GHz SMA whip. The idle screen
shows "2.4 GHz SMA". No powered LNA was in the chain.

Each pass is a live dwell, not an IQ recording. The chip cannot store a
minute of samples. `s0001.txt` is the short bench pass (no `xm_dwell_s`
line). `s0002.txt` and `s0003.txt` dwell 10 seconds on each of the six
integer XM centers and 1.5 seconds on each Wi-Fi check. A line is RISE
only when the corrected window is at least 3 dB above the floor and
1.2–2.6 MHz wide. Wi-Fi "heard" means the loudest snapshot is at least
6 dB above that tune's median.

## Results

Excess is dB. Width was 0.00 MHz on every carrier. Every carrier verdict
was quiet.

| File | Dwell | Wi-Fi burst | 2333 | 2335 | 2337 | 2340 | 2342 | 2344 |
|---|---|---|---|---|---|---|---|---|
| s0001.txt | short | +12.1 dB | −0.91 | −1.09 | −1.29 | −1.45 | −0.74 | −1.55 |
| s0002.txt | 10 s | +5.1 dB | −0.26 | −0.67 | −0.68 | −1.14 | −1.33 | −1.60 |
| s0003.txt | 10 s | +14.8 dB | −0.40 | −0.31 | −0.68 | −1.37 | −1.30 | −1.95 |

Wi-Fi detail: s0001 heard 2412 MHz (median RMS 3.39, p95 13.67). s0002
stayed under the hear line (2412 p95 5.82 against median 3.24). s0003
heard 2437 MHz (median 3.34, p95 18.27). The noise floor steps up toward
2344 MHz on all three files. The carrier window does not.

There is no `s0004.txt`.

## Reading

The whip and the tuner were alive: s0001 and s0003 heard Wi-Fi. A 2.4 GHz
vertical whip is the antenna `docs/phase0-test-plan.md` Step 1 uses for
terrestrial repeaters, and that step does not require an LNA for a first
look. No ~1.8 MHz plateau showed at 2337 or 2340 MHz. Step 1 calls that
miss inconclusive until a powered LNA is tried once, because repeater
coverage is not everywhere.

The satellite kill test is still Step 2: a 2.3 GHz directional or LHCP
antenna, plus a powered LNA at the antenna. A linear 2.4 GHz whip with no
LNA is not that test. Phase 0 stays open.

The Ham It Up Plus (v2) was reviewed and not used on these listens. Its
four positions are passthrough, amp, upconvert, and amp+upconvert.
Upconvert stops at 65 MHz. Amp mode is the only path with gain at
2.33 GHz, about +7 dB on the datasheet plot, with no published noise
figure. On OrcSDR the same Amp button raised the meter from −22 dBFS
to −8 dBFS, a +14 dB rise. OrcSDR tunes only to 1766 MHz, so that rise
is the amp in the RTL's band, near the datasheet's +15 dB HF end. The
upconverter adds 125 MHz to signals below 65 MHz and does not bring
2337 MHz into OrcSDR. The LNA in the plan remains an SPF5189Z-class
stage at the antenna. At 2.2 GHz the Qorvo table lists 11.9 dB of gain
and 0.98 dB noise figure. The listing's 0.6 dB and ~20 dB figures are
the 900 MHz row.

## Handheld screens

The image on COM3 has two screens. A short press on either button
changes screen. A long press starts the screen in view. The data screen
keeps the last saved scan, and a long press there runs the one-minute
save. The waterfall runs one dial live, newest row at the top, low
frequency on the left, with the center spur drawn gray. Leaving the
waterfall and coming back advances the dial through 2337, 2340, 2333,
2335, 2342, 2344, and 2437 MHz. This image no longer speaks the ESP-SDR
text protocol. `bench/outdoor_capture.py` drives a board that is still
running ESP-SDR. COM36 was left on that firmware.
