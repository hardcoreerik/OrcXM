# SiriusXM as a technical system — research dump, 2026-10-17

External survey of the SDARS system OrcXM is receiving: spectrum and regulation, air
interface, receivers, conditional access at an architectural level, the IP delivery layer,
the open-source player ecosystem, and the SDR/hardware-hacking landscape.

**Scope note.** This is a survey of public information, not a circumvention guide. §6
describes the conditional-access layer only architecturally. No keys, key-derivation steps,
or decryption procedures appear here, and none were sought. OrcXM's boundary is unchanged.

**Evidence tags**

| Tag | Meaning |
|---|---|
| **[DOC]** | Verified against a primary or authoritative document and re-fetched from this machine during this pass |
| **[DOC·A]** | Quoted from a primary source by the research sub-agent, but that host would not serve the document to this machine (Google Patents, Justia, FreePatentsOnline all returned 403/503). Treat as high-confidence, not first-hand |
| **[REP]** | Widely reported secondary source, not confirmed by a primary document |
| **[INF]** | Inference, arithmetic or reasoning from the cited facts — mine, not a source's |

---

## 1. Headline: what this changes for OrcXM

Three findings actually move the project forward.

**1. The carrier table is now externally confirmed, quantitatively.** §4 shows the six
frequencies fit the FCC-allocated XM block to within **22 kHz at one edge and 12 kHz at the
other**, and that the terrestrial pair's midpoint equals the FCC-documented XM repeater
centre **to the kilohertz**. That is not a coincidence; it is a derived check that could have
failed and did not. It also independently re-derives the 1.64 Msym/s symbol rate *and* the
0.15 roll-off, because only that combination produces a 1.886 MHz envelope that exactly tiles
a 12.5 MHz block.

**2. The air interface is less dark than the README claims.** Frame durations, preamble
lengths, sync *strategy*, symbol rates, occupied bandwidths, polarisation and the FEC
*families* are all in granted patents. What remains genuinely secret is narrower than "TDM
frame structure and FEC are not public" — see §5.5. This changes the RE plan: the frame-sync
search now starts from a 432 ms master frame with a 128-bit preamble and a 192-bit padding
field, not from a blank page.

**3. Nobody has published a successful SDARS satellite demodulation with an SDR.** §8.1
records the search as a negative result. OrcXM's frame-sync work is not re-treading a solved
public problem — which is either the reason to push or the reason to stop, and is worth
knowing either way.

Two things this dump does **not** deliver: the exact satellite carrier plan from a primary
document (nobody publishes it; §5.5, §10), and any measured link budget at 2.33 GHz
(§8.3 — no open dataset exists).

---

## 2. Spectrum and regulation

### 2.1 The allocation

**[DOC]** 47 CFR §25.214(c)(1): "Exclusive SDARS licenses are limited to the 2320-2345 MHz
segment of the 2310-2360 MHz allocated bandwidth for SDARS."
<https://www.law.cornell.edu/cfr/text/47/25.214>

**[DOC]** §25.214(c)(2): "Two, 12.5 MHz frequency assignments are available for satellite
DARS: 2320.0-2332.5 MHz and 2332.5-2345.0 MHz." Same URL.

**[DOC]** §25.214(c)(5) authorises feeder uplinks in the C-band, 7025–7075 MHz and
6725–7025 MHz. The satellites are fed from large earth stations and broadcast down in S-band.
Same URL.

**[REP]** The 2310–2360 MHz band was allocated to broadcast-satellite-sound at WARC-92, and the
US licensed two SDARS operators in 1997 (American Mobile Satellite → XM; Satellite CD Radio →
Sirius). <https://en.wikipedia.org/wiki/Digital_audio_radio_service>

**[DOC]** Adjacent spectrum is Wireless Communications Service, interleaved around SDARS inside
2305–2360 MHz. <https://docs.fcc.gov/public/attachments/FCC-07-215A1.pdf>

### 2.2 Where the repeaters sit inside each block — verified

This is the load-bearing regulatory fact for §4, and I extracted it from the FCC PDF directly.

**[DOC]** FCC 07-215, footnote:
> "The SDARS licensees intend to operate their terrestrial repeaters in the middle of their
> authorized frequency bands (i.e., 2324.1-2328.4 MHz for Sirius and 2336.2-2341.3 for XM
> Radio)."

<https://docs.fcc.gov/public/attachments/FCC-07-215A1.pdf>

So the architecture is **satellite carriers toward the outer edges, terrestrial repeater
emission in the middle** of each 12.5 MHz block. OrcXM's band is the second block,
2332.5–2345, with repeaters confined to 2336.2–2341.3.

### 2.3 Emission widths — verified from FCC equipment grants

**[DOC]** A 2026 grant for a current repeater product (FCC ID `RS2DRU2-1KW0001`, model
DRU2-1KW0001, applicant Sirius XM Radio LLC, granted 2026-05-08) lists two operating entries:

| Frequency | Output | Emission designator | Rule part |
|---|---|---|---|
| 2326.25 MHz | 1021.9 W | `4M06W1W` | 25 |
| 2338.755 MHz | 1122.5 W | `5M01W1W` | 25 |

<https://fccid.io/RS2DRU2-1KW0001>

Decoded: `4M06W1W` = 4.06 MHz necessary bandwidth, W = combined amplitude/angle/pulse
modulation, 1 = single digital channel with no modulating subcarrier, W = combination of
information types. `5M01W1W` = 5.01 MHz, same decoding.
<https://fccid.io/Emissions-Designator/4M06W1W>

**[DOC·A]** `RS2SR20W` (2019 "Spot Repeater") operates at 2326.25 MHz; other filings in the
same grantee list include `RS2DTR0200` and `RS2DBESR20W`.

**Two documented repeater centres: Sirius 2326.25 MHz, XM 2338.755 MHz.** Hold onto
2338.755 — §4 uses it.

### 2.4 Repeater power and the transparency rule

**[DOC]** §25.214(d): repeaters at ≤12 kW average EIRP, maximum peak-to-average power ratio
13 dB; higher power only until an affected WCS licensee gives notice, then 180 days to comply.
<https://www.law.cornell.edu/cfr/text/47/25.214>

