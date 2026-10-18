"""Re-score archived XM captures with the current metric.

Reads the Phase 0 spectra saved on 2026-10-10 (freqs/mean/maxhold) and
any outdoor_capture run (baseband/median_power), scores each published
carrier, and prints what changed against the SNR that was published in
summary.json.  Writes metrics-v2.json beside the captures unless
--dry-run is given.

Presence only: no demodulation, no transport work, no cipher.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import xm_metrics as m

BENCH = Path(__file__).resolve().parent

# capture stem -> (dial, published center, carrier name)
PHASE0 = {
    "sat2333": (2333, 2333.465, "Sat1A"),
    "sat2335": (2335, 2335.305, "Sat2A"),
    "terr2337": (2337, 2337.490, "TerrA"),
    "terr2340": (2340, 2340.020, "TerrB"),
    "sat2342": (2342, 2342.205, "Sat2B"),
    "sat2344": (2344, 2344.045, "Sat1B"),
}


def load_phase0(path: Path):
    """(baseband_hz, power, gain_tag) for a 2026-10-10 capture."""
    stem = path.stem
    parts = stem.split("-g")
    base = parts[0]
    gain = f"g{parts[1]}" if len(parts) > 1 else "agc"
    if base not in PHASE0:
        return None
    d = np.load(path)
    return d["freqs"].astype(np.float64), d["mean"].astype(np.float64), gain


def published_snr(path: Path) -> dict:
    if not path.exists():
        return {}
    runs = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
    return {r["label"]: r.get("snr_db") for r in runs if "snr_db" in r}


def rescore_phase0(folder: Path, published: dict) -> list[dict]:
    rows = []
    for path in sorted(folder.glob("*.npz")):
        loaded = load_phase0(path)
        if loaded is None:
            continue
        baseband, power, gain = loaded
        dial, center, carrier = PHASE0[path.stem.split("-g")[0]]
        score = m.score_carrier(dial, center, baseband, power)
        rows.append(
            {
                "capture": path.stem,
                "gain": gain,
                "carrier": carrier,
                "dial_mhz": dial,
                "center_mhz": center,
                "published_snr_db": published.get(path.stem),
                **{k: v for k, v in score.items() if k != "metrics_version"},
            }
        )
    return rows


def rescore_outdoor(path: Path) -> list[dict]:
    d = np.load(path)
    rows = []
    centers = d["centers"]
    for i, center in enumerate(centers):
        if not np.isfinite(center):
            continue
        dial = int(d["dials"][i])
        score = m.score_carrier(dial, float(center), d["baseband"], d["median_power"][i])
        rows.append(
            {
                "capture": f"{path.parent.name}[{i}]",
                "gain": int(d["gain"]) if "gain" in d.files else None,
                "carrier": str(d["labels"][i]),
                "dial_mhz": dial,
                "center_mhz": float(center),
                "published_snr_db": None,
                **{k: v for k, v in score.items() if k != "metrics_version"},
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="re-score archived XM captures")
    parser.add_argument("npz", nargs="*", help="capture.npz paths (default: Phase 0 folder)")
    parser.add_argument("--folder", default=str(BENCH / "phase0-2026-10-10"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows: list[dict] = []
    folder = Path(args.folder)
    if args.npz:
        for p in args.npz:
            path = Path(p)
            rows += rescore_outdoor(path) if path.name == "capture.npz" else []
    else:
        rows += rescore_phase0(folder, published_snr(folder / "summary.json"))

    if not rows:
        print("nothing to score")
        return 1

    print(f"metrics v{m.METRICS_VERSION}\n")
    head = (f"{'capture':14s} {'carrier':7s} {'published':>9s} {'v2 excess':>9s} "
            f"{'gate':>5s} {'tilt':>5s} {'spur':>5s} {'masks':>5s}  verdict")
    print(head)
    print("-" * len(head))
    for r in rows:
        pub = "-" if r["published_snr_db"] is None else f"{r['published_snr_db']:+.2f}"
        tilt = "-" if np.isnan(r["tilt_db"]) else f"{r['tilt_db']:.2f}"
        spur = "-" if np.isnan(r["spur_db"]) else f"{r['spur_db']:.2f}"
        print(f"{r['capture']:14s} {r['carrier']:7s} {pub:>9s} {r['excess_db']:+9.2f} "
              f"{r['threshold_db']:5.1f} {tilt:>5s} {spur:>5s} "
              f"{str(r['spur_masks_carrier']):>5s}  {r['verdict']}")

    masked = [r for r in rows if r["spur_masks_carrier"]]
    print(f"\n{len(rows)} scored, {len(masked)} had the carrier inside the spur exclusion"
          + (": " + ", ".join(r["capture"] for r in masked) if masked else ""))
    rises = [r for r in rows if r["verdict"] == "carrier-shaped rise"]
    print(f"carrier-shaped rises: {len(rises)}")

    if not args.dry_run and not args.npz:
        out = folder / "metrics-v2.json"
        payload = {
            "metrics_version": m.METRICS_VERSION,
            "note": "re-score of the archived spectra; presence only",
            "rows": rows,
        }
        out.write_text(json.dumps(payload, indent=2, default=float) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
