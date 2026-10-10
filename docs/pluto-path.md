# OrcXM — Pluto SDR Path

Added 2026-10-09: Erik has a Pluto SDR clone on the bench. This changes the
front-end plan — the Pluto replaces both the downconverter and the RTL-SDR
as the lab receiver. (Typical clone specs below are AD9363-class; verify
against the actual unit: `iio_info` will report the chip.)

## Why the Pluto changes everything

- **Direct tuning**: 325 MHz–3.8 GHz covers 2332.5–2345 MHz natively. No
  downconverter, no IF planning, no image-reject filter math.
- **Whole band at once**: up to 20 MHz bandwidth swallows the entire
  12.5 MHz XM band — all six carriers in a single capture, instead of one
  carrier per RTL-SDR grab.
- **Better samples**: 12-bit ADC vs the dongle's 8-bit (~40 dB usable) —
  more dynamic range for the weak satellite carriers next to strong
  terrestrial repeaters.
- **TX included**: the Pluto transmits too, which enables the cabled
  RF loopback test (Stage 1) with no extra hardware.
- **Cleaner clock**: no ±50–100 ppm R820T2 crystal drift to fight.

What the Pluto does NOT replace: the **2.3 GHz antenna + LNA** (its S-band
noise figure still wants help — SPF5189Z at the antenna, as before), the
**DSP chain** (QPSK recovery → frame sync → demux, unchanged), or the
**frame-sync RE work** (still the core research task).

## Division of labor

- **Pluto = lab reference receiver.** Wideband captures, loopback tests,
  ground truth for validating everything else.
- **RTL-SDR + downconverter = fallback path.** Only if the Pluto is
  busy/broken. The downconverter BOM stays in the docs for this reason.
- **ESP32-S3 native path = the product vision.** Handheld, no PC.
  The Pluto's captures become the reference the S3 implementation is
  checked against.

## Bring-up plan (Pluto)

- **Stage 0 ($0, software only)**: synthesize the R&S-spec waveform
  (1.64 Msym/s QPSK, RRC 0.15, PN9 payload) and validate the modem chain
  — matched filter → Gardner timing → Costas loop — with zero hardware.
- **Stage 1 (cabled loopback)**: Pluto TX → attenuators → Pluto RX at
  2.33 GHz. Validates the real RF chain (filters, gain staging, DC
  offset/IQ imbalance correction) without radiating in a licensed band.
- **Stage 2 (first light)**: antenna + LNA → Pluto, 15–20 MSPS capture
  centered ~2338.75 MHz. Look for the six carriers:
  2333.465 / 2335.305 / 2337.49 / 2340.02 / 2342.205 / 2344.045 MHz.
  Check the terrestrial repeaters first (2337.49 / 2340.02, vertical whip)
  — strongest signal, no pointing.
- **Stage 3**: symbol/carrier recovery on live captures (constellation,
  MER per carrier).
- **Stage 4**: frame-sync RE from long captures → demux → stream analysis.
  Stops hard at the encrypted payload (see boundary in README).

## Software notes

- GNU Radio: `gr-iio` PlutoSDR source/sink blocks. If Radioconda on
  Windows lacks gr-iio, fallback is libiio-based capture to file, then
  offline DSP.
- Pluto appears as a USB network/IIO device; confirm with `iio_info`
  before first use. Clone USB stability varies — short, good-quality
  cable, preferably direct to the PC.
- AD9363 DC offset and IQ imbalance: enable the one-time calibrations;
  verify with a quiet-spectrum capture before trusting weak carriers.
