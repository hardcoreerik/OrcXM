# XM Satellite Decoder — Downconverter & DSP Research Report
Date: 2026-10-07 | Goal: goal_c6660f85aef1
Boundary (firm): RF/DSP only — frame sync, transport demux, stream analysis. NEVER the encrypted audio payload or key provisioning.

## 0. Signal facts (verified, sourced)

From the Rohde & Schwarz SMx/AMU-K56 "XM-Radio" operating manual (public PDF):
- **Carrier plan** — Ensemble A: Sat1A 2333.465 MHz, Sat2A 2335.305 MHz, TerrA 2337.490 MHz; Ensemble B: TerrB 2340.020 MHz, Sat2B 2342.205 MHz, Sat1B 2344.045 MHz. Satellites: QPSK, LHCP. Terrestrial repeaters: COFDM, vertical polarization.
- **Symbol rate: 1.64 Msym/s**, root-cosine roll-off 0.15 → 3.28 Mbit/s raw per carrier, ~1.89 MHz occupied bandwidth. (Matches the "1.84 MHz carrier" figure.)
- Each ensemble = 2 satellite carriers carrying the same content with ~4 s time-diversity delay + 1 terrestrial COFDM channel.
- Receiver reference design (EDN teardown): STMicro STA801 front-end tuner, single SAW preselect filter — i.e., the commercial RX chain is simple; the magic is all DSP.

From Wikipedia (Technology section, cited): 6 carriers in 12.5 MHz, only 2 carry unique content (4 are diversity dupes); content is organized as 100× 8 kbps streams per two-carrier group, built from 4-kbps virtual streams into 4–64 kbps channels. Audio codecs: HE-AAC (music), AMBE (voice) — **payload side of the boundary, do not touch**.

**Honest unknowns (the RE work):** the TDM frame structure (frame length, sync word/pilots) and the FEC scheme are NOT in any public source found. No open-source XM satellite demodulator exists (GitHub "siriusxm" repos are all internet-stream players). Frame sync + demux = the real project.

Link-budget sanity check: 70 dBW EIRP, GEO path loss at 2.33 GHz ≈ 191 dB → ≈ −91 dBm isotropic at ground. A 6 dBi patch + 20 dB LNA gives ≈ −65 dBm at the dongle against a −108 dBm noise floor (1.9 MHz, NF≈3 dB) → ~40+ dB SNR available; QPSK needs ~10 dB. A small patch + LNA has enormous margin. No dish needed — confirmed quantitatively.

## 1. TRACK 1 — Downconverter buy vs build

Requirement: 2332.5–2345 MHz → IF comfortably inside the RTL-SDR's range (<1.7 GHz), LO clean enough for 1.64 Msym/s QPSK (a Costas loop tolerates kHz-level drift easily; the bar is low).

### Buy
| Option | What | IF for XM band | Price (approx) | Notes |
|---|---|---|---|---|
| **Nooelec Ham It Down 3 GHz** | 1.55–3.1 GHz → 50 MHz–1.6 GHz, fixed 1.5 GHz LO, 1PPM TCXO, internal RF/IF/LO filters, bias-tee/USB-C/DC power | 832.5–845 MHz | **~$90 USD** (AMSAT 2023; Amazon.de €101; EU resellers ~€120) | Purpose-built for exactly this. 1 ppm = 2.3 kHz worst drift at 2.33 GHz — trivial for carrier recovery. In stock on Amazon. |
| KD0CQ SUP-2400 mod | $5–10 DirecTV module, SMD mod → 2.4 GHz downconverter (up to ~4.5 GHz) | depends on mod | $5–25 (pre-modded $25 at RXTXDX, 2017 — likely unavailable now) | SiriusXM @ 2.3 GHz explicitly listed as an application. Needs decent SMD soldering; phase-noise/quality uncharacterized; module availability in 2026 uncertain. |
| Chinese MMDS downconverters | 2.2–2.4 GHz, LO 1998 MHz → IF 334–347 MHz | 334–347 MHz | ~$15–25 (historical) | MMDS is dead tech; 2026 availability doubtful. "If you find one" only. |
| Kuhne LNC2227 | Pro S-band LNC | — | ~€220 | Overkill. Skip. |

