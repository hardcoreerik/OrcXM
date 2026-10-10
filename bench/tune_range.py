"""Sweep ESP-SDR tuning on COM36 and save waterfall plots.

Software accepts FREQ 100..6000 in 1 MHz steps. This measures what the
receiver actually returns: RMS, DC, and the spectrum shape at each tune.
Snapshots are gapped CAP16 bursts, not a continuous stream.
"""
import time
import zlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import serial

PORT = "COM36"
BAUD = 2_000_000
FS = 16_000_000
RATE = 6
GAIN = 70
OUT = Path(__file__).resolve().parent / "tune-range"

# One 16 MS/s capture is ±8 MHz, so a 16 MHz step abuts the next window.
SWEEP_START = 100
SWEEP_STOP = 6000
SWEEP_STEP = 16
SWEEP_N = 2048
FALL_N = 4096
FALL_FRAMES = 36
FALL_TUNES = (100, 2338, 2437, 6000)


class Radio:
    def __init__(self):
        ser = serial.Serial()
        ser.port = PORT
        ser.baudrate = BAUD
        ser.timeout = 1.5
        ser.write_timeout = 2
        ser.dtr = False
        ser.rts = False
        ser.open()
        time.sleep(0.2)
        ser.reset_input_buffer()
        self.ser = ser

    def close(self):
        self.ser.close()

    def line(self, cmd: str) -> str:
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\n").encode())
        self.ser.flush()
        buf = bytearray()
        deadline = time.time() + 2.0
        while time.time() < deadline and not buf.endswith(b"\n"):
            b = self.ser.read(1)
            if b:
                buf += b
        text = buf.decode("utf-8", "replace").strip()
        if not text or text.startswith("ERR"):
            raise RuntimeError(f"{cmd} -> {text or 'timeout'}")
        return text

    def capture(self, samples: int) -> np.ndarray:
        self.ser.reset_input_buffer()
        self.ser.write(f"CAP16 {samples} {RATE}\n".encode())
        self.ser.flush()
        header = bytearray()
        deadline = time.time() + 3.0
        while time.time() < deadline and not header.endswith(b"\n"):
            b = self.ser.read(1)
            if b:
                header += b
        parts = header.decode("utf-8", "replace").split()
        if len(parts) < 4 or parts[0] != "DATA":
            raise RuntimeError(f"bad header {header!r}")
        n = int(parts[1])
        crc = int(parts[2], 16)
        payload = self.ser.read(n * 2)
        if len(payload) != n * 2:
            raise RuntimeError(f"short payload {len(payload)}")
        if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
            raise RuntimeError("crc")
        raw = np.frombuffer(payload, dtype=np.int8).astype(np.float32)
        return raw[0::2] + 1j * raw[1::2]


