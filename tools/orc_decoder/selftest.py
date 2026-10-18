#!/usr/bin/env python3
"""Self-test for the OrcXM demodulator, channel model and frame synchroniser.

Run this before trusting any demodulator result:

    python tools/orc_decoder/selftest.py

Exit code 0 means every gate passed.  The gates exist because this code was
previously validated only against a loop-cable test carrier, where the
carrier offset, the symbol timing and the sample clock were all exactly
zero by construction.  Each case below breaks one of those.

The final case is the important one: pure noise must yield **no** frames.
A marker search with errors tolerated matches noise regularly, and a
pipeline that reports frames on noise will happily report them on a real
capture too.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gen_xm_test_carrier as gen  # noqa: E402
from orc_decoder import channel, demod, frame_sync, pipeline  # noqa: E402

SYM_RATE = 1.64e6
SPS = 4
FRAME_PAYLOAD = 1024
FRAME_BITS = 32 + 16 + FRAME_PAYLOAD
ACQ_BITS = 2000          # symbols the loops are allowed to settle over
MAX_ROUNDS = 500

_failures = []


def check(name, ok, detail):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: {detail}")
    if not ok:
        _failures.append(name)


def derotate90(bits, quarter_turns, swap=False):
    """Undo a whole number of 90 degree lock quadrants; see rotate_bits."""
    return frame_sync.rotate_bits(bits, quarter_turns=quarter_turns, swap=swap)


def align_ber(rx_bits, tx_bits, skip_bits=ACQ_BITS, max_shift=64, min_bits=2000):
    """Best BER over the lock quadrants, I/Q reflection and a timing shift.

    Returns ``(ber, quarter_turns, swap, shift)``; ``bb[i]`` is compared against
    ``tx[i - shift]``.  The loop's own lock report says nothing about which of
    its four stable equilibria it chose, so the harness has to search them.
    """
    best = (1.0, 0, False, 0)
    for swap in (False, True):
        for k in range(4):
            bb = derotate90(rx_bits, k, swap)
            for sh in range(-max_shift, max_shift + 1):
                i0 = max(0, sh, skip_bits)
                i1 = min(len(bb), len(tx_bits) + sh)
                if i1 - i0 < min_bits:
                    continue
                err = float(np.mean(bb[i0:i1] != tx_bits[i0 - sh:i1 - sh]))
                if err < best[0]:
                    best = (err, k, swap, sh)
    return best


def run_case(label, iq, bits, imp, *, max_ber, max_evm=None):
    impaired, truth = channel.apply(iq, **imp)
    r = demod.qpsk_demod(impaired)
    ber, quarter_turns, swap, shift = align_ber(r["bits"], bits)
    detail = (f"ber={ber:.2e} evm={r['evm_pct']:.2f}% "
              f"cfo_est={r['cfo_hz_est']:+.1f}Hz drift={r['timing_drift_ppm']:+.2f}ppm")
    ok = ber <= max_ber
    if max_evm is not None:
        ok = ok and r["evm_pct"] <= max_evm
    check(label, ok, detail + f" (limit ber<={max_ber:.0e})")
    return r, ber, truth


CASES = [
    # label, impairments, max BER
    ("clean", {}, 0.0),
    ("cfo +60 kHz", {"cfo_hz": 60e3}, 0.0),
    ("cfo -60 kHz", {"cfo_hz": -60e3}, 0.0),
    ("cfo +150 kHz", {"cfo_hz": 150e3}, 0.0),
    ("phase 45 deg (exact null)", {"phase_deg": 45.0}, 0.0),
    ("timing 0.40 symbol", {"timing_off_symbols": 0.40}, 0.0),
    ("timing 0.75 symbol", {"timing_off_symbols": 0.75}, 0.0),
    ("clock 20 ppm", {"ppm": 20.0}, 0.0),
    ("clock -25 ppm", {"ppm": -25.0}, 0.0),
    ("snr 20 dB (Es/N0 26.0)", {"snr_db": 20.0}, 0.0),
    ("snr 12 dB (Es/N0 18.0)", {"snr_db": 12.0}, 0.0),
    ("snr 8 dB (Es/N0 14.0)", {"snr_db": 8.0}, 1e-4),
    ("snr 6 dB (Es/N0 12.0)", {"snr_db": 6.0}, 5e-3),
    ("worst case: 60 kHz + 0.4 sym + 20 ppm + 10 dB",
     {"cfo_hz": 60e3, "timing_off_symbols": 0.40, "ppm": 20.0, "snr_db": 10.0}, 1e-3),
]


def main():
    print("OrcXM decoder self-test")
    print(f"  reference: {SYM_RATE/1e6:.2f} Msym/s, RRC 0.15, {SPS} samples/symbol, "
          f"frame {FRAME_BITS} bits\n")

    iq, bits = gen.build(duration=0.05, framed=True, seed=1, sym_rate=SYM_RATE,
                         sps=SPS, frame_payload=FRAME_PAYLOAD)
    iq_if, bits_if = gen.build(duration=0.05, framed=False, seed=2,
                               sym_rate=SYM_RATE, sps=SPS)

    # --- 1. open-loop sanity: the matched filter and bit mapping are right -----
    print("1. reference path (open loop)")
    mf = demod.matched_filter(iq)
    best_ph, best_evm = None, 1e9
    for ph in range(SPS):
        e = demod._evm_pct(mf[ph::SPS][:8000])
        if e < best_evm:
            best_ph, best_evm = ph, e
    check("matched-filter EVM floor", best_evm < 6.0,
          f"best phase {best_ph}, evm={best_evm:.2f}% (RRC span 10 floors this at ~4%)")

    # --- 2. impairment sweep ---------------------------------------------------
    print("\n2. impairment sweep (steady state, first "
          f"{ACQ_BITS} bits excluded)")
    for label, imp, limit in CASES:
        run_case(label, iq_if, bits_if, imp, max_ber=limit)

    # --- 3. estimator accuracy -------------------------------------------------
    print("\n3. estimator accuracy")
    for cfo in (20e3, 60e3, -60e3, 150e3):
        y, _ = channel.apply(iq, cfo_hz=cfo)
        r = demod.qpsk_demod(y, max_symbols=20000)
        err = abs(r["cfo_hz_est"] - cfo)
        check(f"cfo estimate {cfo/1e3:+.0f} kHz", err < 100.0,
              f"estimate {r['cfo_hz_est']:+.1f} Hz, error {err:.1f} Hz")

    r = demod.qpsk_demod(channel.apply(iq, ppm=20.0)[0], max_symbols=20000)
    check("clock drift read-out", abs(r["timing_drift_ppm"] - 20.0) < 5.0,
          f"fitted {r['timing_drift_ppm']:+.2f} ppm against 20 ppm injected")

    # --- 3b. 45 degree false-lock detector ------------------------------------
    print("\n3b. QPSK Costas false lock at 45 degrees")
    # A decision-directed Costas loop has an unstable equilibrium at 45 deg
    # where its detector reads zero, so whether it settles there depends on
    # perturbing effects. Test the detector directly on a known rotation
    # rather than depending on where a loop happens to come to rest.
    srng = np.random.default_rng(11)
    synth = srng.integers(0, 2, 40000).astype(np.uint8)
    syms = ((1 - 2 * synth[0::2].astype(np.int8))
            + 1j * (1 - 2 * synth[1::2].astype(np.int8))) / np.sqrt(2.0)
    at_true = demod._lock_angle_deg(syms)
    at_null = demod._lock_angle_deg(syms * np.exp(1j * np.pi / 4.0))
    check("lock angle separates true lock from 45 degree lock",
          abs(at_true) > 170.0 and abs(at_null) < 10.0,
          f"true lock {at_true:+.1f} deg, 45 deg lock {at_null:+.1f} deg")
    fixed = syms * np.exp(1j * np.pi / 4.0) * np.exp(-1j * np.pi / 4.0)
    check("derotating by 45 degrees restores a slicable constellation",
          abs(demod._lock_angle_deg(fixed)) > 170.0,
          f"recovered {demod._lock_angle_deg(fixed):+.1f} deg")

    # The four stable locks are 90 degrees apart, so the BER harness must be
    # able to undo any of them. Confirm derotate90 inverts a real rotation for
    # every quadrant and both I/Q wirings.
    ref = np.empty(2 * len(syms), dtype=np.uint8)
    ref[0::2] = (syms.real < 0)
    ref[1::2] = (syms.imag < 0)
    ok_all = True
    for swap in (False, True):
        for k in range(4):
           spun = syms * np.exp(1j * k * np.pi / 2.0)
           if swap:
               spun = spun.imag + 1j * spun.real
           rb = np.empty(2 * len(spun), dtype=np.uint8)
           rb[0::2] = (spun.real < 0)
           rb[1::2] = (spun.imag < 0)
           ok_all = ok_all and np.array_equal(derotate90(rb, (4 - k) % 4, swap), ref)
    check("derotate90 inverts all four lock quadrants and both wirings", ok_all,
          "round-trips for k=0..3 with and without I/Q swap")

    y, _ = channel.apply(iq, phase_deg=45.0)
    r = demod.qpsk_demod(y, max_symbols=20000)
    ber, quarter_turns, _, _ = align_ber(r["bits"], bits)
    check("noiseless exact 45 degree offset decodes",
          ber == 0.0,
          f"ber={ber:.2e} lock_angle={r['lock_angle_deg']:+.1f} deg "
          f"hypothesis={r['initial_phase_deg']:+.0f} deg "
          f"derotated={r['derotated_45deg']} lock_quadrant={quarter_turns*90} deg")

    # --- 4. framing on the framed carrier --------------------------------------
    print("\n4. framing (framed carrier, impaired)")
    y, _ = channel.apply(iq, cfo_hz=60e3, timing_off_symbols=0.3, ppm=15.0,
                         snr_db=14.0)
    d = demod.qpsk_demod(y)
    out = pipeline.decode_bits(d["bits"], gen.TEST_SYNC_WORD,
                               frame_len_bits=FRAME_BITS, max_errors=0)
    check("marker found", out["n_hits"] > 5, f"{out['n_hits']} hits")
    check("frame period", out["period"] == FRAME_BITS,
          f"period {out['period']} bits, expected {FRAME_BITS}")
    check("all sliced frames intact", out["n_bad"] == 0,
          f"{out['n_ok']} ok, {out['n_bad']} bad, {out['drops']} counter drops")

    # A real loop may settle a quarter turn away from the true constellation.
    # If the marker search cannot express that, the receiver reports no frames
    # at all on a perfectly good signal.
    spun = frame_sync.rotate_bits(d["bits"], quarter_turns=1)
    found = pipeline.decode_bits(spun, gen.TEST_SYNC_WORD,
                                 frame_len_bits=FRAME_BITS, max_errors=0)
    check("a quarter-turn-off lock still finds frames",
          found["n_hits"] == out["n_hits"] and
          found["quadrant"]["quarter_turns"] == 3,
          f"{found['n_hits']} hits recovered by rotating "
          f"{found['quadrant']['quarter_turns']*90} deg back")

    # --- 5. false-alarm behaviour ---------------------------------------------
    print("\n5. false alarms")
    fa = frame_sync.false_alarm_rate(32, max_errors=2, bit_rate=SYM_RATE)
    print(f"       analytic: a 32-bit marker with 2 errors tolerated matches "
          f"noise every {fa['seconds_per_hit']:.1f} s at {SYM_RATE/1e6:.2f} Mbit/s")
    fa0 = frame_sync.false_alarm_rate(32, max_errors=0, bit_rate=SYM_RATE)
    print(f"       analytic: same marker with 0 errors tolerated: "
          f"every {fa0['seconds_per_hit']/60:.0f} min")
    print(f"       longest marker worth trusting for a 1 h mean interval: "
          f"{frame_sync.required_sync_len(SYM_RATE, 3600)} bits")

    rng = np.random.default_rng(7)
    noise_bits = rng.integers(0, 2, 6_000_000).astype(np.uint8)
    hits_loose = frame_sync.find_sync(noise_bits, gen.TEST_SYNC_WORD, 32,
                                      max_errors=2)
    hits_tight = frame_sync.find_sync(noise_bits, gen.TEST_SYNC_WORD, 32,
                                      max_errors=0)
    predicted = fa["hits_per_second"] * len(noise_bits) / SYM_RATE
    check("loose marker on noise behaves as predicted",
          abs(len(hits_loose) - predicted) <= max(3.0, 0.35 * predicted),
          f"{len(hits_loose)} hits observed, {predicted:.1f} predicted")
    check("strict marker on noise yields no frames",
          len(hits_tight) == 0,
          f"{len(hits_tight)} hits with max_errors=0 on 6 Mbit of noise")

    # --- 6. periodicity search negative control -------------------------------
    print("\n6. marker-free frame-period search")
    noise_series = rng.standard_normal(200_000)
    res = frame_sync.find_frame_period(noise_series, sym_rate=SYM_RATE)
    check("periodicity needs a real frame",
          not res["covered"],
          f"only {res['available_symbols']} symbols available, "
          f"{res['needed_symbols']} needed for one 432 ms frame period")

    # --- 7. S-curve sanity ----------------------------------------------------
    print("\n7. Gardner S-curve zero crossing")
    slope_at = {}
    for sym_off in (-0.1, 0.1):
        t0 = 2.0 + 40 + sym_off * SPS
        es, ys, yprev, t = [], [], 0j, t0
        for _ in range(4000):
            yc = demod.interp_one(mf, t)
            ym = demod.interp_one(mf, t - SPS / 2.0)
            es.append(((yc - yprev) * ym.conjugate()).real)
            ys.append(yc)
            yprev = yc
            t += SPS
        var = float(np.mean(np.abs(np.array(ys)) ** 2))
        slope_at[sym_off] = float(np.mean(es)) / var
    check("S-curve is odd around the ISI-free instant",
          slope_at[-0.1] < 0 < slope_at[0.1],
          f"e(-0.1 sym)={slope_at[-0.1]:+.4f}, e(+0.1 sym)={slope_at[0.1]:+.4f}")

    print()
    if _failures:
        print(f"FAILED: {len(_failures)} gate(s): {', '.join(_failures)}")
        return 1
    print("All gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
