"""Outdoor spectrum look on a native-USB ESP32-S3 running ESP-SDR.

Phase 0 presence check only. It does not demodulate, and it does not
touch the SiriusXM cipher.

This firmware (protocol 6, the 2026-10-08 esp32s3 build) accepts whole
megahertz only. BANDWIDTH below 13 is rejected; the capture uses 20.
Gain is manual. Around 2.33 GHz the spectrum is inverted about the dial
and the reference reads about 60 kHz low, so bins are mirrored before
the hump is measured. The line on the tune center is the receiver's own
spur and is left out of the score.

Each carrier is tuned 2-3.5 MHz off its dial, not on it. The spur is
+4 to +7 dB over the floor and the window discards +/-150 kHz of it, so
a carrier tuned to its own dial loses its middle bins; three of the six
did under the old dials. `xm_metrics.dial_plan()` picks the dials.

Default port is COM3, the T-Display-S3. The OrcXM handheld image does
not speak this protocol. Pass --port for a board that is still running
ESP-SDR. COM36 was left on ESP-SDR and is not opened unless you pass
--port.

The ST7789 on a T-Display-S3 stays blank. ESP-SDR does not drive it.
The laptop has to stay attached.

Usage (from the repo root):
    python bench/outdoor_capture.py
    python bench/outdoor_capture.py --frames 12 --tag indoor
"""

from __future__ import annotations

import argparse
import time
import zlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import serial

import xm_metrics

FS = 16_000_000
RATE = 6
SPUR_HZ = xm_metrics.SPUR_HZ
SMOOTH_HZ = xm_metrics.SMOOTH_HZ

# Integer dial, role, and the published center in MHz when there is one.
# The six carriers come from the shared plan so code and report agree.
_ROLE = {"Sat1A": "sat", "Sat2A": "sat", "Sat2B": "sat", "Sat1B": "sat",
         "TerrA": "terr", "TerrB": "terr"}
TUNES = (
    (2437, "wifi", None, "Wi-Fi channel 6"),
    (2412, "wifi", None, "Wi-Fi channel 1"),
) + tuple(
    (p["dial_mhz"], _ROLE[p["carrier"]], p["center_mhz"],
     f"{p['carrier']} {p['center_mhz']:.3f}, {p['offset_mhz']:.2f} MHz off dial")
    for p in xm_metrics.dial_plan()
) + (
    (2323, "away", None, "tune-away 10 MHz below"),
    (2354, "away", None, "tune-away 10 MHz above"),
)

# The 2026-10-10 geometry: nearest integer dial, carrier on or beside the spur.
LEGACY_TUNES = (
    (2437, "wifi", None, "Wi-Fi channel 6"),
    (2412, "wifi", None, "Wi-Fi channel 1"),
    (2333, "sat", 2333.465, "satellite 2333.465"),
    (2335, "sat", 2335.305, "satellite 2335.305"),
    (2337, "terr", 2337.490, "terrestrial 2337.490"),
    (2340, "terr", 2340.020, "terrestrial 2340.020"),
    (2342, "sat", 2342.205, "satellite 2342.205"),
    (2344, "sat", 2344.045, "satellite 2344.045"),
    (2323, "away", None, "tune-away 10 MHz below"),
    (2354, "away", None, "tune-away 10 MHz above"),
)


