"""Carrier-presence metric for the XM band on the ESP32-S3.

Spectrum presence only: no demodulation, no transport work, no cipher.

Why v2 exists.  The 2026-10-10 metric scored a carrier window against
one scalar floor at |baseband| 4-7.5 MHz, and each of the following was
either a real defect or a claim that did not survive measurement:

* The six XM carriers are 1.84 MHz apart and about 1.89 MHz wide, so
  adjacent channels overlap, and a 16 MS/s window puts at most one of
  the two floor bands outside the band.  Masking the neighbours out of
  the floor was tried and dropped: the floor has 3586 bins, two
  overlapping neighbours occupy about a quarter of it, and the median
  stayed within 1.3 dB.  The estimator was already robust.
* Fitting a line to the one clean band and extrapolating across the
  dial was tried and rejected: it was off by -2.9 dB on three carriers
  and -27 dB on TerrB.
* The receiver's own spur sits on the dial at +4 to +7 dB over the
  floor, and the window discards +/-150 kHz of it.  A carrier tuned to
  its own dial therefore loses its middle bins.  This one is real and
  is fixed by tuning off-centre -- see `dial_plan()`.
* The response is not flat (~5 dB tilt measured at 2350 MHz), so the
  floor is kept symmetric about the dial, which cancels a linear tilt.

So v2 keeps the estimator and adds what the published table lacked: the
measured tilt, an adaptive rise threshold, the spur level, and an
explicit flag when the carrier sits in the spur exclusion.
"""

from __future__ import annotations

import numpy as np

METRICS_VERSION = 2

FS_HZ = 16_000_000.0
REF_LOW_HZ = 60_000.0
SPUR_HZ = 150_000.0
SMOOTH_HZ = 150_000.0
CARRIER_HALF_HZ = 950_000.0
FLOOR_INNER_HZ = 4_000_000.0
FLOOR_OUTER_HZ = 7_500_000.0
MASK_HALF_HZ = 1_050_000.0
MIN_FLOOR_BINS = 64
RISE_DB = 3.0
WIDTH_LO_MHZ = 1.2
WIDTH_HI_MHZ = 2.6

# R&S XM-Radio manual, Table 2-1.
XM_CENTERS_MHZ = (2333.465, 2335.305, 2337.490, 2340.020, 2342.205, 2344.045)
XM_CARRIER_MHZ = 1.89


def corrected_hz(dial_mhz: float, baseband_hz) -> np.ndarray:
    """True RF after the 2.33 GHz mirror and the 60 kHz-low reference."""
    return dial_mhz * 1e6 - np.asarray(baseband_hz, dtype=np.float64) + REF_LOW_HZ


def carrier_baseband_hz(dial_mhz: float, center_mhz: float) -> float:
    """Where a carrier at `center_mhz` lands on the raw baseband axis."""
    return -(center_mhz - dial_mhz) * 1e6 + REF_LOW_HZ


def smooth_db(power, bin_hz: float, width_hz: float = SMOOTH_HZ) -> np.ndarray:
    p = np.asarray(power, dtype=np.float64)
    width = max(1, int(round(width_hz / bin_hz)))
    if width % 2 == 0:
        width += 1
    kernel = np.ones(width) / width
    return 10.0 * np.log10(np.convolve(p, kernel, mode="same") + 1e-20)


def _width_mhz(flat, dist, spur, true_hz, center_hz, bin_hz) -> float:
    """Width of the 3 dB-above-baseline run that spans the carrier center."""
    search = dist <= 2_500_000.0
    idx = np.flatnonzero(search & ~spur & (flat >= RISE_DB))
    if not idx.size:
        return 0.0
    gap = max(1, int(0.4e6 / bin_hz))
    breaks = np.where(np.diff(idx) > gap)[0]
    starts = np.r_[idx[0], idx[breaks + 1]]
    ends = np.r_[idx[breaks], idx[-1]]
    center_bin = int(np.argmin(dist))
    for start, end in zip(starts, ends):
        spans = start <= center_bin <= end
        crossed = min(true_hz[start], true_hz[end]) <= center_hz <= max(
            true_hz[start], true_hz[end]
        )
        if spans or crossed:
            return abs(float(true_hz[end] - true_hz[start])) / 1e6
    return 0.0


