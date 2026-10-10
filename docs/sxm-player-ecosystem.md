# SiriusXM Player Ecosystem — Comparative Investigation

**Date:** 2026-10-10
**Objective:** Survey the open-source SiriusXM player landscape (per Grok's
table) for stream-handling patterns useful to OrcXM's decode work —
HLS/AAC pipelines, metadata formats, channel organization.
**Boundary:** architecture and formats only. No auth, no streams fetched,
no decryption examined (SeriousCast's decrypt routines untouched).

## The five projects

### 1. AngellusMortis/sxm-client (Python, MIT) — Grok's pick, correctly

The foundational async library everything modern builds on. Cloned to
`~/workspace/review/sxm-client`.

- `SXMClientAsync`: `login()` → `channels()` → `get_playlist()` →
  `get_segment()`.
- **Key finding:** modern HLS uses **raw AAC segments**, not MPEG-TS.
  Playlists reference `.aac` files under `AAC_Data` paths; the client
  rewrites variant-playlist entries to full segment URLs and fetches
  raw bytes. ADTS framing all the way down.
- Session renewal on 403 (playlist and segment level).

### 2. AngellusMortis/sxm-player (Python, MIT) — the player on top

Built on sxm-client. Cloned to `~/workspace/review/sxm-player-py`.

- Pluggable player architecture (`players/base.py`, `players/cli.py`),
  worker model (`workers/hls.py`, `workers/archiver.py`,
  `workers/processor.py`).
- HLS worker drives FFmpeg for playback; archiver worker records
  streams to disk with song/show splitting.

### 3. schlarpc/SeriousCast (Python 3) — the older generation

SiriusXM → SHOUTcast bridge. Cloned to `~/workspace/review/SeriousCast`.
**From the older HLS era: MPEG-TS segments, not raw AAC.**

`mpegutils.py` (pure format parsing, no crypto) reveals the old
segment structure:

- **MPEG-TS, 188-byte packets. PID 768 = audio PES, PID 1024 =
  metadata PES.** PCR/OPCR in adaptation fields.
- **SiriusXM in-stream metadata format** (`parse_sxm_metadata`):
  packet starts with magic `0x0f`, then a type byte and element
  count; each element is length/index/value. Type `0xfe` carries
  UTF-8 strings — first three are the track info (title/artist).
- `create_id3` builds ID3v2.3 tags with the HLS timestamp
  (`com.apple.streaming.transportStreamTimestamp`), TIT2, TPE1.

This metadata format is directly reusable knowledge for stream
analysis — it's the *framing*, not the cipher.

### 4. Ionshard/pyxis (Python) — historical

Pre-merger-era CLI player (`ProviderUSA.py`, `ProviderCanada.py`,
`Sirius.py`). Ancient protocol, predates HLS entirely. Historical
interest only — documents that the IP API has been RE'd and
re-RE'd for ~20 years.

### 5. paul-1/plugin-siriusxm (Perl) — Lyrion/LMS integration

Thin LMS plugin wrapping a Perl proxy (`SiriusXM-Perl`) on port 9999.
Integration layer, not a distinct stream implementation. Not deeply
analyzed — nothing new underneath.

## What converges (and what it means for OrcXM)

1. **Tune flow is identical everywhere modern:** login → channel
   lineup → tune → HLS. The .NET player, sxm-client, and sxm-player
   all do this; only the API vintage differs.
2. **Two HLS eras:** TS segments (PID 768/1024, old) → raw AAC
   segments (new). Both ADTS-framed. If OrcXM's post-demux stream
   analysis ever needs AAC handling, the framing discipline is
   documented in two independent implementations.
3. **In-stream metadata format** (0x0f magic, typed elements) is the
   most directly reusable find — it's the *container*, fully
   separable from content encryption.
4. **Channel lineup** is always available as structured data
   (IDs/names/numbers) — the reference for identifying demuxed
   content later.

## Honest scope

None of this is the satellite TDM waveform. It doesn't advance frame
sync. What it gives OrcXM is the **stream layer**: how SiriusXM
packages channels → segments → metadata → audio frames on the IP
side, with two concrete, reusable format specs (ADTS/AAC handling,
SXM metadata framing). The satellite demux will produce its own
transport — but when it does, we'll recognize the shapes.