### Build (module-level, no custom PCB required)
- **LNA (at antenna, most important part):** SPF5189Z module, 50 MHz–4 GHz, ~$5–10. This sets the system noise figure — do this regardless of buy/build.
- **Mixer:** ADL5350 eval module (~$20) — proven precedent: IanWraith/24DownConvert (github.com/IanWraith/24DownConvert) built a 2.4 GHz→1.4 GHz downconverter from exactly this + ADF435x + STM32.
- **LO:** ADF4351 dev module (~$20–30, Amazon/AliExpress), SPI-programmed 35 MHz–4.4 GHz. Phase noise ≈ −89 dBc/Hz @ 10 kHz at 2.2 GHz — fine for QPSK.
- **LO control:** any small MCU — Erik already has ESP32s; 6 SPI registers, Analog Devices has a calculator tool.
- **Filtering:** 2.3 GHz bandpass preselector (SAW module or homebrew edge-coupled microstrip) + IF lowpass.
- **Example frequency plan:** LO = 1533.465 MHz → Sat1A 2333.465 → IF 800 MHz; image at 733.465 MHz, 1.6 GHz from RF — killed by any reasonable 2.3 GHz BPF. All four sat carriers land at 800–810.6 MHz; dongle tunes one at a time, no LO retune needed.
- **Estimated total:** ~$60–80 in modules + antenna + cabling + shielding box.
- **Gotchas:** (1) image rejection lives and dies on the preselect filter; (2) ADF4351 integer-boundary spurs — pick LO frequencies away from integer multiples of the PFD; (3) LO leakage into the RF port; (4) shielding — IanWraith measured his STM32's crystal harmonics in the 2.4 GHz band, keep digital and RF in separate screened boxes; (5) clean 5 V power (switching-supply noise becomes phase noise).

### Verdict
**Buy the Nooelec Ham It Down (~$90), homebrew the antenna + LNA + preselect filter.** Rationale: the downconverter is the fiddliest block with the least learning value per dollar and the most ways to silently underperform (spurs, images, leakage); Nooelec's TCXO/filtered/cased unit removes a whole debug dimension for $90. The antenna (2.33 GHz patch or helix — note LHCP for the satellite carriers, though a linear patch eats only 3 dB and the link budget has 30 dB to spare) and the LNA/filter are where the homebrew RF learning actually lives, and Erik's bench is well suited to them. If the homebrew itch needs scratching, the ADF4351+ADL5350 module stack is a proven weekend build — but do it as phase 2, after first light with the Nooelec.

## 2. TRACK 2 — DSP chain scope

### Demod chain (all blocks exist off-the-shelf except where noted)
1. **Capture:** `rtl_sdr -f <IF> -s 2.4e6` → 8-bit IQ. One carrier at a time (1.89 MHz fits in 2.4 Msps with margin).
2. **Channel select:** complex bandpass / frequency shift + RRC matched filter (roll-off 0.15), decimate to 2 samples/symbol → 3.28 Msps.
3. **Timing recovery:** Gardner or Mueller-Müller TED + interpolator (GNU Radio `digital.symbol_sync`).
4. **Carrier recovery:** Costas loop (2nd order for QPSK) — handles the TCXO drift and Doppler (GEO Doppler is negligible, <100 Hz).
5. **Differential/phase-ambiguity resolution:** TBD once the frame structure is known (may need the sync word to resolve quadrant ambiguity).
6. **Frame sync (CUSTOM — the RE core):** autocorrelate the demodulated bitstream against candidate sync words; the TDM structure is undocumented publicly. The R&S manual confirms PN9 test data and a configurable satellite delay (time diversity) exist in the waveform definition — useful for building a local reference transmitter.
7. **Demux + stream analysis (CUSTOM, stops at encryption boundary):** parse the TDM multiplex into its 4-kbps virtual streams; analyze framing, channel-lineup metadata, and any in-the-clear signaling. Audio payloads stay untouched, always.