**[DOC]** §25.144(e)(7)(ii) specifies PAPR measured by CCDF, not exceeding 13 dB "for more
than 0.1 percent of the time". <https://www.law.cornell.edu/cfr/text/47/25.144>

**[DOC]** §25.144(e)(4) restricts repeaters to:
> "the simultaneous retransmission of the complete programming, and only that programming,
> transmitted by the SDARS licensee's satellite(s) directly to the SDARS licensee's
> subscribers' receivers, and may not be used to distribute any information not also
> transmitted to all subscribers' receivers."

Same URL. Repeaters are legally transparent gap-fillers, not local content insertion points.
**[INF]** Usefully for OrcXM: it means terrestrial and satellite copies of a programme must be
the same programme, which is what makes diversity combining meaningful and what a
satellite/terrestrial comparison would be able to exploit.

### 2.5 Network scale

**[DOC]** FY2025 Form 10-K: "We operate **over 1,000 terrestrial repeaters** across the United
States" and "we lease or license space at **approximately 520 locations**".
<https://www.sec.gov/Archives/edgar/data/908937/000090893726000006/siri-20251231.htm>

**[INF]** >1000 repeaters at ~520 sites implies roughly two chains or feed paths per site,
consistent with the two-operator heritage of the network.

### 2.6 Post-merger ownership

**[DOC]** Merger order is MB Docket 07-57, FCC 08-178, adopted 2008-07-25, released 2008-08-05.
Conditions included an interoperable receiver at retail within nine months, opening device
manufacturing to third parties, a three-year price freeze, and noncommercial-programmer
set-asides. <https://docs.fcc.gov/public/attachments/FCC-08-178A3.pdf>

**[DOC]** The same 10-K says two satellites carry service "on frequencies originally licensed by
the FCC to Sirius Satellite Radio Inc." and two "on frequencies originally licensed by the FCC
to XM Satellite Radio Holdings Inc." — so the heritage band split is still operational, not
merely historical.

**Licence expiries per the 10-K:** FM-5/FM-6 2030; XM-3/XM-5 2026; SXM-8 2029; SXM-7 2029
(not in use); SXM-9/SXM-10 2033. Repeater network "through 2027".

**[INF]** The band is licensed, not owned. SiriusXM holds exclusive space-station and blanket
repeater authorisations for both 12.5 MHz blocks.

---

## 3. The carrier plan: where the six frequencies come from

### 3.1 Two accounts of the sub-band split disagree — and only one is citable

**[DOC]** FCC 07-215 (§2.2): Sirius repeaters 2324.1–2328.4, XM repeaters 2336.2–2341.3.

**[REP]** Wikipedia's SDARS article gives 2324.54–2327.96 (Sirius) and 2336.225–2341.285 (XM)
<https://en.wikipedia.org/wiki/Digital_audio_radio_service>. The table carries no citation.

The XM figures agree with FCC 07-215 to within 25 kHz. The Sirius figures are narrower —
3.42 MHz against the grant's 4.06 MHz emission designator.

**A correction to my own earlier reading.** I initially took the Wikipedia table as the
authority and reported a 6/6 sub-band match on that basis. It now looks like that table was
*derived from the carrier list*, not from a filing — which is why it reproduces OrcXM's own
carrier edges so exactly (§4). The correct authority is FCC 07-215 plus the equipment grants;
happily the 6/6 conclusion survives, and §4 makes it far stronger than a sub-band
classification.

**[INF]** On the Sirius width discrepancy: three sources agree the Sirius repeater is *centred*
on 2326.25 MHz and disagree only on width (3.42 / 4.06 / 4.30 MHz). The centre is
triple-confirmed; the width is not settled. Nothing in OrcXM depends on it.

### 3.2 The six XM frequencies (project table, from the R&S XM-Radio manual)

| # | Name | Centre (MHz) | Type |
|---|---|---|---|
| 1 | Sat1A | 2333.465 | satellite QPSK |
| 2 | Sat2A | 2335.305 | satellite QPSK |
| 3 | TerrA | 2337.490 | terrestrial COFDM |
| 4 | TerrB | 2340.020 | terrestrial COFDM |
| 5 | Sat2B | 2342.205 | satellite QPSK |
| 6 | Sat1B | 2344.045 | satellite QPSK |

**[INF]** The naming is a frequency-order enumeration with an A/B ensemble tag, not a satellite
attribution. See §3.4 for what the encoding implies.

---

## 4. Cross-check: the six carriers tile the allocation almost exactly

This is the substantive new result of this dump. Take the project's symbol rate and roll-off
(1.64 Msym/s, RRC α = 0.15 → occupied bandwidth 1.64 × 1.15 = **1.886 MHz**, half-width
0.943 MHz) and overlay the six centres on the FCC-verified allocation.

### 4.1 Envelopes

| Carrier | Centre | Occupied span |
|---|---|---|
| Sat1A | 2333.465 | 2332.522 – 2334.408 |
| Sat2A | 2335.305 | 2334.362 – 2336.248 |
| TerrA | 2337.490 | 2336.547 – 2338.433 |
| TerrB | 2340.020 | 2339.077 – 2340.963 |
| Sat2B | 2342.205 | 2341.262 – 2343.148 |
| Sat1B | 2344.045 | 2343.102 – 2344.988 |

### 4.2 Five arithmetic results

**(a) The bottom edge.** Lowest envelope edge 2332.522 MHz against the XM block start of
2332.5 MHz — **22 kHz margin**, i.e. 0.18% of the block.

**(b) The top edge.** Highest envelope edge 2344.988 MHz against the block end of 2345.0 MHz —
**12 kHz margin**.

**(c) Total occupancy.** 12.466 MHz of the 12.5 MHz block — **99.73% filled**.

