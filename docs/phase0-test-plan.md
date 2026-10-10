# OrcXM Phase 0 Test Plan — S3 out-of-spec tuning
### Verbose edition — written for execution from a local clone of the OrcXM repo

> If you are an AI assistant: clone `https://github.com/hardcoreerik/OrcXM`
> to disk first, then read `README.md`, `docs/downconverter-dsp-report.md`,
> and `docs/esp32-native-exploration.md` before touching this plan. The
> boundary in `README.md` (RF/DSP only — never the encrypted audio payload)
> applies to everything here.

---

## 1. Purpose — the single question this test answers

Can the ESP32-S3's built-in 2.4 GHz Wi-Fi radio, driven through the ESP-SDR
undocumented debug path, tune to **2.33 GHz** — roughly 67 MHz below the
bottom edge of the 2.4 GHz ISM band (2400 MHz) — with **usable sensitivity**?

"Usable sensitivity" means: a real XM carrier (~−65 dBm at the antenna
terminals with LNA, per the link budget in `docs/downconverter-dsp-report.md`)
shows up at least ~10 dB above the noise floor in the on-chip spectrum, stable
enough to attempt symbol recovery later.

Why this is the whole bet: every downstream step of the ESP32-native path —
the clean-room capture driver, the on-device QPSK demodulator, the handheld
receiver — is engineering that only matters if the silicon cooperates this
far out of spec. ESP-SDR's docs say tuning attempts from 100–6000 MHz are
accepted but "extended tuning does not guarantee PLL lock or reception," and
gain is uncalibrated off-band. Nobody has published a 2.33 GHz result. This
test produces one.

**Kill criterion:** if no XM carriers *and* no terrestrial repeaters are
visible with a proper antenna + powered LNA after honest attempts, the S3
native path dies. The Pluto and RTL-SDR/downconverter plans are unaffected —
this test risks nothing except an evening.

---

## 2. Background you need before touching hardware

### 2.1 The signal (from the R&S XM-Radio manual)

| Carrier | Freq (MHz) | Type | Polarization |
|---|---|---|---|
| Sat1A | 2333.465 | QPSK | LHCP |
| Sat2A | 2335.305 | QPSK | LHCP |
| TerrA (repeater) | 2337.490 | COFDM | vertical |
| TerrB (repeater) | 2340.020 | COFDM | vertical |
| Sat2B | 2342.205 | QPSK | LHCP |
| Sat1B | 2344.045 | QPSK | LHCP |

- Satellite carriers: 1.64 Msym/s QPSK, root-raised-cosine roll-off 0.15,
  ~1.89 MHz occupied bandwidth. On a spectrum display: a **rounded bump**
  ~1.84 MHz wide.
- Repeaters: COFDM, ~1.8 MHz wide. On a spectrum display: a **flat-topped
  plateau** — visibly flatter than the QPSK bumps.
- Satellites are geostationary (85°W / 115°W): fixed aim, zero Doppler.
- Polarization trap: the satellite carriers are **LHCP** (left-hand
  circular). Most commercial 2.4 GHz helix antennas (FPV stock) are RHCP —
  wrong hand. A linear patch just costs ~3 dB, which the link budget
  absorbs. Wind homebrew helices left-hand viewed from the feed toward
  the satellite.

### 2.2 The S3 radio path (from ESP-SDR)

- ESP-SDR bypasses the Wi-Fi modem via an undocumented debug path and
  streams raw I/Q from the receiver's ADC into 3×64 KiB SRAM ring banks
  at 16 MS/s (S3). The on-chip FFT (256–2048 bins) renders spectrum
  without a PC.
- At 2332–2345 MHz the tuner uses the **direct-PLL path**. (The
  experimental 5/6 LO divider mode only covers 1842–2209 MHz, so it does
  not apply here — this is a straight ~67 MHz below-band tune attempt.)
- Reception is **RX only**. Gain is uncalibrated off-band; hardware AGC
  is the default, manual gain indices are listed by `LIMITS?`.
- Key ESP-SDR console commands (newline-terminated ASCII over native USB
  serial): `INFO`, `CAPS`, `LIMITS?`, `RANGE?`, `FREQ <MHz>`,
  `BANDWIDTH <MHz>`, `GAIN MANUAL <index>` / `GAIN HARDWARE`,
  `CAP16 <samples> <rate-index>` (signed 8-bit I/Q snapshot),
  `CAP20 <samples> <rate-index>` (packed 10-bit I/Q).

### 2.3 What "tune attempt" means in practice