def _verdict(excess_db: float, width_mhz: float) -> str:
    if excess_db < RISE_DB or width_mhz <= 0.0:
        return "no carrier-shaped rise"
    if WIDTH_LO_MHZ <= width_mhz <= WIDTH_HI_MHZ:
        return "carrier-shaped rise"
    if width_mhz < WIDTH_LO_MHZ:
        return "narrow rise"
    return "broad rise"


def score_carrier_v1(dial_mhz: float, center_mhz: float, baseband, median_power) -> dict:
    """The 2026-10-10 metric: one scalar floor, no tilt fit, no masking.

    Kept so a re-score can be compared against what was published. New
    captures should use score_carrier().
    """
    bb = np.asarray(baseband, dtype=np.float64)
    bin_hz = abs(float(bb[1] - bb[0]))
    db = smooth_db(median_power, bin_hz)
    true_hz = corrected_hz(dial_mhz, bb)
    center_hz = float(center_mhz) * 1e6
    dist = np.abs(true_hz - center_hz)
    spur = np.abs(bb) < SPUR_HZ
    floor = (np.abs(bb) >= FLOOR_INNER_HZ) & (np.abs(bb) <= FLOOR_OUTER_HZ)
    window = (dist <= CARRIER_HALF_HZ) & ~spur
    if not np.any(window) or not np.any(floor):
        return {"excess_db": float("nan"), "width_mhz": 0.0, "verdict": "unscored"}
    floor_db = float(np.median(db[floor]))
    excess = float(np.median(db[window]) - floor_db)
    width = _width_mhz(db - floor_db, dist, spur, true_hz, center_hz, bin_hz)
    return {
        "excess_db": excess,
        "width_mhz": width,
        "floor_db": floor_db,
        "floor_bins": int(floor.sum()),
        "verdict": _verdict(excess, width),
    }


def _floor_band(bb, true_hz):
    """Symmetric off-band floor, |baseband| 4-7.5 MHz, no masking."""
    band = (np.abs(bb) >= FLOOR_INNER_HZ) & (np.abs(bb) <= FLOOR_OUTER_HZ)
    return band & (bb < 0), band & (bb > 0)