### Tooling
- **GNU Radio 3.10+** (via Radioconda on Windows — Erik's platform): `digital.symbol_sync`, `digital.costas_loop_cc`, RRC filters, constellation sinks. All modem primitives exist; only frame-sync/demux are custom.
- **Reference signal source:** the R&S manual fully specifies the generatable waveform (1.64 Msym/s, RRC 0.15, PN9) — enough to synthesize a bit-exact local test vector in GNU Radio for loopback validation without any RF hardware.

### Staged bring-up (cheapest first signal first)
- **Stage 0 — software loopback ($0):** generate the R&S-spec waveform in GNU Radio, run the full Gardner+Costas chain on it. Validates the modem with zero hardware. Success = clean constellation, zero BER on PN9.
- **Stage 1 — RF loopback (optional, if a TX-capable SDR is handy):** transmit the test waveform over the air at low power in the 2.3 GHz ISM-adjacent space... (note: 2.33 GHz is a licensed band — keep this cabled/attenuated, not radiated) through downconverter → dongle. Validates the analog chain.
- **Stage 2 — first real light:** patch/helix + LNA + Ham It Down + RTL-SDR pointed at 85°W or 115°W (elevation/azimuth from Erik's location). Expect the four QPSK carriers as obvious ~1.9 MHz humps; demod → constellation. The terrestrial COFDM repeaters (2337.49/2340.02 MHz) are a separate, harder waveform — skip for first light even if stronger nearby; come back to them later.
- **Stage 3 — frame sync RE:** capture long recordings, hunt the sync word by autocorrelation, determine frame length and TDM layout.
- **Stage 4 — demux & stream analysis:** demultiplex to virtual streams, characterize the multiplex, document everything. Hard stop before any encrypted payload.

## 3. WILD CARD — ESP-SDR direct capture (SPECULATIVE)

Could an ESP32-S3 with a 2.3 GHz antenna+LNA digitize the XM downlink directly — no downconverter, no RTL-SDR?

- **Frequency:** ESP-SDR tunes 100–6000 MHz in software (warning outside 2.4 GHz ISM, never blocked); nominal range quoted as 2.2–2.7 GHz on some chips. XM at 2332.5–2345 MHz sits just below the 2.4 GHz ISM band, inside the normal tunable range — the experimental 5/6 LO mode (down to 1.84 GHz) isn't even needed. Plausible.
- **Bandwidth:** S3 does 16/40/80 MS/s; 16 MS/s is ~8× the 1.89 MHz carrier. Plenty.
- **Caveats (real):** RX quality at 2.33 GHz is uncharacterized (gain/power uncalibrated, PLL lock not guaranteed off-band); the ESP32 RF front-end match is designed for 2.4 GHz (small mismatch loss at 2.33 GHz, acceptable); debug-path silicon-revision sensitivity; data egress over USB serial in snapshot/FFT modes.
- **Assessment:** genuinely plausible as a bench experiment — Erik has the S3 boards, and it would collapse the entire analog chain to antenna+LNA+board. But it must not gate the main path: unproven RF performance at 2.33 GHz, and the DSP work is identical either way. Recommendation: try it as a parallel side experiment once the antenna+LNA exist (they're needed regardless); keep the downconverter+dongle as the primary path until the S3 proves itself on real XM carriers.

## 4. Open questions for Erik
1. **Downconverter call:** buy the Ham It Down (~$90), or full-homebrew module stack (~$60–80 + a weekend)? (Verdict above: buy converter, homebrew antenna/LNA.)
2. **Location (metro area):** determines GEO look angles for 85°W/115°W and whether terrestrial repeaters are nearby.
3. **TX hardware for RF loopback:** HackRF/Pluto or similar on hand? (Optional — Stage 0 needs none.)
4. **Antenna preference:** LHCP helix (proper polarization, more build) vs. linear patch (3 dB penalty, link budget doesn't care)?
5. **Wild card:** green-light the ESP-S3 direct-capture side experiment alongside the main path?
6. **Windows DSP environment:** Radioconda (GNU Radio on Windows) acceptable, or prefer Linux VM/WSL?
