# ESP32-S3 Native XM Decoder — Technical Exploration

Date: 2026-10-07 | Goal: goal_c6660f85aef1
Question: can an ESP32-S3 **alone** (no FPGA, no downconverter, no RTL-SDR, no PC) receive and demodulate XM satellite radio?
Boundary (firm): RF/DSP only — symbol recovery, frame sync, transport demux, stream analysis. NEVER the encrypted audio payload, codecs, or key provisioning.

**Verdict: FEASIBLE WITH CONDITIONS.** The RF capture path is proven in hardware by ESP-SDR's design; the DSP budget closes on paper with modest headroom; the single biggest risk is that S3 reception at 2.33 GHz is uncharacterized — Phase 0 (a $0 firmware flash + antenna/LNA) answers it definitively before any serious work begins.

---

## A. RF capture path — can the app CPU get continuous raw I/Q?

**Short answer: yes — the hardware path is proven, but ESP-SDR's firmware doesn't hand it to you; a clean-room driver must reimplement the capture loop with an app callback.**

What I verified in the ESP-SDR source (`main/targets/esp32s3/receiver.c`, `main/common/ring_capture.c/.h`):

- The dump engine (`adctrig` ROM function + `DUMP_CTRL_REG` at `0x60033d5c`) writes raw IQ words **directly into SRAM** at 16/40/80 MS/s (rate code 6 = 16 MS/s via bit 16, code 1 = 40 MS/s via bit 15, code 0 = 80 MS/s). No software resampling — it's a hardware path.
- Continuous mode uses **3 ring banks × 64 KiB** (`RING_BANK_BASE 0x3fcb0000`, `RING_BANKS 3`, `RING_PAIRS 16384`), reserved out of the heap via `SOC_RESERVE_MEMORY_REGION`. 192 KiB of the S3's 512 KiB SRAM.
- Bank rotation is **software-polled**: core 0 polls `DUMP_WRITE_INDEX_REG` (`0x60033d60`), and when a bank passes `RING_THRESHOLD` (12288 pairs) it prepares the next bank and hands the full one to the worker. Their SPEC mode "keeps the RF writer running" indefinitely — continuous capture is proven, not theoretical.
- Each 32-bit IQ word = one complex sample: **I in bits [11:2], Q in bits [21:12]** (10-bit signed each; confirmed in `s3_firdot.S` `s3_unpack_iq10_split`).
- The IQS "streaming" mode (max 250 kSa/s) is a **software** two-stage FIR decimation (64–1024×) running on core 1 over the *same* raw banks. 250 kSa/s is far too slow for 1.64 Msym/s (need ≥3.28 MS/s at 2 samp/sym) — so the app must tap the banks **before** decimation, i.e., raw 16 MS/s words.

**The tap point:** the ring banks *are* the pre-decimation stream. A clean-room driver reimplements: `prepare_rx()` equivalent (Wi-Fi init → promiscuous → `s3_tune()` → `adctrig` → dump-engine register setup), then the poll/rotate loop, calling an app callback with each full bank's pointer + count. No code is copied — only the hardware facts (register addresses, bit meanings, bank protocol) are reused, which is how the ESP-SDR authors themselves describe the discovery ("not protected by copyright").

**Timing constraint (hard real-time):** at 16 MS/s, one bank's 12288-pair threshold fills in **768 µs**. The app must consume each bank within ~1.5 ms (3-bank rotation) or the engine overwrites it (their `RING_FAIL_LATE` exists for exactly this). Interrupts are masked during the switch itself; the poll loop otherwise coexists with FreeRTOS.

**Tuning at 2.33 GHz:** `rx_lo_plan()` in `main/common/rx_lo.h` uses the experimental 5/6 LO divider mode only for 1842–2209 MHz. XM's 2332.5–2345 MHz falls in the **direct-PLL** path (`alternate = false`), i.e., the synthesizer is simply tuned ~67 MHz below the 2.4 GHz ISM edge. The firmware *attempts* 100–6000 MHz ("the warning never blocks tuning") but the README is explicit: "Extended tuning does not guarantee PLL lock or reception." Gain/filter calibration at 2.33 GHz is uncharacterized. **This is the Phase 0 bench experiment, not something to assume.**

## B. DSP budget — real-time QPSK demod on dual 240 MHz LX7

Assumptions: 16 MS/s complex in (IQ10 words) → polyphase RRC ÷4 → 4 MS/s (2.44 samp/sym) → Gardner timing recovery → 1.64 Msym/s symbols → 2nd-order Costas → slicer. S3 PIE SIMD does 8× int16 MACs per instruction (`ee.vmulas.s16.accx`).

Per-bank cost (12288 input pairs = 768 µs of signal; budget per bank on one 240 MHz core ≈ 184k cycles):