def score_carrier(dial_mhz: float, center_mhz: float, baseband, median_power) -> dict:
    """Score one published carrier and report how good the number is.

    The estimator is the 2026-10-10 one -- median of the carrier window
    against the median of the symmetric |baseband| 4-7.5 MHz floor.  It
    was kept after measurement, not by default: against the six archived
    captures it recovers an injected 3-12 dB plateau within 1.3 dB, and
    it stays within 1.3 dB with one or two neighbouring carriers at
    +10 dB inside the floor band, because the floor has 3586 bins and
    two overlapping neighbours occupy about a quarter of it.

    What is new is the reporting, which the published table lacked:
    `tilt_db` (how far the two floor halves disagree), `threshold_db`
    (raised to match that disagreement), `spur_db`, and
    `spur_masks_carrier`, which is true when the carrier sits inside the
    +/-150 kHz spur exclusion and therefore loses its middle bins.
    `dial_plan()` exists so that flag never has to be true.
    """
    bb = np.asarray(baseband, dtype=np.float64)
    bin_hz = abs(float(bb[1] - bb[0]))
    db = smooth_db(median_power, bin_hz)
    true_hz = corrected_hz(dial_mhz, bb)
    center_hz = float(center_mhz) * 1e6
    dist = np.abs(true_hz - center_hz)

    spur = np.abs(bb) < SPUR_HZ
    lower, upper = _floor_band(bb, true_hz)
    floor = lower | upper
    window = (dist <= CARRIER_HALF_HZ) & ~spur
    carrier_bb = carrier_baseband_hz(dial_mhz, center_mhz)

    out = {
        "excess_db": float("nan"),
        "width_mhz": 0.0,
        "verdict": "unscored",
        "floor_db": float("nan"),
        "floor_bins": int(floor.sum()),
        "floor_lower_bins": int(lower.sum()),
        "floor_upper_bins": int(upper.sum()),
        "tilt_db": float("nan"),
        "threshold_db": RISE_DB,
        "spur_db": float("nan"),
        "spur_masks_carrier": bool(abs(carrier_bb) < SPUR_HZ),
        "metrics_version": METRICS_VERSION,
    }
    if not np.any(window) or floor.sum() < MIN_FLOOR_BINS:
        return out

    floor_db = float(np.median(db[floor]))
    out["floor_db"] = floor_db
    if np.any(spur):
        out["spur_db"] = float(np.max(db[spur]) - floor_db)
    if lower.sum() >= MIN_FLOOR_BINS and upper.sum() >= MIN_FLOOR_BINS:
        tilt = abs(float(np.median(db[upper]) - np.median(db[lower])))
        out["tilt_db"] = tilt
        # A rise below the floor's own side-to-side disagreement is not
        # evidence of a carrier.
        out["threshold_db"] = max(RISE_DB, tilt)

    flat = db - floor_db
    out["excess_db"] = float(np.median(flat[window]))
    out["width_mhz"] = _width_mhz(flat, dist, spur, true_hz, center_hz, bin_hz)
    if out["excess_db"] < out["threshold_db"]:
        out["verdict"] = "no carrier-shaped rise"
    else:
        out["verdict"] = _verdict(out["excess_db"], out["width_mhz"])
    return out


def clean_floor_bins(dial_mhz: float, n: int = 8192) -> tuple[int, int]:
    """Clean floor bins in each |baseband| 4-7.5 MHz band for this dial."""
    bb = np.linspace(-FS_HZ / 2, FS_HZ / 2, n, endpoint=False)
    true_hz = corrected_hz(dial_mhz, bb)
    masked = np.zeros(bb.shape, dtype=bool)
    for c in XM_CENTERS_MHZ:
        masked |= np.abs(true_hz - c * 1e6) < MASK_HALF_HZ
    band = (np.abs(bb) >= FLOOR_INNER_HZ) & (np.abs(bb) <= FLOOR_OUTER_HZ) & ~masked
    lower = band & (bb < 0)
    upper = band & (bb > 0)
    return int(lower.sum()), int(upper.sum())


def dial_plan(min_offset_mhz: float = 2.0, max_offset_mhz: float = 3.5) -> list[dict]:
    """Integer dials that keep each carrier clear of the centre spur.

    The spur sits on the dial and is +4 to +7 dB over the floor, so a
    carrier tuned onto its own dial is masked.  Among the dials that
    leave a 2.0-3.5 MHz offset, pick the one with the most clean floor
    bins to fit the baseline on.
    """
    plan = []
    for i, center in enumerate(XM_CENTERS_MHZ):
        best = None
        for dial in range(int(np.floor(center)) - 4, int(np.ceil(center)) + 5):
            offset = abs(dial - center)
            if not min_offset_mhz <= offset <= max_offset_mhz:
                continue
            lo, hi = clean_floor_bins(dial)
            key = (lo + hi, -offset)
            if best is None or key > best[0]:
                best = (key, dial, offset, lo, hi)
        _, dial, offset, lo, hi = best
        plan.append(
            {
                "carrier": ("Sat1A", "Sat2A", "TerrA", "TerrB", "Sat2B", "Sat1B")[i],
                "center_mhz": center,
                "dial_mhz": dial,
                "offset_mhz": offset,
                "baseband_mhz": carrier_baseband_hz(dial, center) / 1e6,
                "floor_bins": lo + hi,
                "spur_clear_mhz": offset,
            }
        )
    return plan