class Radio:
    def __init__(self, port: str, baud: int):
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.timeout = 0.3
        ser.write_timeout = 2
        ser.dtr = False
        ser.rts = False
        ser.open()
        time.sleep(0.15)
        self.ser = ser
        # Opening USB-Serial/JTAG can reset the chip. 4 s covers that boot;
        # an already-running board returns as soon as the line is quiet.
        self._drain(4.0)

    def close(self) -> None:
        self.ser.close()

    def _drain(self, max_s: float) -> bytes:
        blob = bytearray()
        last = time.time()
        end = time.time() + max_s
        while time.time() < end:
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                blob += chunk
                last = time.time()
                continue
            quiet = time.time() - last
            if blob and quiet > 0.35:
                break
            if not blob and quiet > 0.45:
                break
        return bytes(blob)

    def _readline(self, wait_s: float) -> bytes:
        buf = bytearray()
        deadline = time.time() + wait_s
        while time.time() < deadline and not buf.endswith(b"\n"):
            got = self.ser.read(1)
            if got:
                buf += got
        return bytes(buf)

    def line(self, cmd: str, wait_s: float = 2.0) -> str:
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())
        self.ser.flush()
        text = self._readline(wait_s).decode("utf-8", "replace").strip()
        if not text or text.startswith("ERR"):
            raise RuntimeError(f"{cmd} -> {text or 'timeout'}")
        return text

    def capture(self, samples: int) -> np.ndarray:
        last = "timeout"
        for _ in range(3):
            self.ser.reset_input_buffer()
            self.ser.write(f"CAP16 {samples} {RATE}\n".encode())
            self.ser.flush()
            header = self._readline(3.0)
            parts = header.decode("utf-8", "replace").split()
            if len(parts) < 3 or parts[0] != "DATA":
                last = f"bad header {header!r}"
                continue
            n = int(parts[1])
            crc = int(parts[2], 16)
            payload = self.ser.read(n * 2)
            if len(payload) != n * 2:
                last = f"short payload {len(payload)}"
                continue
            if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
                last = "crc"
                continue
            raw = np.frombuffer(payload, dtype=np.int8).astype(np.float32)
            return raw[0::2] + 1j * raw[1::2]
        raise RuntimeError(last)