| Stage | Work per bank | ~Cycles |
|---|---|---|
| Unpack IQ10 → int16 I/Q (`s3_unpack_iq10_split`-style) | 12288 samp × ~2.5 cy | ~31k |
| Polyphase RRC FIR ÷4 (64 taps → 16 MACs/out/rail) | 3072 out × 32 MACs @ 8/instr + overhead | ~25k |
| Gardner TED @ 4 MS/s + loop filter + interpolator ctrl | 3072 samp × ~8 cy + symbol-rate overhead | ~35k |
| 2nd-order Costas @ 1.64 MS/s (1260 sym/bank) | 1260 × ~25 cy | ~31k |
| AGC, DC removal, misc | — | ~10k |
| **Total** | | **~132k / 184k ≈ 70% of one core** |

**The budget closes, with modest headroom.** One LX7 core runs the full demod chain at ~70%; the other core does capture rotation + UI. ESP-DSP (available for Arduino/PlatformIO) provides the SIMD FIR/FFT primitives; the Gardner/Costas loops are small hand-tuned kernels.

**Tightest constraint:** the 768 µs bank deadline is hard real-time — an overrun drops a bank (audible as a sync slip, recoverable, but it breaks the "continuous" guarantee the frame sync wants).

**What breaks first / fallbacks (in order):**
1. Trim the RRC to 48 taps (saves ~25% of FIR cost, negligible matched-filter loss at roll-off 0.15).
2. Decimate ÷8 → 2 MS/s (1.22 samp/sym) and swap Gardner for Mueller-Müller at ~1 samp/sym — halves front-end cost, slightly worse timing jitter.
3. Snapshot-assisted demod (capture bursts, demod offline-style between bursts) — loses continuous frame sync; last resort, changes the architecture.

Memory: unpacked bank = 64 KiB int16 I/Q + FIR delay lines (few KiB) + loop state (bytes). Fits comfortably in SRAM alongside the 192 KiB ring. Long captures for frame-sync RE go to PSRAM (T-Display-S3 has octal PSRAM).

## C. Architecture sketch — the device

**Hardware:** LilyGO T-Display-S3 + 2.3 GHz antenna + LNA module. Antenna: LHCP helix is proper (sats are LHCP); a linear patch costs 3 dB the link budget doesn't miss (~40 dB margin). LNA (SPF5189Z module, ~20 dB) mounted at the antenna — non-negotiable, same as the dongle plan. Total RF chain: antenna → LNA → S3's existing 2.4 GHz antenna port (U.FL/pcb — needs a U.FL pigtail to the LNA; front-end match is designed for 2.4 GHz, small loss at 2.33 GHz acceptable).

**Core split:**
- **Core 0 (Pro CPU):** capture rotation poll loop (highest priority, short critical sections), LVGL/display refresh (~15–20 Hz), touch input, session/evidence logging (NEONDRIVE already has this infra).
- **Core 1 (App CPU):** DSP pipeline — unpack → polyphase FIR → Gardner → Costas → slicer → frame-sync correlator → demux. Runs bank-to-bank with the 768 µs deadline.

