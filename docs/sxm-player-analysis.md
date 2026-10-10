# SiriusXM Player Analysis — REA-Directed

**Date:** 2026-10-10
**Objective:** Map the architecture of a Linux SiriusXM player to inform
OrcXM's stream-analysis work (channel organization, stream acquisition,
metadata) — without touching encryption or access controls.

## Target

- **yob15662/sxm-player** — .NET 8, Apache 2.0 licensed, SiriusXM
  streaming proxy built for headless Linux. Presents as an
  Icecast-compatible server so MPD/VLC/etc. can play SiriusXM channels.
- Cloned to `~/workspace/review/sxm-player` (shallow).

## Method — and the boundary

- **REA:** `rea analyze` was run against the repo (its JS analyzer —
  limited value for C# source). REA's managed (.NET) analysis needs
  compiled assemblies plus the dotnet SDK; neither is available here,
  so the deep work below is direct static source analysis, REA-directed
  and evidence-first.
- **Boundary (hard):** architecture mapping only. No authentication
  performed, no streams fetched, no decryption examined —
  `HlsEncryptionService.cs` was deliberately not opened. The project's
  encryption wall stands.

## Architecture

Two halves:

- **SXMPlayer.Client** — the SiriusXM API client: session management
  (`APISession.cs`, `SxmSessionService.cs`), channel lineup
  (`MetadataService.cs`), stream tuning (`StreamTuner.cs`,
  `PlaylistService.cs`), Icecast output (`IcecastStreamer.cs`).
- **SXMPlayer.Proxy** — the Icecast-compatible server front end
  (`Program.cs`, `Services/`, `wwwroot/`).

## API surface

From `sxm_cleaned.yaml` — an OpenAPI 3.0 spec of SiriusXM's public API,
extracted from their web client (10,202 lines). Base:
`https://api.edge-gateway.siriusxm.com/`. All 25 endpoints:

```
/configservice/v1/applications/sxm_web_prod/configs/{version}
/time/v1/metronome
/device/v1/grant/refresh
/subscription/v1/subscriptions
/account/v2/accounts/me
/profile/v2/profiles/me
/identity/v1/identities/me
/ondemand/v1/library/user-progress
/page/v1/page/library/{id}
/ondemand/v1/library/all
/localizationservice/v1/localizations
/ondemand/v1/library/filters
/ondemand/v1/library/filter-views
/playback/play/v1/tuneSource
/playback/telemetry/v2/actions
/playback/key/v1/{id}
/playback/stream-enforcement/v1/status
/playback/play/v1/liveUpdate
/user-event/v1/events/submit
/relationship/v1/container/all-channels
/relationship/v1/set/all-channels
/session/v1/sessions/anonymous
/identity/v1/identities/authenticate/password
/session/v1/sessions/authenticated
/device/v1/devices
```

The interesting ones for stream analysis: `tuneSource` (resolve a
channel to playable streams), `all-channels` (full channel lineup with
IDs/names/numbers), `liveUpdate`.

## Tune flow (StreamTuner.cs)

1. Login if the session needs it.
2. Fetch the channel list via the metadata service.
3. Match the requested channel by entity ID.
4. Call `tuneSource` with the channel ID, `HlsVersion: "V3"`, and
   `manifestVariant: "FULL"` — or `"WEB"` for `channel-linear` type
   channels.
5. The response carries the HLS stream URLs.

## Delivery pipeline

- HLS version 3, AAC segments.
- The proxy re-serves segments as an Icecast stream with ICY metadata
  injected at `icy-metaint: 8162`.
- `docs/aac-frame-logic.md` documents the ADTS framing discipline:
  sync-word (`0xFFF`) detection, frame-length parsing, metadata
  injected at exact byte intervals or FAAD/MPD desyncs
  (`PCE shall be the first element in a frame`, etc.). Useful
  reference for any AAC handling later.

## Relevance to OrcXM — honest assessment

- This is the **IP-delivery side** (internet HLS), not the satellite
  TDM waveform. It does **not** advance frame-sync or demux RE
  directly.
- What it does give us:
  - **Channel lineup reference** — IDs, names, numbers for every
    channel, useful when identifying demuxed satellite content later.
  - **Stream organization model** — how SiriusXM structures
    channels → streams → segments → metadata.
  - **AAC/ADTS framing knowledge** — directly reusable if the
    satellite audio pipeline ever needs it (it won't, pre-decryption —
    but the framing discipline is good hygiene for any stream work).
- Nothing here crosses the encryption boundary. The satellite work
  (frame sync → demux → stream analysis, stopping at the cipher)
  continues unchanged.
