# OrcXM

Homebrew XM satellite receiver — RF and DSP, everything up to the cipher.

## What this is

OrcXM is a project to build a homebrew XM satellite radio receiver covering the full receive chain: S-band front end at ~2.33 GHz, QPSK carrier capture, symbol recovery, frame sync, transport demux, and stream analysis. No PC required in the endgame — the wild-card track aims at an ESP32-S3 doing it all natively.

## The boundary

The audio payload is encrypted with per-device keys provisioned over the air by SiriusXM. Defeating that encryption is circumvention of a paid service and is **permanently out of scope**. This project stops at transport demux and stream analysis of everything *around* the cipher.

## The signal

- 2332.5–2345 MHz; six carriers: 2333.465 / 2335.305 / 2337.49 / 2340.02 / 2342.205 / 2344.045 MHz
- 1.64 Msym/s QPSK, root-raised-cosine 0.15, ~1.89 MHz occupied per carrier
- Satellites: QPSK, LHCP, geostationary at 85°W/115°W (zero Doppler); terrestrial repeaters: COFDM, vertical
- TDM frame structure and FEC are **not public** — recovering them is the RE core of this project
- Link budget: ~40+ dB SNR from a small patch/helix + LNA vs ~10 dB needed. No dish.

## Docs

- `docs/phase1-frontend-bom.md` — Phase 1 front-end BOM: exact carrier/IF plan, LNA and antenna options, phased test plan
- `docs/downconverter-dsp-report.md` — downconverter buy-vs-build spec, DSP chain scope, staged bring-up
- `docs/esp32-native-exploration.md` — ESP32-S3 native capture feasibility: no downconverter, no dongle, no FPGA
- `docs/pluto-path.md` — Pluto SDR as lab reference receiver: direct 2.33 GHz tuning, whole-band capture, revised bring-up plan (added 2026-10-09)
- `docs/phase0-test-plan.md` — Phase 0 bench procedure: S3 out-of-spec tuning test with go/no-go criteria
- `docs/phase0-setup-espsdr-method.md` — Phase 0 setup following the ESP-SDR team's documented method (flash, interrogate, tune, capture)
- `docs/s3-tuning-investigation.md` — REA-directed static analysis of the S3 RF PLL tuning path (libphy.a): fractional-N/SDM mechanism, call chain, out-of-band assessment
- `docs/sxm-player-analysis.md` — REA-directed analysis of a Linux SiriusXM player (sxm-player): IP API surface, tune flow, delivery pipeline; architecture only, encryption untouched
- `docs/sxm-player-ecosystem.md` — comparative survey of five open-source players: HLS/AAC pipelines, SXM in-stream metadata format, TS stream structure (PID 768/1024); formats only, no decryption
- `grok-prompt.md` — handoff prompt for briefing an AI assistant onto this project

## Status

- [x] Signal parameters pinned (R&S XM-Radio manual)
- [x] Pluto SDR clone on the bench (Zynq-7020 + AD9361: 70 MHz–6 GHz, ≤56 MHz BW) — covers 2.33 GHz directly, whole 12.5 MHz XM band in one capture; downconverter now fallback-only (RTL-SDR path)
- [x] DSP chain scoped (GNU Radio primitives; custom work = frame sync + demux)
- [x] ESP32-native path explored: feasible with conditions (Pluto captures become its reference)
- [ ] Phase 0: RF verification — S3 + antenna + LNA, look for carriers at 2333 MHz (kill criterion for the native path)
- [ ] Antenna + LNA build
- [ ] Stage 0 modem prototype (synthesized waveform, $0)

## Hardware

Pluto SDR clone (Zynq-7020 + AD9361: 70 MHz–6 GHz, ≤56 MHz BW, 12-bit, TX+RX) · RTL-SDR dongles (R820T2, ~1.75 GHz / 2.4 Msps, fallback path) · ESP32-S3 boards (LilyGO T-Display-S3, T-Embed CC1101, M5Stack Cardputer Advanced) · Windows bench (GNU Radio via Radioconda)