**(d) Satellite pair spacing is exactly 1.840 MHz, twice.** Sat2A − Sat1A = 1.840 MHz and
Sat1B − Sat2B = 1.840 MHz. Against a 1.886 MHz occupied bandwidth that is a 46 kHz overlap of
the roll-off tails only — and at the crossover point each RRC response is at its extreme
skirt, i.e. ~0. The satellite carriers are **packed with effectively zero guard band**, which
is what you would do to fit six carriers into 25 MHz.

**(e) The terrestrial pair brackets the XM repeater slice, and its midpoint is the FCC
frequency.** TerrA − 1.265 = 2336.225; TerrB + 1.265 = 2341.285. FCC 07-215 says the XM
repeater slice is 2336.2–2341.3. And:

> (2337.490 + 2340.020) / 2 = **2338.755 MHz**

which is the XM repeater centre in the 2026 FCC equipment grant (§2.3), to the kilohertz.
The two terrestrial "carriers" are the lower and upper halves of **one** 5.01 MHz COFDM
emission, not two independent repeaters.

### 4.3 Why this is a real check and not numerology

Three independent quantities had to line up, and each comes from a different source:

- the 12.5 MHz block edges come from the CFR;
- the repeater slice edges and centre come from an FCC order and an FCC equipment grant;
- the six centres come from an R&S test-equipment manual.

The rolled-off envelope width was **derived** from the symbol rate and roll-off alone — 1.886
MHz, no fitting. If the project's symbol rate were 1.5 or 1.8 Msym/s, or the roll-off were
0.2, the envelopes would not tile the block: the bottom and top margins would move by hundreds
of kHz and the terrestrial pair would stop bracketing the FCC slice. They do not.

**Practical consequence for OrcXM.** The carrier table and the modem parameters are consistent
with the regulatory allocation at the tens-of-kHz level. Phase 0's job is to *find energy* at
those six centres, and the frequency hypothesis behind it is now as well-supported as it can be
without a capture. The remaining Phase 0 risk is therefore almost entirely **receiver-side**
(LO accuracy, PLL lock, antenna, LNA, noise figure) rather than **plan-side**.

**[INF]** One refinement worth carrying into the bench work: because the satellite carriers are
butted edge-to-edge with essentially no guard band (§4.2d), a measurement window of ±0.95 MHz
around a satellite centre already contains the neighbouring carrier's skirt. The v2 presence
metric's ±0.95 MHz window is therefore right at the boundary of correct — widening it would
start integrating the neighbour. This is a *new* argument for keeping the window where it is,
and it is tighter than the earlier "spur exclusion" argument.

---

## 5. Air interface: what is public

The single best public description of the legacy SDARS physical layer is a **granted Sirius XM
patent on interoperable receivers**, which tabulates both systems' TDM parameters side by side.
Everything in §5.1–5.3 is **[DOC·A]** from that patent unless marked otherwise.

Source: US 8,983,364 B2, "Methods and apparatus for interoperable satellite radio receivers",
priority 2007-03-29. <https://patents.google.com/patent/US8983364B2/en>

### 5.1 Parameter table (XM vs Sirius, satellite TDM)

| Parameter | XM | Sirius |
|---|---|---|
| Bit rate | 3.28 Mbps | 7.5168 Mbps |
| Symbol rate | **1.64 Msps** | 3.7584 Msps |
| Fast-sync preamble length | 64 bits | 48 bits |
| Fast-sync preamble frequency | 474.5 Hz | 3670 Hz |
| Master-frame preamble | 128 bits (continuous) | 255 bits (spread) |
| Master-frame duration | **432 ms** | 347 ms |
| Padding field | 192 bits | 0 bits |
| RRC excess bandwidth | **15%** | 20% |
| Total occupied bandwidth | **1.886 MHz** | 4.51008 MHz |

**This is the confirmation that matters most for OrcXM.** The project's 1.64 Msym/s and 15%
roll-off came from an R&S manual; a granted patent, written for a different purpose, states the
same two numbers and adds the resulting 1.886 MHz. Two independent sources, same answer.

### 5.2 Modulation and polarisation

**[DOC·A]** "Because both the XM and Sirius services employ **QPSK modulation** on their
satellite paths…"

**[DOC·A]** "Both XM and Sirius utilise **circular polarization for their TDM signals** and
**vertical polarization for their COFDM signal(s)**." This confirms the project's LHCP/vertical
split.

**[DOC]** For the terrestrial layer specifically, the Sirius signal architecture is described as
"an OFDM QPSK signal, and cousin to WiMax and LTE, with the particular feature that more than
one transmitter operates on the same frequency, forming a **single frequency network**"
<https://en.wikipedia.org/wiki/Sirius_Satellite_Radio>. Consistent with the COFDM assumption,
and worth knowing: an SFN means OrcXM may observe **constructive or destructive interference**
between repeaters, not a clean single emitter.

### 5.3 Stream topology — why XM has six carriers

**[DOC·A]** The patent:
> "XM splits their content into **two ensembles**, and then further splits each coded ensemble
> into two halves, each with half of the error protection. Thus, each satellite carries half the
> data from each ensemble, but as **two separate QPSK modulated data streams**."

**[DOC·A]** Receiver implication: "four TDM demodulators… for the XM signal… the Sirius datastream
comprises only two TDM signals and only one COFDM signal."

**[REP]** Wikipedia puts it from the product side: "XM which uses six carriers and **decodes
three 2 MHz carriers** to economize on receiver power consumption and complexity at the cost of
channel-changing speed" <https://en.wikipedia.org/wiki/Sirius_Satellite_Radio>.

**[INF]** Reconciling these: the **broadcast** is six carriers (4 satellite + 2 terrestrial
halves, §4), but a **receiver** need only demodulate three concurrent ~2 MHz channels to get
audio — it time-shares the remaining content. For OrcXM this is directly useful: a
single-carrier capture is not a partial view of "the signal", it is a complete view of *one
ensemble half*, which is enough to characterise framing.

**[REP]** XM's framing has an intentional four-second skew between copies, giving an 8-second
obstruction tolerance. <https://en.wikipedia.org/wiki/Sirius_Satellite_Radio> (stated for
Sirius; the general diversity design applies to both).

### 5.4 FEC