def spectrum(iq: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    z = iq - np.mean(iq)
    rms = float(np.sqrt(np.mean(np.abs(z) ** 2)))
    clip = float(np.mean(np.abs(iq) >= 126))
    window = np.hanning(z.size).astype(np.float32)
    power = np.abs(np.fft.fftshift(np.fft.fft(z * window))) ** 2
    power /= np.sum(window**2)
    baseband = np.fft.fftshift(np.fft.fftfreq(z.size, 1.0 / FS))
    return baseband, power, rms, clip


def smooth(power: np.ndarray, hz: float) -> np.ndarray:
    bin_hz = FS / power.size
    width = max(1, int(round(hz / bin_hz)))
    if width % 2 == 0:
        width += 1
    kernel = np.ones(width, dtype=np.float64) / width
    return np.convolve(power, kernel, mode="same")


corrected_hz = xm_metrics.corrected_hz
score_carrier = xm_metrics.score_carrier


def measure(radio: Radio, dial: int, samples: int, frames: int) -> dict:
    radio.line(f"FREQ {dial}")
    powers = []
    rms = []
    clip = []
    baseband = None
    for _ in range(frames):
        iq = radio.capture(samples)
        baseband, power, r, c = spectrum(iq)
        powers.append(power)
        rms.append(r)
        clip.append(c)
    stack = np.stack(powers)
    rms_a = np.array(rms, dtype=np.float32)
    return {
        "dial_mhz": dial,
        "baseband": baseband.astype(np.float32),
        # Median spectrum, so one Wi-Fi-like burst cannot paint a hump.
        "median_power": np.median(stack, axis=0).astype(np.float32),
        "max_power": stack.max(axis=0).astype(np.float32),
        "rms_med": float(np.median(rms_a)),
        "rms_p95": float(np.percentile(rms_a, 95)),
        "clip": float(np.mean(clip)),
        "frames": frames,
    }


def plot(path: Path, rows: list[dict]) -> None:
    n = len(rows)
    cols = 5
    grid_rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(grid_rows, cols, figsize=(3.2 * cols, 2.6 * grid_rows), squeeze=False)
    for ax, row in zip(axes.ravel(), rows):
        bb = row["baseband"]
        true_mhz = corrected_hz(row["dial_mhz"], bb) / 1e6
        db = 10.0 * np.log10(smooth(row["median_power"], SMOOTH_HZ) + 1e-20)
        step = max(1, db.size // 400)
        ax.plot(true_mhz[::step], db[::step], color="#1f4e79", lw=0.8)
        ax.axvline(row["dial_mhz"] + xm_metrics.REF_LOW_HZ / 1e6, color="#999999", lw=0.6)
        title = f"{row['dial_mhz']}  {row['label']}"
        if row["role"] == "wifi":
            burst_db = 20.0 * np.log10(row["rms_p95"] / max(row["rms_med"], 1e-3))
            title = f"{row['dial_mhz']}  loud frame {burst_db:+.0f} dB\n{row['label']}"
        if row.get("center_mhz"):
            ax.axvspan(row["center_mhz"] - 0.95, row["center_mhz"] + 0.95, color="#f4c7a4", alpha=0.45)
            title = (
                f"{row['dial_mhz']}  {row['excess_db']:+.1f} dB"
                f"\n{row['verdict']}"
            )
        ax.set_title(title, fontsize=8)
        ax.set_xlim(row["dial_mhz"] - 6, row["dial_mhz"] + 6)
        ax.tick_params(labelsize=7)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.suptitle("Corrected MHz (mirror undone, spur at the gray line)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="ESP-SDR outdoor XM presence look")
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--baud", type=int, default=2_000_000)
    parser.add_argument("--gain", type=int, default=70)
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--samples", type=int, default=8192)
    parser.add_argument("--tag", default="outdoor")
    parser.add_argument(
        "--legacy-dials",
        action="store_true",
        help="nearest integer dial per carrier (2026-10-10 geometry, carrier on the spur)",
    )
    args = parser.parse_args()
    if not 0 <= args.gain <= 82:
        raise SystemExit("gain must be 0..82")
    if not 256 <= args.samples <= 16380:
        raise SystemExit("samples must be 256..16380")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(__file__).resolve().parent / "outdoor" / f"{stamp}-{args.tag}"
    out.mkdir(parents=True, exist_ok=True)

    radio = Radio(args.port, args.baud)
    rows: list[dict] = []
    info = ""
    try:
        info = radio.line("INFO")
        print(info, flush=True)
        print(radio.line("TRANSPORT?"), flush=True)
        for extra in ("LIMITS?", "RANGE?"):
            try:
                print(radio.line(extra), flush=True)
            except RuntimeError as exc:
                print(exc, flush=True)
        radio.line(f"GAIN MANUAL {args.gain}")
        radio.line("BANDWIDTH 20")
        print(radio.line("GAIN?"), flush=True)
        print(
            f"{args.port} gain {args.gain}, {args.frames} frames x {args.samples} samples",
            flush=True,
        )
        t0 = time.time()
        tunes = LEGACY_TUNES if args.legacy_dials else TUNES
        if args.legacy_dials:
            print("legacy dials: carrier on or beside the spur", flush=True)
        for dial, role, center, label in tunes:
            t1 = time.time()
            row = measure(radio, dial, args.samples, args.frames)
            row["role"] = role
            row["label"] = label
            row["center_mhz"] = center
            if center is not None:
                row.update(score_carrier(dial, center, row["baseband"], row["median_power"]))
                tilt = "  -  " if np.isnan(row["tilt_db"]) else f"{row['tilt_db']:5.1f}"
                print(
                    f"{dial:4d}  rms {row['rms_med']:6.2f}  p95 {row['rms_p95']:6.2f}"
                    f"  {row['excess_db']:+6.2f} dB  gate {row['threshold_db']:4.1f}"
                    f"  tilt {tilt}  width {row['width_mhz']:.2f} MHz"
                    f"  {row['verdict']}  ({time.time() - t1:.0f}s)",
                    flush=True,
                )
                if row["spur_masks_carrier"]:
                    print(
                        f"      WARNING: carrier is inside the +/-150 kHz spur exclusion; "
                        f"tune this carrier {row['dial_mhz']:d} MHz off its dial instead",
                        flush=True,
                    )
            else:
                row["excess_db"] = float("nan")
                row["width_mhz"] = 0.0
                row["verdict"] = role
                print(
                    f"{dial:4d}  rms {row['rms_med']:6.2f}  p95 {row['rms_p95']:6.2f}"
                    f"  clip {row['clip'] * 100:.2f}%  {label}  ({time.time() - t1:.0f}s)",
                    flush=True,
                )
            rows.append(row)
        print(f"done in {time.time() - t0:.0f}s", flush=True)
    finally:
        radio.close()
        if rows:
            np.savez_compressed(
                out / "capture.npz",
                info=np.array(info),
                gain=np.int32(args.gain),
                dials=np.array([r["dial_mhz"] for r in rows], dtype=np.int32),
                roles=np.array([r["role"] for r in rows]),
                labels=np.array([r["label"] for r in rows]),
                centers=np.array(
                    [np.nan if r["center_mhz"] is None else r["center_mhz"] for r in rows],
                    dtype=np.float64,
                ),
                excess_db=np.array([r["excess_db"] for r in rows], dtype=np.float32),
                width_mhz=np.array([r["width_mhz"] for r in rows], dtype=np.float32),
                threshold_db=np.array([r.get("threshold_db", np.nan) for r in rows], dtype=np.float32),
                tilt_db=np.array([r.get("tilt_db", np.nan) for r in rows], dtype=np.float32),
                spur_db=np.array([r.get("spur_db", np.nan) for r in rows], dtype=np.float32),
                spur_masks_carrier=np.array(
                    [bool(r.get("spur_masks_carrier", False)) for r in rows]
                ),
                metrics_version=np.int32(xm_metrics.METRICS_VERSION),
                rms_med=np.array([r["rms_med"] for r in rows], dtype=np.float32),
                rms_p95=np.array([r["rms_p95"] for r in rows], dtype=np.float32),
                clip=np.array([r["clip"] for r in rows], dtype=np.float32),
                baseband=rows[0]["baseband"],
                median_power=np.stack([r["median_power"] for r in rows]),
                max_power=np.stack([r["max_power"] for r in rows]),
            )
            plot(out / "spectra.png", rows)
            print(f"wrote {out}", flush=True)

    wifi_rows = [r for r in rows if r["role"] == "wifi"]
    if wifi_rows:
        loudest = max(wifi_rows, key=lambda r: r["rms_p95"])
        floor = max(loudest["rms_med"], 1e-3)
        burst_db = 20.0 * np.log10(loudest["rms_p95"] / floor)
        print(
            f"Wi-Fi {loudest['dial_mhz']} MHz floor RMS {loudest['rms_med']:.2f},"
            f" loud-frame RMS {loudest['rms_p95']:.2f} ({burst_db:+.1f} dB)",
            flush=True,
        )
        if burst_db >= 6.0:
            print("In-band sanity: the antenna heard a 2.4 GHz burst.", flush=True)
        else:
            print("In-band sanity: no clear 2.4 GHz burst in this run.", flush=True)
            print(
                "An empty 2.33 GHz result from this run does not say the sky is empty.",
                flush=True,
            )
    shaped = [
        r
        for r in rows
        if r["role"] in ("sat", "terr") and r["verdict"] == "carrier-shaped rise"
    ]
    if shaped:
        print("Carrier-shaped rises (still not demodulated audio):", flush=True)
        for r in shaped:
            print(
                f"  {r['label']}: {r['excess_db']:+.1f} dB over the tune's own edges,"
                f" width {r['width_mhz']:.2f} MHz",
                flush=True,
            )
    elif any(r["role"] in ("sat", "terr") for r in rows):
        print("No ~1.8 MHz carrier-shaped rise on the six centers.", flush=True)


if __name__ == "__main__":
    main()
