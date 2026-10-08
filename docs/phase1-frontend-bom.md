# XM Decoder — Phase 1 Front End: BOM + Frequency Plan

Drafted 2026-10-07. Boundary: RF/DSP only — antenna, LNA, downconverter, capture,
QPSK recovery, frame sync, demux, analysis. Audio decryption is off the table.

## Signal facts (verified)

Source: R&S SMxAMU XM-Radio operating manual, carrier table (Table 2-1).

| Ensemble | Source | Center freq | Polarization | Modulation |
|---|---|---|---|---|
| A | Sat 1 (XM-3, 85°W) | 2333.465 MHz | LHCP | QPSK, ~1.84 MHz wide |
| A | Sat 2 (XM-4, 115°W) | 2335.305 MHz | LHCP | QPSK, ~1.84 MHz wide |
| A | Terrestrial repeater | 2337.490 MHz | vertical | COFDM |
| B | Terrestrial repeater | 2340.020 MHz | vertical | COFDM |
| B | Sat 2 (XM-4, 115°W) | 2342.205 MHz | LHCP | QPSK, ~1.84 MHz wide |
| B | Sat 1 (XM-3, 85°W) | 2344.045 MHz | LHCP | QPSK, ~1.84 MHz wide |

Notes:
- Satellites are **LHCP, not RHCP**. A homebrew helix must be wound left-hand;
  most commercial 2.4 GHz FPV helices are RHCP (wrong hand). Linear antenna = 3 dB
  polarization loss, acceptable for first light.
- Each ensemble rides on BOTH satellites (diversity) — pick the stronger carrier.
- ~800 terrestrial repeater sites across 60 US markets (~20+/city). If in a major
  metro, 2337.49 / 2340.02 MHz vertical may be strong enough to skip dish pointing.

## Chain

antenna (2.33 GHz) → LNA (at antenna) → downconverter → RTL-SDR (2.4 Msps, one carrier at a time)

## Frequency plan

**Buy route** — Nooelec Ham It Down (LO = 1500 MHz, 1PPM TCXO):

| RF (MHz) | IF at dongle (MHz) |
|---|---|
| 2333.465 | 833.465 |
| 2335.305 | 835.305 |
| 2337.490 (terr) | 837.490 |
| 2340.020 (terr) | 840.020 |
| 2342.205 | 842.205 |
| 2344.045 | 844.045 |

Caveat: 833–844 MHz sits inside the LTE uplink band (824–849 MHz). Urban LTE noise
is possible; if so, switch to the build route's cleaner IF.

**Build route** — ADL5350 mixer + ADF4351 synth, LO = 2188.5 MHz:

| RF (MHz) | IF at dongle (MHz) |
|---|---|
| 2333.465 | 144.965 |
| 2335.305 | 146.805 |
| 2337.490 (terr) | 148.990 |
| 2340.020 (terr) | 151.520 |
| 2342.205 | 153.705 |
| 2344.045 | 155.545 |

Quiet VHF spectrum, no LTE issue. Recipe: github.com/IanWraith/24DownConvert
(ADL5350 eval + ADF4351 board + MCU for SPI; no custom PCB).

## BOM

| Part | Option A (buy, fastest) | Option B (build, RF project) |
|---|---|---|
| Downconverter | Nooelec Ham It Down 100846, ~$89.95 (nooelec.com) | ADL5350 + ADF4351 modules, ~$40–70 (AliExpress/Amazon) |
| LNA | SPF5189Z module 50–4000 MHz, NF 0.6 dB, ~$5–10; or RTL-SDR Blog Wideband LNA, $18.95 (bias-tee powered) | same |
| Antenna (sat) | Homebrew LHCP helix, ~$10 in parts (see below) | same |
| Antenna (terr test) | Vertical 2.4 GHz whip (even a WiFi whip) | same |
| Dongle | existing RTL-SDR | existing RTL-SDR |

Buy-route total for first light: roughly **$105–120**.

Power detail (resolve at build): LNA wants 5V (bias-tee or USB); Ham It Down takes
bias-tee (4–5.5V) / USB-C / DC. Whether the Ham It Down passes bias-tee DC through
to the LNA is unconfirmed — plan a separate 5V feed for the LNA if not. (Needs an
RTL-SDR with bias-tee, i.e. V3 or newer.)

## Homebrew LHCP helix (2338 MHz center)

Classic Kraus axial-mode dimensions, λ ≈ 128 mm:
- Helix diameter ≈ 41 mm (circumference ≈ λ)
- Turn spacing ≈ 32 mm (0.25 λ)
- 8–10 turns → ~13–15 dBic, ~35° beamwidth
- Ground plane ~130 mm square, copper wire, SMA feed
- **Wind left-hand** when viewed from the feed looking toward the satellite.

## Phased test plan

1. Downconverter + vertical whip → check 837.49 / 840.02 MHz IF for terrestrial
   COFDM. Strong signal = repeater market; helix optional.
2. Else build LHCP helix, point at 85°W (XM-3) or 115°W (XM-4) — geostationary,
   fixed aim, huge EIRP.
3. Capture one QPSK carrier at 2.4 Msps → Phase 2 (symbol recovery, frame sync).

## Open / verify at purchase time

- Ham It Down price/stock on nooelec.com (was $89.95, in stock, checked 2026-10-07).
- Repeater coverage for his city (unconfirmed location; likely if in LA/Bay Area/SD).
- Which RTL-SDR models he owns (bias-tee present on V3+).
