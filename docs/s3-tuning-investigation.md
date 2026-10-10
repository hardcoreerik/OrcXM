# S3 RF Tuning — REA-Directed Investigation

**Date:** 2026-10-10
**Objective:** Understand how the ESP32-S3 programs its RF PLL, to assess
out-of-band tuning to 2.33 GHz (XM band). Supports OrcXM Track 3
(ESP32-native path) and the Phase 0 go/no-go.

## Method and tools — read this first

- **REA** (`morluto/rea`) was installed and evaluated: `rea@6.3.0` CLI,
  `rea doctor` run. Verdict: **all native analysis providers missing.**
  - Hopper: assessed as no help for S3 — it disassembles x86/ARM only,
    not Xtensa. The `rea setup --install-hopper` path cannot analyze
    S3 binaries.
  - Ghidra: supports Xtensa and is REA's viable provider here, but
    needs JDK 17+ plus a Ghidra 12.1.x download — neither installed.
    Flagged below as the deeper-work path (needs approval for the
    installs).
  - pwntools provider: needs specific Python packages, and Unicorn
    doesn't emulate Xtensa anyway.
- The static analysis below was therefore performed with the
  **xtensa-elf toolchain from Erik's own PlatformIO install**
  (`objdump`/`nm`/`ar`) — the same class of static binary analysis,
  run evidence-first in REA's style.
- **Target:** `libphy.a` (ESP32-S3) from
  `framework-arduinoespressif32` — Espressif's binary-only RF PHY
  library.
- **Clean-room note:** No ESP-SDR (GPL-3.0) code was examined or copied.
  This is independent analysis of the silicon vendor's binary for
  interoperability — the mechanism, not anyone's code.

## Finding 1: the tuning call chain

```
phy_change_channel
  → chip_v7_set_chan
    → set_channel_rfpll_freq
      → rfpll_set_freq
        → write_rfpll_sdm        (programs the PLL hardware)
```

Supporting cast: `get_pll_ref_code`, `rfpll_cap_init_cal`,
`wait_rfpll_cal_end`, `rfpll_cap_track`, `rfpll_cap_correct`
(PLL capacitor calibration), `set_rf_freq_offset`,
`correct_rfpll_offset`, `phy_freq_correct`.

(`phy_change_channel` itself is a thin wrapper — one indirect call.
The real work starts in `chip_v7_set_chan`.)

## Finding 2: the mechanism is fractional-N via SDM

- `write_rfpll_sdm` writes 6+ sigma-delta-modulator bytes to the RF PLL
  over PBUS/I2C, one byte per call through a register-write helper.
- `rfpll_set_freq` computes the integer and fractional divider values
  with fixed-point multiply/divide sequences (`mull`, `quos`, shifts) —
  i.e. **the frequency is computed as PLL divider values, not looked
  up from a channel table.**
- Consequence: on the direct-programming path, the achievable range is
  set by the VCO and divider hardware — not by a software channel
  list. There is no channel table to defeat.

## Finding 3: two paths — channel API vs direct programming

- `chip_v7_set_chan` takes an **8-bit Wi-Fi channel number** (masked
  with `extui`, with a channel-14 special case visible in the
  disassembly). This is the constrained, Wi-Fi-shaped path.
- ESP-SDR bypasses it entirely: calibrate on a standard channel, then
  program the PLL directly (their documented method; the library
  exports `set_rf_freq_offset` for exactly this kind of use).
- Out-of-band tuning is possible **because** the direct path exists —
  the firmware never has to pretend 2333 MHz is a Wi-Fi channel.

## Finding 4: what this means for 2.33 GHz

- The only question the hardware must answer is whether the PLL/VCO
  locks at the divider values for 2333 MHz — 67 MHz below the band
  edge. No software table stands in the way.
- This mechanism finding converges with the empirical reports
  (see `docs/phase0-test-plan.md` background): S31/C61 verified
  220–250 MHz below band via direct PLL, 5/6 LO mode to 1.84 GHz,
  2.63 GHz above band. A fractional-N PLL doing 220+ MHz excursions
  on sibling silicon makes 67 MHz on the S3 plausible — which is
  exactly what Phase 0 will confirm or kill.

## Open questions (need Ghidra or hardware)

1. Exact VCO tuning range and divider limits — requires deeper
   disassembly of `rfpll_set_freq`'s fixed-point computation and the
   SDM value format.
2. The calibration algorithm — what `rfpll_cap_init_cal` actually
   measures, and why the achievable range "depends on the individual
   chip" (per ESP-SDR docs).
3. 5/6 LO mode mechanics — h0m3us3r's eSpDR documented this; not
   re-derived here.

## Relevance to the XM decoder

- This investigation supports **Track 3** (S3 native handheld): it
  maps the exact software path a clean-room capture driver would use
  to tune out of band, and confirms there's no software barrier —
  only the PLL lock question Phase 0 answers empirically.
- The **frame-sync RE** (Track 2 core) is untouched by this: it needs
  real captures first. No signal, nothing to reverse.
- Recommended next: Phase 0 hardware test (unchanged), then — if
  GREEN — Ghidra-backed analysis of `rfpll_set_freq`/`write_rfpll_sdm`
  to nail the exact programming for the clean-room driver.