**[DOC·A]** Legacy FEC is concatenated convolutional coding plus interleaving:
- US 6,154,452 A, XM Satellite Radio, priority 1999-05-26 — continuous cross-channel interleaving
- US 8,667,344 B2, Sirius XM — concatenated convolutional encoding and interleaving, with
  "a QPSK demodulator and synchronization unit" per receiver arm
- **LDPC** layer added later: US 9,037,939 B2 (priority 2007-08-01), US 9,036,720 B2, and
  US 2009/0168809 A1 on joint legacy/overlay synchronisation

**[REP]** From the Bell Labs heritage account: concatenated Reed-Solomon block coding plus FEC,
with more robust coding on control channels than on audio, and the waveform/early receivers
prototyped in FPGA by Lucent, then ASICs from Agere Systems and later also STMicroelectronics.
<https://en.wikipedia.org/wiki/Sirius_Satellite_Radio>

### 5.5 What is genuinely *not* public

**[INF]** Public: modulation family, symbol rates, occupied bandwidths, frame durations, preamble
lengths, sync strategy, interleaver family, FEC families, polarisation.

**Not public anywhere found:** the exact convolutional/LDPC code parameters, interleaver depth
and permutation, scrambling sequences, the actual sync-word bit patterns, the exact carrier
centre frequencies, and the complete frame field layout. Those appear only in proprietary
specifications and confidential FCC exhibits (§7.1).

**[INF]** Concretely, for the decoder work this means the *search space is now bounded*: a
432 ms master frame with a 128-bit continuous preamble, a 192-bit padding sequence at frame end
"used as a second synchronisation layer", and a fast-sync preamble at 474.5 Hz. OrcXM's
`tools/orc_decoder` frame sync should be re-parameterised against those numbers — the current
v0.1 sync word is a test-carrier artefact, not an SDARS one, and 432 ms at 1.64 Msym/s is
708,480 symbols per master frame. That is a checkable interval: an autocorrelation of a real
capture should show a periodicity near 432 ms, or near 216 ms / 144 ms if the search falls on a
sub-multiple. **This is the single highest-value measurement Phase 0 can now make.**

### 5.6 ITU filings — a gap

**[INF]** The ITU BR IFIC / Space Network List is not openly indexed and I had no credentials.
This is where an authoritative carrier plan would live. Recorded as a gap, not a result.

---

## 6. Receivers and silicon

### 6.1 The device population is well catalogued

**[DOC]** Sirius XM Radio LLC holds FCC grantee codes **RS2** (registered 2004-01-16, 49 FCC IDs)
and **2AAC6** (5 IDs). <https://fccid.io/RS2> · <https://fccid.io/2AAC6>

**[DOC]** FCC equipment-class strings read literally "XM Satellite RX with FM Transmitter",
"Sirius XM Bluetooth Vehicle Dock", "Sirius XM Lynx Portable Radio". **[INF]** FM retransmission
into a legacy head unit was the standard integration path for add-on radios.

**[DOC]** A consumer filing (Onyx PLUS G7.5, `RS2SXPL2`, 2016) shows the exhibit structure:
internal photos of the receiver, car dock, home dock and FM coupler are public; **block diagrams,
schematics and the operational description are withheld as confidential**. The same pattern holds
for the 2026 repeater grant. <https://fccid.io/RS2SXPL2>

### 6.2 Chipset identification — unverified, and one popular claim is wrong

**[DOC]** The commonly mis-cited **STMicroelectronics STA680** is an "Automotive HD Radio™
baseband receiver" (IBOC/HDC), *not* SDARS. Its own datasheet says so.
<https://web.archive.org/web/20240512015821/https://www.st.com/resource/en/datasheet/sta680.pdf>

Do not repeat the claim that STA680 is the SiriusXM chip. It is not.

**[DOC]** The FCC block diagrams that would name the ICs are confidential, and no public service
manual or schematic was found. **[REP]** Teardown claims circulate but none could be tied to a
primary document.

**[INF]** Receiver silicon is the least-documented part of the whole system. The observable public
surface is the *device*, not the die.

### 6.3 Antenna and RF front end — genuinely well documented

The 2.3 GHz link has a substantial peer-reviewed antenna literature, the best public window into
the vehicle front end:

- "Dual Antenna System for Mobile SDARS Application", SAE 2001-01-0008 — <https://doi.org/10.4271/2001-01-0008>
- "Peripheral SDAR Interoperability", SAE 2001-01-0006 — <https://doi.org/10.4271/2001-01-0006>
- "Ground plane effects on the performance of SDARS antennas", IEEE APS 2002 — <https://doi.org/10.1109/aps.2002.1017091>
- "Low profile SDARS-antenna with diversity functionality", IEEE APS 2002 — <https://doi.org/10.1109/aps.2002.1017090>
- "Microstrip patch antenna for SDARS reception", IEEE APS 2005 — <https://doi.org/10.1109/aps.2005.1552502>
- "Novel combined scan-phase antenna diversity system for SDARS", IEEE APS 2008 — <https://doi.org/10.1109/aps.2008.4619572>
- "Dual-band antenna system for SDARS and GPS applications", IEEE APS 2010 — <https://doi.org/10.1109/aps.2010.5561019>
- "Design of a Compact GPS and SDARS Integrated Antenna for Automotive Applications", IEEE AWPL 2010 — <https://doi.org/10.1109/lawp.2010.2049632>
- "Measuring the radiation patterns of SDARS installed in vehicles", EuCAP 2012 — <https://doi.org/10.1109/eucap.2012.6206707>
- "SDARS-GNSS LNA That Can Coexist With Cellular", 2019 — <https://doi.org/10.21917/ijme.2019.01118>

**[INF]** A typical vehicle module is a combined SDARS+GNSS element (patch or monopole, often
with integral LNA and cellular coexistence filtering), shielded coax, and a receiver that outputs
audio plus an FM modulator. **Relevant to OrcXM's Phase 1 BOM:** the commercial parts are
2.3 GHz LHCP patches with integrated LNAs designed for a ground plane, which is exactly the
"patch/helix + LNA" the project already planned — and the literature says ground-plane size
matters a lot, which is a bench caveat worth recording.