def spectrum(iq: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    dc = float(np.abs(np.mean(iq)))
    z = iq - np.mean(iq)
    rms = float(np.sqrt(np.mean(np.abs(z) ** 2)))
    window = np.hanning(z.size).astype(np.float32)
    power = np.abs(np.fft.fftshift(np.fft.fft(z * window))) ** 2
    power /= np.sum(window ** 2)
    freqs = np.fft.fftshift(np.fft.fftfreq(z.size, 1.0 / FS))
    return freqs, power, rms, dc


def decimate(power: np.ndarray, bins: int) -> np.ndarray:
    usable = (power.size // bins) * bins
    return power[:usable].reshape(bins, -1).mean(axis=1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    radio = Radio()
    try:
        print(radio.line("INFO"), flush=True)
        print(radio.line("TRANSPORT?"), flush=True)
        radio.line(f"GAIN MANUAL {GAIN}")
        radio.line("BANDWIDTH 20")
        print(radio.line("GAIN?"), flush=True)

        tunes = list(range(SWEEP_START, SWEEP_STOP + 1, SWEEP_STEP))
        rows = []
        rms = []
        dc = []
        accepted = []
        t0 = time.time()
        for i, mhz in enumerate(tunes):
            try:
                radio.line(f"FREQ {mhz}")
                _, power, r, d = spectrum(radio.capture(SWEEP_N))
                rows.append(decimate(power, 128))
                rms.append(r)
                dc.append(d)
                accepted.append(True)
            except RuntimeError as exc:
                print(f"skip {mhz}: {exc}", flush=True)
                rows.append(np.full(128, np.nan))
                rms.append(np.nan)
                dc.append(np.nan)
                accepted.append(False)
            if i % 25 == 0:
                print(f"{mhz:5d} MHz  rms={rms[-1]:.2f}  {time.time()-t0:.0f}s", flush=True)
        rows = np.stack(rows)
        rms = np.array(rms)
        dc = np.array(dc)
        tunes = np.array(tunes)
        print(f"sweep {tunes.size} tunes in {time.time()-t0:.1f}s", flush=True)

        falls = {}
        for mhz in FALL_TUNES:
            radio.line(f"FREQ {mhz}")
            frames = []
            for _ in range(FALL_FRAMES):
                freqs, power, _, _ = spectrum(radio.capture(FALL_N))
                frames.append(decimate(power, 256))
            falls[mhz] = (freqs, np.stack(frames))
            print(f"waterfall {mhz} done", flush=True)

        np.savez_compressed(
            OUT / "survey.npz",
            tunes=tunes,
            rows=rows.astype(np.float32),
            rms=rms.astype(np.float32),
            dc=dc.astype(np.float32),
            accepted=np.array(accepted),
        )
        plot(tunes, rows, rms, dc, falls)
        summarize(tunes, rms, dc)
    finally:
        radio.close()


def plot(tunes, rows, rms, dc, falls):
    db = 10 * np.log10(np.maximum(rows, 1e-20))
    finite = db[np.isfinite(db)]
    vmin, vmax = np.percentile(finite, [5, 99])

    fig, ax = plt.subplots(figsize=(11, 8))
    extent = [-8, 8, tunes[-1] + SWEEP_STEP / 2, tunes[0] - SWEEP_STEP / 2]
    im = ax.imshow(db, aspect="auto", extent=extent, vmin=vmin, vmax=vmax, cmap="inferno", interpolation="nearest")
    ax.set_xlabel("MHz from the tune")
    ax.set_ylabel("Tune (MHz)")
    ax.set_title(f"ESP32-S3 shape waterfall, GAIN MANUAL {GAIN}, 16 MS/s, {SWEEP_STEP} MHz steps")
    for edge in (1842, 2209, 2400, 2483):
        ax.axhline(edge, color="cyan", lw=0.4, alpha=0.7)
    fig.colorbar(im, ax=ax, label="dB, arbitrary")
    fig.tight_layout()
    fig.savefig(OUT / "shape-waterfall.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(tunes, rms, lw=0.9)
    ax.set_xlabel("Tune (MHz)")
    ax.set_ylabel("RMS (ADC counts)")
    ax.set_title(f"Capture level vs tune, GAIN MANUAL {GAIN}")
    ax.grid(True, alpha=0.3)
    for edge, name in ((1842, "5/6 low"), (2209, "5/6 high"), (2400, "ISM"), (2484, "ISM")):
        ax.axvline(edge, color="tab:red", lw=0.5, alpha=0.6)
    fig.tight_layout()
    fig.savefig(OUT / "rms-vs-tune.png", dpi=140)
    plt.close(fig)

    # Stitch the center of each window onto an absolute-frequency axis.
    grid = np.arange(SWEEP_START, SWEEP_STOP + 1, 1)
    acc = np.zeros(grid.size)
    weight = np.zeros(grid.size)
    centers = np.linspace(-8, 8, rows.shape[1], endpoint=False) + (16 / rows.shape[1] / 2)
    keep = np.abs(centers) <= 6
    for tune, row in zip(tunes, rows):
        if not np.isfinite(row).all():
            continue
        rf = tune + centers[keep]
        idx = np.clip(np.round(rf - grid[0]).astype(int), 0, grid.size - 1)
        acc[idx] += row[keep]
        weight[idx] += 1
    stitched = np.divide(acc, weight, out=np.zeros_like(acc), where=weight > 0)
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.plot(grid, 10 * np.log10(np.maximum(stitched, 1e-20)), lw=0.6)
    ax.set_xlabel("RF (MHz)")
    ax.set_ylabel("dB, arbitrary")
    ax.set_title("Stitched spectrum, center ±6 MHz of each tune")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "stitched.png", dpi=140)
    plt.close(fig)

    for mhz, (freqs, frames) in falls.items():
        fdb = 10 * np.log10(np.maximum(frames, 1e-20))
        lo, hi = np.percentile(fdb, [5, 99.5])
        fig, ax = plt.subplots(figsize=(10, 4.2))
        extent = [-8, 8, frames.shape[0], 0]
        im = ax.imshow(fdb, aspect="auto", extent=extent, vmin=lo, vmax=hi, cmap="inferno", interpolation="nearest")
        ax.set_xlabel(f"MHz from {mhz}")
        ax.set_ylabel("Snapshot (gapped)")
        ax.set_title(f"Time waterfall at {mhz} MHz, {FALL_FRAMES} x CAP16")
        fig.colorbar(im, ax=ax, label="dB, arbitrary")
        fig.tight_layout()
        fig.savefig(OUT / f"waterfall-{mhz}.png", dpi=140)
        plt.close(fig)
    print("wrote", OUT, flush=True)


def summarize(tunes, rms, dc):
    ok = np.isfinite(rms)
    print(f"accepted {int(ok.sum())}/{tunes.size}", flush=True)
    log_r = np.log10(np.maximum(rms, 1e-3))
    jump = np.diff(log_r)
    order = np.argsort(np.abs(np.where(np.isfinite(jump), jump, 0)))[::-1]
    print("largest RMS jumps (MHz, ratio dB):", flush=True)
    for k in order[:12]:
        if not np.isfinite(jump[k]):
            continue
        print(f"  {tunes[k]:5.0f}->{tunes[k+1]:5.0f}  {20*jump[k]:+6.1f} dB", flush=True)
    anchors = (100, 500, 900, 1500, 1800, 1840, 1900, 2100, 2208, 2300, 2336, 2432, 2500, 2700, 3500, 5000, 5800, 6000)
    print("anchor RMS / DC:", flush=True)
    for a in anchors:
        i = int(np.argmin(np.abs(tunes - a)))
        print(f"  {tunes[i]:5.0f}  rms={rms[i]:7.2f}  dc={dc[i]:6.2f}", flush=True)


if __name__ == "__main__":
    main()
