# OrcXM Decoder (v0.1) — software side

**Status:** frame sync working end-to-end on lab carriers. Demodulation
is Erik's signal side; this module takes bits → frames.

## Layout

`tools/orc_decoder/`:
- `frame_sync.py` — sync-word correlator (`find_sync`), frame period
  estimation, frame extraction, counter-continuity verification.
- `pipeline.py` — decode pipeline: IQ file → demodulator → bits →
  frames. `set_demodulator(fn)` plugs in the real DSP;
  `ideal_demodulator` is a reference slicer for clean lab captures.

## Test carrier framing

`tools/gen_xm_test_carrier.py --framed` embeds:
- 32-bit sync word `0x1ACFFC1D`
- 16-bit frame counter (wraps at 65536)
- Configurable payload (`--frame-payload`, default 1024 bits)

Frame length = 1072 bits default. The counter gives frame-sync
verification a ground truth: drops = lost frames.

## Verified

Generate → decode → verify, all green:
- 304 sync words found, 0 missed
- Frame period exactly 1072 bits
- 303/303 frames pass sync + counter check, 0 drops

## What's next

- Real demodulator (RRC, timing, Costas) → `set_demodulator`
- TDM structure research → `demux.py`
- Soft-bit support in `frame_sync.py` when LLRs are available

## Blind sync search (v0.2)

`tools/orc_decoder/blind_sync.py` — for when we don't know the sync word.

Real XM's frame structure is unpublished. Given a demodulated bitstream
with no prior knowledge, blind search:
1. Finds candidate frame periods via autocorrelation
2. Recovers the sync pattern by entropy analysis (sync positions have
   ~zero entropy, data positions ~1 bit)

Verified on synthetic data: unknown 48-bit sync word in 2048-bit frames,
40 frames — recovered the period and the exact sync word with zero errors.
This is the tool we'll run on real XM captures to find the actual frame
structure.

## Transmit chain simulator (v0.3)

`tools/orc_decoder/xm_encoder.py` — full software transmit chain so the
decoder can be developed without waiting on hardware captures:

    payload → framing → convolutional FEC → block interleave →
    QPSK → RRC → channel (freq offset, phase noise, AWGN) → IQ

Returns IQ plus ground truth (original payload bits per frame) for
scoring the decoder. The FEC is a stand-in (XM's actual code is unknown)
— the point is testing the decoder against coded, interleaved, noisy
data with known answers.

## Patent-accurate XM frame simulator (v0.4)

`tools/orc_decoder/xm_frame.py` — implements the frame structure from
XM's own patents (US20080311845, US7653088):

- Master frame: 128-bit MFP + 205 × 6912-bit sub-frames + 192-bit PAD
  = 1,417,280 bits per 432 ms
- Sub-frame: 64-bit FSP + 6848 coded bits
- FEC: RS(255,223) outer + rate-1/3 K=7 convolutional inner
- QPSK at 1.64 Msps, RRC 0.15

The FSP/MFP/PAD bit patterns are stand-ins (unpublished); lengths and
repetition rates are exact per the patents. `blind_sync.find_xm_fsp()`
recovers the 64-bit FSP from the stream using the known 6912-bit period
— verified exact match on synthetic data.