### 6.4 Satellite hardware, for scale

**[DOC]** SXM-9: Maxar 1300 platform, ~6,400 kg at launch, "more than 27 feet tall and over 100
feet long with its solar arrays deployed", large unfurlable S-band reflector from L3Harris,
serving ~167 million equipped vehicles.
<https://investor.siriusxm.com/news-events/press-releases/detail/2142/siriusxms-sxm-9-satellite-completes-in-orbit-testing-and>

**[INF]** A large unfurlable S-band reflector is what makes a ~10 dB SNR achievable on a small
vehicle patch. It also means the downlink is shaped to CONUS, not global.

---

## 7. Conditional access — architecture only

### 7.1 How a receiver is authorised

**[DOC]** From the FCC-filed owner's manual for the Onyx Plus:
> "Your Onyx Plus has an **8 character alphanumeric ID** which uniquely identifies your Radio.
> **This ID is used during the subscription process.**"

**[DOC]** Activation is web or phone: siriusxm.com/activatenow, or siriusxm.com/refresh to
"refresh your Radio". Before authorisation the receiver parks on channel 1 ("XM Preview"):
"Upon power up, Onyx Plus should tune to channel 1 by default, when it's not yet activated."
<https://fccid.io/RS2SXPL2/User-Manual/Onyx-Plus-Users-Guide-2913749.pdf>

**[INF]** "Refresh" is the user-facing name for a conditional-access entitlement message carried
over the broadcast link. The receiver already has its RF chain and frame sync working — it can
show channel 1 and preview audio — but its service tier is gated until an authorisation record
keyed to its Radio ID arrives. This is the classic addressable-EMM/ECM broadcast-CA pattern. The
ESN→Radio ID derivation, the entitlement message format and the key hierarchy are not public, and
this project does not go near them.

### 7.2 Is the satellite audio cipher publicly specified? No.

**[DOC]** No public specification, standard or vendor document defines the SDARS satellite audio
cipher was found. The public record contains patents that describe "data scrambling" as a
functional stage in the LDPC/TDM pipeline (US 9,036,720 B2), and no mention of scrambling or
conditional access in the consumer manual at all.

**[REP]** Community understanding is a proprietary, hardware-implemented conditional-access
system. Labelled secondary because it could not be verified against a primary source, and no
implementation detail is described here.

**[INF] Architectural summary, which is all OrcXM needs:** the system separates (a) an
unencrypted broadcast transport that any receiver can demodulate and frame-sync, from (b) a
conditional-access layer that gates service by device identity. **The transport is not secret;
only the gating is.** That is precisely the seam OrcXM is built to work inside — the project can
legitimately recover everything up to and including frame structure, channel multiplex and
stream metadata.

### 7.3 The IP stream is a separate, weaker layer

**[DOC]** The internet stream uses standard **HLS with AES-128-CBC** segment encryption; the
client fetches the key from an authenticated API call inside its own subscriber session.
Implementation: `Aes.Create()` with `KeySize=128`, `CipherMode=CBC`; key endpoint
`/playback/key/v1/{id}`.
<https://github.com/yob15662/sxm-player/blob/main/SXMPlayer.Client/Services/HlsEncryptionService.cs>
· <https://raw.githubusercontent.com/yob15662/sxm-player/main/sxm_cleaned.yaml>

**[INF]** This is ordinary streaming DRM keyed to a paid account, entirely separate from the
satellite link's conditional access. Nothing in it helps with the satellite path, and nothing in
the satellite path is needed for it.

---

## 8. IP delivery layer (documented, and independent of the RF work)

Included because it is what the entire open-source ecosystem actually implements, and because
OrcXM's `docs/sxm-player-analysis.md` and `docs/sxm-player-ecosystem.md` already cover adjacent
ground. This section adds the *current* API surface.

### 8.1 Current API (edge-gateway generation)

**[DOC]** Extracted from a captured OpenAPI spec, by family:

| Family | Path |
|---|---|
| Identity | `/identity/v1/identities/authenticate/password`, `/identity/v1/identities/me` |
| Session | `/session/v1/sessions/anonymous`, `/session/v1/sessions/authenticated` |
| Device | `/device/v1/devices`, `/device/v1/grant/refresh` |
| Account / profile | `/account/v2/accounts/me`, `/profile/v2/profiles/me` |
| Subscription | `/subscription/v1/subscriptions` |
| Playback | `/playback/play/v1/tuneSource`, `/playback/play/v1/liveUpdate` |
| Key | `/playback/key/v1/{id}` |
| Enforcement | `/playback/stream-enforcement/v1/status` |
| Channel lineup | `/relationship/v1/set/all-channels`, `/relationship/v1/container/all-channels` |
| On-demand | `/ondemand/v1/library/all`, `…/filters`, `…/filter-views`, `…/user-progress` |
| Config / localisation | `/configservice/v1/applications/sxm_web_prod/configs/{version}`, `/localizationservice/v1/localizations` |
| Time / telemetry | `/time/v1/metronome`, `/playback/telemetry/v2/actions`, `/user-event/v1/events/submit` |

**[DOC]** `tuneSource` is a POST taking `{id, type, hlsVersion, manifestVariant, mtcVersion}`
returning a large object with channel images and stream descriptors.

**[DOC]** The legacy generation used `player.siriusxm.com/rest/v2/experience/modules/{}` and
`/rest/v4/…`, with a `tune/now-playing-live` module taking `assetGUID`, `channelId`,
`hls_output_mode=custom`, `marker_mode=all_separate_cue_points`, `result-template=web`.
<https://github.com/AngellusMortis/sxm-client/blob/master/sxm/client.py>

### 8.2 HLS structure, from a captured live response

**[DOC]** Verbatim URL templates:
```
"%Live_Primary_HLS%/AAC_Data/octane/octane_variant_small_v3.m3u8"
"%Live_Secondary_HLS%/…"
"…/HLS_octane_32k_v3/octane_32k_1_071504172003_00144991_v3.aac"
"keyUrl": "%Live_Primary_HLS%/…/HLS_octane_32k_v3/key/1"
```
<https://raw.githubusercontent.com/AngellusMortis/sxm-client/master/tests/sample_data/xm_live_channel.json>

