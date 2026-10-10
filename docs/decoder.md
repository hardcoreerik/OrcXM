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