The firmware will accept `FREQ 2333.465` without complaint — the viewer
only shows an informational warning outside 2400–2483.5 MHz and never
blocks. Acceptance proves nothing. **Reception** is proven only by a
recognizable signal shape (plateau or bump) at the expected frequency
that moves/disappears when you retune — the classic "tune away, signal
goes away" sanity check. Run that check on every positive: tune 10 MHz
off, confirm the feature vanishes, tune back, confirm it returns. This
rules out spurs, images, and DC artifacts masquerading as carriers.

---

## 3. Prerequisites — gather before the bench session

### 3.1 Boards
- Spare ESP32-S3 board with native USB: LilyGO T-Display-S3, T-Embed
  CC1101, or M5Stack Cardputer Advanced. Any S3 works; prefer one with an
  external antenna connector (u.FL/IPEX). Without one, the onboard PCB
  antenna suffices for the strong repeater check (Step 1) but is a
  handicap for the satellite check (Step 2).
- A **data-capable** USB cable (charge-only cables are the #1 time sink),
  preferably short and direct to the PC.

### 3.2 RF hardware
- **Repeater check:** any vertical 2.4 GHz whip (even a WiFi router whip).
  Repeaters are vertically polarized and strong.
- **Satellite check:** 2.3 GHz directional antenna or LHCP helix (see the
  polarization trap above) **plus a powered LNA at the antenna**
  (SPF5189Z module or equivalent). The LNA needs 5 V — bias-tee or a
  separate feed. The LNA is not optional for the satellite carriers.
- A satellite-finder app on the phone for azimuth/elevation to 85°W or
  115°W from your location.

### 3.3 Software
- Chrome or Edge (WebSerial support — Firefox/Safari will not work).
- ESP-SDR firmware, S3 build, flashed from
  https://espargos.net/espsdr/app/flash.html
- The browser viewer: https://espargos.net/espsdr/app/

---

## 4. Procedure

### Step 0 — Sanity check in-band (must pass before anything else)

Purpose: prove the debug path, USB link, antenna connection, and viewer
are all healthy, so any later failure is attributable to 2.33 GHz
specifically and not to the setup.

1. Flash the S3 from the flasher URL above. If the flasher can't see the
   board: try another cable, then hold BOOT while tapping RESET to force
   download mode.
2. Open the viewer URL. Connect to the board's native USB serial.
3. Send `INFO` — confirm the firmware identifies as the S3 build.
   Send `LIMITS?` — note the supported sample rates, FFT sizes, and gain
   indices. Write them down; you'll need the gain indices in Step 2.
4. `FREQ 2437`, `BANDWIDTH 20`. This is WiFi channel 6 — in any
   inhabited area you should see obvious spectral energy, bursty and
   wide.
   - **PASS:** in-band reception works. Proceed.
   - **FAIL:** stop. Debug flashing, USB, and antenna. Do not proceed —
     a dead setup at 2.44 GHz tells you nothing about 2.33 GHz.

### Step 1 — Terrestrial repeaters (easy mode)

Purpose: answer the sensitivity question with the strongest available
signals before spending effort on pointing and helices. Repeaters are
COFDM, vertical, and — in a covered market — far stronger than the
satellite carriers.

1. Antenna: vertical whip. No LNA strictly required to start, but have
   it ready.
2. `FREQ 2337.49`, `BANDWIDTH 10`, `GAIN HARDWARE` (AGC on).
3. Watch for a **~1.8 MHz flat-topped plateau** centered on 2337.49.
   COFDM's flat top is distinctive — compare against the rounded QPSK
   shape you'll look for later.
4. Run the tune-away check: `FREQ 2327`, confirm the plateau vanishes;
   `FREQ 2337.49`, confirm it returns.
5. Repeat at `FREQ 2340.02` (TerrB).
6. Try indoors first (repeaters penetrate buildings reasonably), then
   near a window or outside if nothing shows.
7. If nothing with the whip: add the powered LNA and repeat once.

**Interpreting Step 1:**
- **Plateau visible** → the S3 tunes 60+ MHz out of spec with genuine
  sensitivity. The core physics question is answered YES for strong
  signals. Proceed to Step 2 — the remaining question is only whether
  weak satellite carriers clear the noise floor.
- **Nothing after honest attempts** → inconclusive on its own. Your area
  may simply lack repeater coverage (~800 repeaters across ~60 US
  markets — not everywhere). Proceed to Step 2 regardless; the
  satellites cover everywhere.

### Step 2 — Satellite carriers (the real test)

Purpose: the actual kill-criterion measurement.

1. Antenna: 2.3 GHz directional or LHCP helix **+ powered LNA mounted at
   the antenna** (feedline loss before the LNA directly degrades SNR).
2. Aim: 85°W or 115°W, whichever is higher in your sky. Geostationary =
   fixed aim; get azimuth/elevation from a satellite-finder app. A few
   degrees of error is fine (helix beamwidth is wide); being 30° off is
   not.
3. `FREQ 2333.465` (Sat1A), `BANDWIDTH 4`, `GAIN HARDWARE`.
4. Look for a **~1.84 MHz rounded bump** (QPSK with RRC 0.15 has soft
   shoulders, not a brick wall), ideally 10+ dB above the surrounding
   noise floor.
5. Run the tune-away check (`FREQ 2323` → gone → `FREQ 2333.465` →
   back). This is the single most important anti-fooling step in the
   whole plan.
6. Repeat for 2335.305, 2342.205, 2344.045.
7. If a bump is marginal (a few dB, flickering): step through manual
   gain (`GAIN MANUAL <index>` from the `LIMITS?` list you wrote down),
   try `BANDWIDTH 2` to concentrate the FFT bins, and nudge aim ±5°.
   Distinguish a real carrier from a spur: real carriers are ~1.84 MHz
   wide and sit exactly on the known centers; spurs are usually
   narrower and don't move correctly with retuning.
8. Note the approximate SNR of the best carrier — this number decides
   how much DSP margin the demodulator will have later.

**Interpreting Step 2:**
- **≥1 carrier visible** → **Phase 0 GREEN.** The S3 does 2.33 GHz.
  Proceed to Step 3, then report back (see Section 6).
- **Nothing, with proper antenna + powered LNA + verified pointing** →
  **Phase 0 RED.** The S3 native path is dead. Fall back to the Pluto
  plan (`docs/pluto-path.md`). No shame in it — the physics answered.

### Step 3 — Capture evidence (both outcomes)

Negative results are data — capture them with the same care as positives.

1. Screenshot the spectrum at every tuned frequency, pass or fail.
   Include the frequency readout and gain setting in frame.
2. If carriers are visible: capture a raw IQ snapshot —
   `CAP16 16384 <rate-index>` at 2333.465 MHz (pick a rate index from
   `LIMITS?`; 16 MS/s preferred). Verify the reply's CRC32 before
   trusting the payload. Save the binary for later offline analysis.
3. Fill in the session log (Section 6) while details are fresh.

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Flasher can't see the board | Charge-only cable / not in download mode | Swap cable; hold BOOT, tap RESET |
| Viewer connects but spectrum is flatline | Antenna disconnected / wrong port | Check u.FL seating; redo Step 0 |
| Step 0 shows nothing at 2437 MHz | Setup issue, not 2.33 GHz | Do not proceed; fix the setup |
| Signals drift slowly across the display | Cheap crystal | Normal; note it, don't chase it |
| A "bump" that doesn't move with retuning | Spur, image, or DC artifact | Tune-away check exposes it |
| Everything looks like noise at 2.33 GHz | Gain too low / LNA unpowered | Verify LNA power LED; step manual gain up |
| Intermittent USB disconnects | Cable or hub | Short direct cable, no hub |

---

## 6. Reporting back — fill this in after the session

Copy this block into chat when reporting results:

```
Phase 0 report — <date>
Board: <model, e.g. T-Display-S3>
Antenna: <whip / helix / patch, polarization>
LNA: <model, powered Y/N>
Location: <indoor / outdoor, city or region>
ESP-SDR version: <from INFO>

Step 0 (2437 MHz sanity): PASS / FAIL
Step 1 repeaters (2337.49 / 2340.02): <plateau visible Y/N, approx dB above noise>
Step 2 satellites:
  2333.465: <visible Y/N, approx SNR>
  2335.305: <visible Y/N, approx SNR>
  2342.205: <visible Y/N, approx SNR>
  2344.045: <visible Y/N, approx SNR>
Tune-away checks performed: Y/N
Verdict: GREEN (build the driver) / RED (kill the S3 path)
Notes: <anything odd — drift, spurs, USB issues>
```

---

## 7. Reference

- ESP-SDR firmware + docs: https://github.com/ESPARGOS/esp-sdr (GPL-3.0 —
  read for understanding only; OrcXM's driver will be clean-room)
- Browser flasher: https://espargos.net/espsdr/app/flash.html
- Browser viewer: https://espargos.net/espsdr/app/
- Carrier table: R&S SMx/AMU-K56 "XM-Radio" operating manual (public PDF)
- Project docs in this repo: `docs/downconverter-dsp-report.md`
  (link budget, DSP chain), `docs/esp32-native-exploration.md`
  (why the S3 can plausibly do this), `docs/phase1-frontend-bom.md`
  (antenna/LNA specifics), `docs/pluto-path.md` (fallback plan)