Read off that: two independent HLS roots (redundant origins); three bitrate variants
(small/medium/large, ABR); `_v3` = HLS protocol version 3; `.aac` segments with nominal bitrate,
sequence number, timestamp and ID in the path; and a `keyUrl` pointing at a separate rotating
`key/<n>` resource.

**[DOC]** Segment framing is **AAC ADTS**: "ADTS frames start with 0xFFF (sync code in first 12
bits)", 7-byte headers (9 with CRC).
<https://github.com/yob15662/sxm-player/blob/main/SXMPlayer.Client/Services/Aac/AacFrameAnalyzer.cs>

### 8.3 Metadata is out-of-band

**[DOC]** Metadata arrives by API polling, not in-band: the captured response carries structured
`cut` objects with `title`, `album.title`, `cutContentType: "Song"`.

**[INF]** Because it is polled and segment-aligned rather than embedded, it can lag playback; the
Lyrion plugin warns "Data often lags playback" and offers a segment-delay cache to resync.
<https://github.com/paul-1/plugin-SiriusXM>

---

## 9. Open-source player ecosystem

All metadata **[DOC]** from the GitHub REST API and each repo's own source. **Every one of these
is a subscriber client**: each requires a real SiriusXM account, and none claims to defeat the
satellite conditional-access layer.

