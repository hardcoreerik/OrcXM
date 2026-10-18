"""Score the archived Phase 0 spectra with v1 and v2, with a known hump added.

The point is the metric, not the sky.  Each archived capture is real
measured noise and receiver tilt; a flat-topped plateau 1.89 MHz wide is
injected at the position the inversion model says the carrier lands, at
a known level.  A good metric returns that level and returns ~0 when
nothing is added.  v1 is the metric that produced the published table.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

import xm_metrics as m

BENCH = Path(__file__).resolve().parent
PHASE0 = BENCH / "phase0-2026-10-10"

CAPTURES = (
    ("sat2333", 2333, 2333.465, "Sat1A"),
    ("sat2335", 2335, 2335.305, "Sat2A"),
    ("terr2337", 2337, 2337.490, "TerrA"),
    ("terr2340", 2340, 2340.020, "TerrB"),
    ("sat2342", 2342, 2342.205, "Sat2B"),
    ("sat2344", 2344, 2344.045, "Sat1B"),
)
AMPLITUDES_DB = (0.0, 3.0, 6.0, 9.0, 12.0)


def inject(baseband, power, dial, center, amplitude_db):
    if amplitude_db == 0.0:
        return power
    xc = m.carrier_baseband_hz(dial, center)
    inside = np.abs(baseband - xc) <= m.XM_CARRIER_MHZ / 2.0 * 1e6
    factor = 10.0 ** (amplitude_db / 10.0) - 1.0
    return power * (1.0 + factor * inside)


def main() -> int:
    rows = []
    print(f"metrics v{m.METRICS_VERSION}; plateau {m.XM_CARRIER_MHZ} MHz wide, "
          f"injected at the mirrored carrier position\n")
    header = f"{'carrier':7s} {'inj dB':>6s} {'v1':>7s} {'v1 err':>7s} {'v2':>7s} {'v2 err':>7s} {'width':>6s} {'verdict':>22s}"
    print(header)
    print("-" * len(header))
    for name, dial, center, label in CAPTURES:
        path = PHASE0 / f"{name}.npz"
        if not path.exists():
            print(f"{label:7s} missing {path.name}")
            continue
        d = np.load(path)
        baseband = d["freqs"].astype(np.float64)
        power = d["mean"].astype(np.float64)
        for amp in AMPLITUDES_DB:
            p = inject(baseband, power, dial, center, amp)
            v1 = m.score_carrier_v1(dial, center, baseband, p)
            v2 = m.score_carrier(dial, center, baseband, p)
            rows.append(
                dict(carrier=label, injected_db=amp, v1=v1["excess_db"], v2=v2["excess_db"])
            )
            print(
                f"{label:7s} {amp:6.1f} {v1['excess_db']:7.2f} {v1['excess_db'] - amp:7.2f} "
                f"{v2['excess_db']:7.2f} {v2['excess_db'] - amp:7.2f} {v2['width_mhz']:6.2f} "
                f"{v2['verdict']:>22s}"
            )

    v1_err = np.array([r["v1"] - r["injected_db"] for r in rows])
    v2_err = np.array([r["v2"] - r["injected_db"] for r in rows])
    print(f"\nv1 error: mean {v1_err.mean():+.2f} dB, rms {np.sqrt((v1_err**2).mean()):.2f} dB, "
          f"worst {np.abs(v1_err).max():.2f} dB")
    print(f"v2 error: mean {v2_err.mean():+.2f} dB, rms {np.sqrt((v2_err**2).mean()):.2f} dB, "
          f"worst {np.abs(v2_err).max():.2f} dB")

    blank = [r for r in rows if r["injected_db"] == 0.0]
    worst_blank = max(abs(r["v2"]) for r in blank)
    print(f"v2 on un-injected spectra: max |excess| {worst_blank:.2f} dB")

    if worst_blank >= m.RISE_DB:
        return 1
    rc = neighbour_test()
    rc |= spur_test()
    return rc

def neighbour_test() -> int:
    """Does a strong neighbouring carrier corrupt the floor?

    Masked-floor scoring should ignore it; the v1 floor band contains it.
    Only pairs where the neighbour really falls inside the unmasked floor
    band are run, and the test says which those are.
    """
    print("\nneighbour contamination: target at +6 dB, neighbour at +10 dB")
    print("(only pairs whose neighbour lands in the unmasked v1 floor band)\n")
    header = f"{'capture':9s} {'target':7s} {'neighbour':9s} {'v1 err':>7s} {'v2 err':>7s} {'spur':>6s}"
    print(header)
    print("-" * len(header))
    errs = []
    for name, dial, center, label in CAPTURES:
        path = PHASE0 / f"{name}.npz"
        if not path.exists():
            continue
        d = np.load(path)
        baseband = d["freqs"].astype(np.float64)
        power = d["mean"].astype(np.float64)
        true_hz = m.corrected_hz(dial, baseband)
        lower, upper = m._floor_band(baseband, true_hz)
        unmasked = lower | upper
        for other in m.XM_CENTERS_MHZ:
            if other == center:
                continue
            occ = np.abs(true_hz - other * 1e6) < m.XM_CARRIER_MHZ / 2.0 * 1e6
            if (occ & unmasked).sum() < 64:
                continue
            p = inject(baseband, power, dial, center, 6.0)
            p = inject(baseband, p, dial, other, 10.0)
            v1 = m.score_carrier_v1(dial, center, baseband, p)
            v2 = m.score_carrier(dial, center, baseband, p)
            e1, e2 = v1["excess_db"] - 6.0, v2["excess_db"] - 6.0
            errs.append((e1, e2))
            neigh = [n for n, c in zip(("Sat1A", "Sat2A", "TerrA", "TerrB", "Sat2B", "Sat1B"),
                                       m.XM_CENTERS_MHZ) if c == other][0]
            print(f"{name:9s} {label:7s} {neigh:9s} {e1:+7.2f} {e2:+7.2f} "
                  f"{str(v2['spur_masks_carrier']):>6s}")
    if not errs:
        print("no contaminating neighbour pairs in this dataset")
        return 0
    e1 = np.array([x[0] for x in errs])
    e2 = np.array([x[1] for x in errs])
    print(f"\nv1 worst error {np.abs(e1).max():.2f} dB, v2 worst error {np.abs(e2).max():.2f} dB")
    # v2 keeps the same estimator, so it must not regress against v1.
    return 0 if np.abs(e2).max() <= np.abs(e1).max() + 0.5 else 1


def spur_test() -> int:
    """The one defect measurement did support: carriers tuned onto the spur."""
    print("\nspur exclusion: nearest integer dial vs the off-centre plan")
    print(f"{'carrier':7s} {'center':>8s} {'old':>5s} {'offset':>7s} {'masked':>7s} "
          f"{'plan':>5s} {'offset':>7s} {'masked':>7s}")
    ok = True
    for p, item in zip(m.dial_plan(), CAPTURES):
        _, old_dial, center, label = item
        # geometry only: recompute where the carrier lands on each dial
        old_flag = abs(m.carrier_baseband_hz(old_dial, center)) < m.SPUR_HZ
        new_flag = abs(m.carrier_baseband_hz(p["dial_mhz"], center)) < m.SPUR_HZ
        ok &= not new_flag
        print(f"{label:7s} {center:8.3f} {old_dial:5d} {abs(old_dial - center):7.3f} "
              f"{str(old_flag):>7s} {p['dial_mhz']:5d} {p['offset_mhz']:7.3f} {str(new_flag):>7s}")
    print("\nplan keeps every carrier out of the spur: " + ("yes" if ok else "NO"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