**On screen (T-Display-S3, 320×170 ST7789):**
- Live spectrum waterfall at 2.33 GHz (reuse NEONDRIVE's `scopeWaterfall` infra — the buffer we just heap-allocated for the DRAM fix),
- Constellation diagram (post-Costas, decimated for display),
- Lock panel: timing lock / carrier lock / frame lock indicators + estimated SNR,
- Carrier table: the 6 XM carriers with present/absent + measured power,
- Post-demux: ensemble/channel map and stream metadata (unencrypted multiplex info only).

**Frame-sync RE strategy:** do it the cheap way — record long raw-IQ captures to a host (UART/USB dump of bank data, or PSRAM buffer dumped later), find the sync word offline via autocorrelation on a PC, then bake the known word into firmware as a real-time correlator (~64-bit pattern match at symbol rate = trivial on-device). On-device blind sync-word hunt is wasted effort; the RE happens once, on the host.

**NEONDRIVE fit:** a new module (name TBD — `XM` alongside the Packet Lab modules), reusing the display, waterfall, session/evidence, and logging infrastructure. The RF driver is a new clean-room component (ESP-IDF-style register driver, callable from Arduino). Not a standalone firmware — the module system is the right home, and the spectrum-waterfall SDR proposal (Phase 1) is literally the same RF driver with a different DSP tail, so the two projects share the hardest part.

## D. Staged plan

**Phase 0 — RF verification ($0 + antenna/LNA ~$30–50, needed regardless).**
Flash stock ESP-SDR firmware on a spare T-Display-S3, connect antenna+LNA, open their browser viewer, tune 2333.465 MHz. Exit criteria: satellite carriers visible in spectrum, or definitively absent after gain/filter sweeps. Kill criterion: no carrier energy detectable → the S3 path is dead, fall back to the RTL-SDR + downconverter plan (which is unaffected). Time: an evening.

**Phase 1 — Clean-room capture driver (no new hardware).**
Reimplement the capture path (RX setup → `adctrig` → dump engine → bank rotation with app callback) as a NEONDRIVE component. No DSP yet — just shovel banks into a counter. Exit criteria: 60 s continuous 16 MS/s capture, zero late-bank failures, bank checksums sane. This de-risks the entire software schedule.

**Phase 2 — On-device demod (no new hardware).**
DSP chain per §B; constellation + lock indicators + SNR on screen. Exit criteria: stable Costas lock on a real XM carrier, measured SNR within a few dB of the link-budget prediction, symbols slicing cleanly. The "it works" demo.

**Phase 3 — Frame-sync RE (no new hardware).**
Long IQ recordings → host-side sync-word hunt → bake correlator into firmware. Exit criteria: frame lock achieved on-device and holding. This is the schedule risk (unknown unknowns in an undocumented TDM structure) — time-box the blind hunt; the multiplex may yield to autocorrelation of the known 1.64 Msym/s structure.

**Phase 4 — Demux + stream analysis UI (no new hardware).**
Transport demux, ensemble/channel map display, stream metadata. Stops hard at the encryption boundary — encrypted audio payloads are counted and characterized, never decrypted. Exit criteria: channel map on screen, stream info decoded.

## E. Risks, ranked

1. **Off-band RX at 2.33 GHz uncharacterized** — Likelihood: medium-high that it underperforms the 2.4 GHz spec; Impact: **project-killing** if carriers are invisible. Mitigation: Phase 0 answers it in one evening for ~$0 beyond the antenna/LNA (needed anyway). Kill criterion is explicit. Fallback (RTL-SDR + downconverter) is independent and unaffected.
2. **Frame-sync RE unknowns** — Likelihood: medium (undocumented TDM, no public sync word); Impact: high (no demux without it). Mitigation: offline RE with long captures; autocorrelation against the known symbol rate; time-box the blind phase. This is schedule risk more than kill risk — the RF and demod work retains value (spectrum + constellation + carrier analysis) even if demux stalls.
3. **CPU budget overrun** — Likelihood: low-medium; Impact: medium (dropped banks → sync slips). Mitigation: quantified at ~70% of one core with hand-tuned PIE; fallbacks in §B (48-tap FIR, ÷8 + Mueller-Müller). Measured early in Phase 2 via cycle counters per bank.
4. **Debug-path silicon sensitivity** — Likelihood: low-medium; Impact: medium (works on Erik's boards, maybe not every S3). Mitigation: validate on his actual bench boards in Phase 0/1; document chip revisions. Not a project killer for a homebrew receiver.
5. **GPL clean-room discipline** — Likelihood of a slip: low if disciplined; Impact: high (license contamination of NEONDRIVE's PolyForm Noncommercial codebase). Mitigation: contamination log from day one; describe mechanisms, never copy code; the register facts are hardware truths, not expression. (Note: h0m3us3r's eSpDR rotation scheme is 0BSD, but the S3 register-poke path still gets clean-room treatment.)
6. **Antenna/LNA still required** — not a risk, just physics and ~$30–50. The LNA-at-antenna is the highest-leverage dollar in the whole project.

## F. The pitch

An ESP32-S3 board, a $10 LNA, and a homebrew antenna becomes a handheld XM satellite receiver — live S-band spectrum, constellation, and transport demux on a wrist-sized display, no PC, no dongle, no downconverter, no FPGA. Nobody has put an on-chip SDR waterfall on a microcontroller yet (Hackaday is openly doubting it's possible); doing it for a real satellite downlink would be a genuine first.

The honest version: the RF trick is real but the 2.33 GHz reception is unverified until Phase 0, the DSP budget is tight-but-closable rather than comfortable, and the frame-sync reverse-engineering is the long pole — the demodulator is engineering, the demux is research. If Phase 0 shows carriers, the rest is execution risk, not physics risk.

## Open bench experiments (named, not guessed)

1. Does the S3 PLL lock at 2333.465 MHz with usable gain? (Phase 0 — the one experiment that matters.)
2. Effective sensitivity / noise figure at 2.33 GHz vs. the 2.4 GHz band.
3. Whether the 5/6 LO alternate mode helps or hurts at 2332–2345 MHz (theory says direct-PLL; verify).
4. Bank-rotation timing margin under full DSP load (Phase 2 cycle-counter measurement).