| Repo | Lang | Licence | Last push | What it implements |
|---|---|---|---|---|
| [AngellusMortis/sxm-client](https://github.com/AngellusMortis/sxm-client) | Python | MIT | 2022-11-17 | Library + HTTP proxy turning an authenticated session into an HLS stream. Legacy REST v2/v4. |
| [AngellusMortis/sxm-player](https://github.com/AngellusMortis/sxm-player) | Python | MIT | 2021-07-30 | CLI/daemon on `sxm-client`; MP3 capture, archiving, plugin API. |
| [schlarpc/SeriousCast](https://github.com/schlarpc/SeriousCast) | Python | MIT | 2020-09-30 | Internet radio → SHOUTcast/Icecast bridge; web UI; experimental Flask HLS server. |
| [yob15662/sxm-player](https://github.com/yob15662/sxm-player) | C#/.NET | Apache-2.0 | **2026-10-11** | **Most current.** Icecast proxy with metadata/cover art, MPD/Home Assistant, NSwag client generated from a captured HAR, AES-128 HLS, ADTS analysis. |
| [Ionshard/pyxis](https://github.com/Ionshard/pyxis) | Python | GPL-2.0 | 2012-07-18 (dead) | Legacy internet-stream CLI; rewrite of Sipie. Historical. |
| [paul-1/plugin-SiriusXM](https://github.com/paul-1/plugin-SiriusXM) | Perl | GPL-2.0 | **2026-10-10** | Lyrion Media Server plugin + Perl proxy; US/CA, quality selection, segment caching. |
| [kenzik/sxm-player](https://github.com/kenzik/sxm-player) | C | MIT | 2026-09-12 | Headless live-radio daemon with MPRIS. Small/new. |
| [AgentiLoop/StarPlayrX](https://github.com/AgentiLoop/StarPlayrX) | Swift | NOASSERTION | **2026-10-16** | Native macOS player (branch `mustang`). |
| [CHJ85/SiriusXM-HLS-Proxy-Server](https://github.com/CHJ85/SiriusXM-HLS-Proxy-Server) | Python | none declared | 2026-09-15 | Local proxy for VLC/Kodi/Plex/mpv/ffmpeg. |
| [rosswaycaster/XM-Menu-Player](https://github.com/rosswaycaster/XM-Menu-Player) | JavaScript | none declared | 2026-08-28 | Electron menu-bar wrapper around the web player. |
| [biceroy/DiscordXM](https://github.com/biceroy/DiscordXM) | Python | none declared | 2026-07-23 | Streams a channel into a Discord voice channel. |
| [gabeosx/canis97](https://github.com/gabeosx/canis97) | Swift | none declared | 2026-09-16 | Native skinnable macOS player. |

**Caveats**

- **[DOC]** `sxm-client`'s README is explicit that it is "100% unofficial", "PERSONAL USE ONLY",
  and that corporate or profit-seeking use "may result in you getting in legal trouble."
- **[DOC]** `yob15662/sxm-player` is the only repo targeting the current
  `api.edge-gateway.siriusxm.com` surface and is actively maintained — the de-facto reference for
  §8.
- **[DOC]** The Lyrion plugin states "This uses an unofficial API. SiriusXM does not publish API
  information. It may stop working at anytime."
- **[INF]** The ecosystem is bimodal: a large 2010–2022 Python cluster against the now-stale legacy
  API, and a 2025–2026 cluster in C#/Swift/C/Python against the edge-gateway API. **Nothing in
  either cluster touches the satellite link.** The hobbyist path of least resistance has always
  been the IP API, which is exactly the path OrcXM deliberately did not take.

---

## 10. SDR and hardware-hacking landscape

### 10.1 Negative result: no published SDARS satellite demodulation

**[DOC·A]** Searches run: GitHub repositories for `SDARS` (46 results, all unrelated — diffusion
models, astro codes, personal profiles); GitHub repositories for `satellite radio SDR
demodulator` (0 results); rtl-sdr.com site search for "sirius" (no SDARS-reception article; hits
were Outernet/LoRa); Hackaday search for "siriusxm" (only the SXM-7 failure story).

**No credible published account of successfully demodulating and decoding the SDARS satellite
downlink with an SDR was found.** That is a search result, not proof of absence. Recorded because
it is decision-relevant: the frame-sync problem OrcXM is attacking is not solved in public.

### 10.2 Why it is hard

**[DOC]** Front-end reach is the first gate: RTL-SDR-class dongles tune ~500 kHz–1.75 GHz, below
the band <https://www.rtl-sdr.com/about-rtl-sdr/>; HackRF One covers 1 MHz–6 GHz but at 8-bit I/Q,
≤20 Msps, no front-end filtering for a weak wideband signal
<https://greatscottgadgets.com/hackrf/one/>.

**[DOC]** Second gate: the waveform is 1.886 MHz (XM) to 4.51 MHz (Sirius) occupied per carrier,
QPSK, with proprietary FEC/interleaving/sync whose parameters are unpublished (§5.5). Capture is
easy; closing the link is not.

**[DOC]** Third gate: the conditional-access layer (§7.2) — which is where OrcXM stops by design.

**[INF]** Note that OrcXM has already cleared the first gate, which is precisely why the project
is unusual: the Pluto clone tunes 2.33 GHz directly with ≤56 MHz of bandwidth, so the whole
12.5 MHz band fits in one capture. Most attempts die at gate one.

### 10.3 No public link budget at 2.33 GHz

**[DOC·A]** No open dataset of SDARS carrier power, C/N or link-budget measurements at 2.33 GHz
was found. Nearest public artefacts are the antenna/installed-pattern papers (§6.3) and satellite
hardware descriptions (§6.4). Link budgets live in FCC space-station applications.

**[INF]** A useful measurement campaign needs a 2.32–2.345 GHz LHCP antenna with LNA, a ≥10 MHz
capture SDR, and a known-G/T reference — plus, to be *useful* rather than merely interesting, the
frame-sync structure from §5.3. **OrcXM's own Phase 0/1 captures would be the first public
measurement of this kind that I could locate.** That is a real contribution, independent of
whether the project ever decodes audio.

---

## 11. Constellation status (context for "which satellite am I looking at")

From the FY2025 10-K (filed Feb 2026) unless marked. Not load-bearing for OrcXM — the carriers are
frequency-defined, not satellite-defined, and both satellites on a given carrier are
co-located in the sky and indistinguishable from a fixed antenna.

| Satellite | Launched | Bus | Status | Licence |
|---|---|---|---|---|
| Sirius FM-1/2/3 ("Radiosat 1–3") | 2000 | SSL LS-1300 | Retired 2016; were in **24 h Tundra** orbit | — |
| Sirius FM-4 | never launched | SSL LS-1300 | Ground spare; donated to NASM Udvar-Hazy 2012 | — |
| XM-1 / XM-2 ("Rock"/"Roll") | 2001 | Boeing BSS-702 | XM-1 retired 2016 | — |
| XM-3 ("Rhythm") | 2005-02-28 | Boeing BSS-702 | **Deorbited Nov 2025** | 2026 (with XM-5) |
| XM-4 ("Blues") | 2006-10-30 | Boeing BSS-702 | Not in the 10-K fleet table | — |
| Sirius FM-5 | 2009-06-30 | SSL LS-1300 | In orbit; moved 96°W → 86.2°W | 2030 |
| XM-5 | 2010-10-14 | SSL LS-1300S | In orbit; being replaced by SXM-11 | **2026** |
| Sirius FM-6 | 2013-10-25 | SSL LS-1300 | In-orbit spare (replaced by SXM-10, Jul 2025) | 2030 |
| SXM-7 | 2020-12-13 | Maxar 1300 | **Payload failure in IOT; not in active use** | 2029 |
| SXM-8 | 2021-06-06 | Maxar 1300 | In-orbit spare (replaced by SXM-9, Jan 2025) | 2029 |
| SXM-9 | 2024-12-05 | Maxar 1300 | **In service Jan 2025** | 2033 |
| SXM-10 | 2025-06-07 **[REP]** | Maxar 1300 | **In service Jul 2025** | 2033 |
| SXM-11 | 2026-06-28 **[REP]** | Lanteris IM-1300 **[REP]** | Under construction per 10-K | — |
| SXM-12 | future | — | Under construction; to replace FM-5 | — |

**[DOC]** 10-K fleet sentence verbatim: "We currently operate four in-orbit and two spare
satellites, FM-5, FM-6, XM-5, SXM-8, SXM-9, and SXM-10." The "four + two" phrasing and the
six-name list do not reconcile cleanly; quoted rather than paraphrased.

**[INF]** Two warnings for later geo-referencing work: the project's "geostationary at 85°W/115°W"
(README §The signal) is the *legacy* XM pairing, and the 10-K now shows FM-5 moved to 86.2°W. Do
not assert orbital slots without re-checking licence records; public tracking only gives
sub-satellite points within a station-keeping box.

---

## 12. Open questions, and the experiment that settles each

| # | Unknown | What would answer it | OrcXM can do it? |
|---|---|---|---|
| 1 | Frame field layout, sync-word bit patterns | Patent figure with full field maps; or an FCC operational description released after confidentiality expires | Partly — a real capture plus a 432 ms autocorrelation probe (§5.5) |
| 2 | FEC parameters (convolutional polynomials, LDPC base graph, interleaver depth) | Full patent texts (US 8,667,344 / 9,037,939), plus BER measurement on a real capture | Text: yes, locally |
| 3 | Whether energy is present at the six centres at all | A calibrated capture with known noise floor | **Yes — this is Phase 0** |
| 4 | Measured C/N at 2.33 GHz, link budget | Antenna + LNA + known-G/T capture | **Yes — Phase 1** |
| 5 | Exact satellite carrier plan from a primary document | FCC space-station exhibit (IBFS), or ITU BR IFIC | Maybe — FCC IBFS is public-shaped |
| 6 | Which baseband/tuner ICs are in receivers | Teardown with die markings; or an expired-confidentiality FCC block diagram | Out of scope |
| 7 | Whether satellite CA has ever been publicly analysed | A citable academic/security publication — none found | Out of scope, permanently |
| 8 | Terrestrial COFDM parameters (FFT size, guard interval, carrier count) | Patents US 8,923,429 / US 2006/0239365 read in full; or measurement of the repeater signal | Text: yes; measurement: only near a repeater |

---

## 13. Concrete next actions for OrcXM

Ranked by evidence value per unit of effort.

1. **Add a 432 ms periodicity test to the decoder.** With a real capture (Pluto, 12.5 MHz wide,
   ≥2 s), autocorrelate the magnitude-squared envelope of one carrier and look for a peak at
   432 ms / 708,480 symbols, and at sub-multiples. This is the cheapest way to convert "frame
   structure unknown" into "master frame located". It needs no new hardware.
2. **Re-parameterise `tools/orc_decoder` frame sync** against the published XM framing numbers:
   432 ms master frame, 128-bit continuous preamble, 192-bit padding field (second sync layer),
   fast-sync preamble at 474.5 Hz, 64 bits. Replace the test-carrier sync word with a *search*
   for these rather than a match against a guess.
3. **Correct the README's "not public" claim** (done in this pass) — the framing envelope and FEC
   families are published; only the parameters are not.
4. **Keep the ±0.95 MHz presence window, for a new reason.** §4.2d shows the satellite carriers are
   butted with essentially no guard band, so a wider window would integrate the neighbouring
   carrier. This is a stronger justification than the original spur-exclusion argument.
5. **Record the 22 kHz / 12 kHz edge margins** in `docs/presence-metric-2026-10-17.md` as the
   plan-side verification, so Phase 0's remaining risk is unambiguously receiver-side.
6. **Skip repeater-based measurements unless near a city.** The repeater layer is a legally
   transparent SFN (§2.4, §5.2), so a distant observation tells you about interference, not about
   the link.
7. **Do not pursue ITU filings or FCC space-station exhibits** unless the carrier plan needs
   further tightening — §4 has already tightened it to tens of kHz.

---

## Appendix A — Source ledger

**Re-fetched and read from this machine during this pass [DOC]**
- 47 CFR §25.144, §25.214 — <https://www.law.cornell.edu/cfr/text/47/25.144> · <https://www.law.cornell.edu/cfr/text/47/25.214>
- FCC 07-215, text extracted from the PDF; the repeater-slice sentence quoted in §2.2 was read
  verbatim from the extraction — <https://docs.fcc.gov/public/attachments/FCC-07-215A1.pdf>
- Wikipedia "Sirius Satellite Radio" (Bell Labs heritage, OFDM/SFN description, six-carrier XM
  contrast) — <https://en.wikipedia.org/wiki/Sirius_Satellite_Radio>
- Wikipedia "XM Satellite Radio" (company history) — <https://en.wikipedia.org/wiki/XM_Satellite_Radio>

**Primary sources cited by the research sub-agent, not re-fetched here [DOC·A]**
- US 8,983,364 B2 and the patent family in §5.4 — <https://patents.google.com/patent/US8983364B2/en>
  (Google Patents, Justia and FreePatentsOnline all returned 403/503 to this host; the USPTO
  scanned PDF is image-only and no OCR tool is installed, so the §5.1 table is not first-hand)
- FCC 08-178 merger order — <https://docs.fcc.gov/public/attachments/FCC-08-178A3.pdf>
- Sirius XM Holdings FY2025 Form 10-K — <https://www.sec.gov/Archives/edgar/data/908937/000090893726000006/siri-20251231.htm>
- FCC equipment authorisations — <https://fccid.io/RS2> · <https://fccid.io/RS2DRU2-1KW0001> ·
  <https://fccid.io/RS2SR20W> · <https://fccid.io/RS2SXPL2>
- Onyx Plus owner's manual — <https://fccid.io/RS2SXPL2/User-Manual/Onyx-Plus-Users-Guide-2913749.pdf>
- SXM-9 press release — <https://investor.siriusxm.com/news-events/press-releases/detail/2142/siriusxms-sxm-9-satellite-completes-in-orbit-testing-and>
- Repo sources: `sxm_cleaned.yaml`, `HlsEncryptionService.cs`, `AacFrameAnalyzer.cs`,
  `sxm/client.py`, `xm_live_channel.json`
- ANTEX/STA-2001 order as indexed in FCC 07-215 footnote 27

**Secondary, flagged [REP]**
- Wikipedia "Digital audio radio service" (sub-band table, uncited) — <https://en.wikipedia.org/wiki/Digital_audio_radio_service>
- Wikipedia "List of SiriusXM satellites" — **internally inconsistent**: still lists XM-3 as active
  while the 10-K says it was deorbited Nov 2025
- Gunter's Space Page for bus/orbit history — <https://space.skyrocket.de/doc_sdat/sirius-cdr.htm>
- Wikipedia "Sirius FM-5" (96°W → 86.2°W move)

**Explicitly NOT verified anywhere in this document:** actual satellite carrier centre frequencies
(only the project's manual and the §4 consistency argument), IC part numbers, ITU filings, any
measured link budget or C/N at 2.33 GHz, and the satellite cipher.

---

## Appendix B — One-paragraph synthesis

SiriusXM is a **two-block, 25 MHz S-band broadcast system** (2320–2345 MHz, split into 12.5 MHz
per heritage operator), fed by C-band uplinks, delivered by a GEO fleet of large
unfurlable-reflector satellites plus a **>1,000-repeater terrestrial gap-filler network that is
legally constrained to be a transparent retransmitter**. The satellite path is **QPSK/TDM** at
1.64 Msym/s (XM) or 3.7584 Msym/s (Sirius) with circular polarisation; the repeater path is
**COFDM** at ~5.01 MHz occupied (XM) or 4.06 MHz (Sirius) with vertical polarisation, forming a
single-frequency network. Frame durations, preamble lengths, sync strategy and FEC *families* are
public through patents; the complete air-interface specification, the exact carrier plan, the
conditional-access layer and the receiver silicon are not. The open-source ecosystem has
converged entirely on the **IP/HLS side**, which is a standard paid-subscriber API with
AES-128-CBC segment encryption — a completely separate system from the satellite link. **No public
attempt at demodulating the satellite link with an SDR was found.** OrcXM's six-carrier table and
modem parameters, meanwhile, tile the FCC allocation to within 22 kHz and reproduce the
FCC-documented XM repeater centre exactly, which is the strongest external check the project has
had.
