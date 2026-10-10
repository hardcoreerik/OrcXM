# Sending our own XM test carrier

**Purpose:** a known, controllable XM-like signal for validating the
receive chain — S3 capture, Pluto reference, demodulator development.
Known bits in means we can score every stage objectively.

**Rule:** conducted only. Cable (with attenuator) from Pluto TX into the
receiver. Do NOT radiate at 2.33 GHz — it's licensed S-band.

## The transmitter: Pluto TX1

The clone's AD9361 transmits as well as receives (70 MHz–6 GHz).
Grok's bench already proved the path: CW tone at 2333 MHz seen by the
S3 at +28 dB, and lab QPSK resolved at the right width.

## Generate the baseband

`tools/gen_xm_test_carrier.py` (numpy only, runs anywhere):

```
python gen_xm_test_carrier.py -o xm_test.iq -d 1.0
```

Defaults produce the satellite waveform: random QPSK, 1.64 Msym/s,
RRC roll-off 0.15, 4 samples/symbol → 6.56 Msps complex64, RMS 0.18.
`--seed` makes the bits reproducible; `--sps 2` gives 3.28 Msps if you
want a lighter file.

## Transmit

**GNU Radio** (Radioconda on the Windows bench): File Source
(complex64, 6.56 Msps) → PlutoSDR Sink, LO 2333 MHz (or any XM center:
2333.465 / 2335.305 / 2342.205 / 2344.045). Start with TX attenuation
high (−50 dB hardware gain worked on the bench) and come down until
the receiver sees it clean.

**Note the S3 mirror:** the S3's spectrum is inverted (see
`docs/bench-report-2026-10-10.md`). A carrier sent at 2333 MHz shows
up mirrored around the S3's tune frequency — read it that way or
pre-mirror the baseband (conjugate the IQ) before transmitting.

## What's next

Once the receiver reliably sees the lab carrier, the same generator
can carry a known sync word / frame structure — giving frame-sync
development a ground truth to lock against before touching real
satellite captures.
