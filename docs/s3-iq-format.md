# S3 hardware IQ format (reverse-engineered)

Source: ESP32-S3 `libphy.a`, `phy_debug.o` — disassembled 2026-10-11.
Functions: `get_iq_value()` and `get_dc_value()`.

## Raw IQ register (16-bit)

The S3's radio exposes raw IQ samples through a 16-bit register.
`get_iq_value(raw16, mode, out)` unpacks it into two signed bytes:

| Bits   | Field | Width   | Range       |
|--------|-------|---------|-------------|
| [0:5]  | Q     | 6-bit   | -32 to +31  |
| [6:11] | I     | 5-bit   | -16 to +15  | (mode = 0)
| [6:12] | I     | 6-bit   | -32 to +31  | (mode ≠ 0)

Sign extension: values above half-scale wrap (e.g., 6-bit value 33 → -31).

## DC offset register (32-bit)

`get_dc_value(raw32, out)` splits into two signed 16-bit values:

| Bits    | Field |
|---------|-------|
| [16:31] | I DC offset |
| [0:15]  | Q DC offset |

## Implications for the decoder

- S3 IQ is **low resolution** (5-6 bits). Don't expect clean constellations.
- The spectrum is **mirrored** (confirmed by Grok's bench tests).
- DC offset should be estimated and removed before demodulation.
- `tools/orc_decoder/s3_iq.py` implements the unpacking.

## Clean-room note

This documents the *data format* of hardware registers, not Espressif's
source code. No GPL code was examined. Format documentation for
interoperability.
