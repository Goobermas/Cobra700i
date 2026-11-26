#!/usr/bin/env python3
"""Side-by-side original vs proposed alert audio, cadence held constant.

The cadence is NOT changed here: every render uses the exact envelope the
firmware produces today (0xFFF93BDC: 50 ms on / 30 ms off / 50 ms on), so the
only audible difference from the original is pitch -- which is precisely what a
2-byte immediate change at the three alert sites buys.

Because the timer clock is still unconfirmed (see CLOCK_PATCH.md), every
comparison is rendered at each candidate clock so the pair can be judged at the
right speed once the clock is measured.

Usage: python3 tools/render_compare.py [outdir]
"""
import sys
import wave
from pathlib import Path

import numpy as np

FS = 48000
PERIOD = 15000                      # 0x3A98, the firmware constant
# 50 ms on, 30 ms off, 50 ms on -- unchanged from the original
ORIGINAL_SEGMENTS = [(50, True), (30, False), (50, True)]
# 15 MHz is the measured timer clock (CLOCK_AND_PATCH.md: 999.98 Hz x 15000).
# The others are kept only to show sensitivity if that measurement is revised.
CLOCKS = [("15MHz", 15_000_000), ("30MHz", 30_000_000), ("60MHz", 60_000_000)]

# At 15 MHz the stock beep (period 15000) is already 1000 Hz, so the proposed
# targets deliberately avoid 1000 Hz.  period = 15e6 / f, all <= 0xFFFF.
PROPOSED = {"X": 1250, "K": 1500, "Ka": 2000, "LASER": 2500}


def square(freq, ms, fs=FS, ramp_ms=1.5):
    n = max(1, int(round(ms * fs / 1000)))
    t = np.arange(n) / fs
    s = np.sign(np.sin(2 * np.pi * freq * t))
    s[s == 0] = 1.0
    r = max(1, int(round(ramp_ms * fs / 1000)))
    if 2 * r < n:
        e = np.ones(n)
        e[:r] = np.linspace(0, 1, r)
        e[-r:] = np.linspace(1, 0, r)
        s *= e
    return s


def render(segments, freq):
    out = []
    for ms, on in segments:
        out.append(square(freq, ms) if on else np.zeros(max(1, int(ms * FS / 1000))))
    return np.concatenate(out)


def save(path, sig):
    pcm = (np.clip(sig, -1, 1) * 32000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(pcm.tobytes())


def peak_freq(sig):
    nz = np.nonzero(np.abs(sig) > 0.2)[0]
    if len(nz) < 64:
        return 0.0
    seg = sig[nz[0]:nz[-1] + 1][: FS]
    if len(seg) < 64:
        return 0.0
    seg = seg * np.hanning(len(seg))
    f = np.fft.rfftfreq(len(seg), 1 / FS)
    return float(f[np.argmax(np.abs(np.fft.rfft(seg)))])


def main():
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "out/compare")
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"cadence held constant: {ORIGINAL_SEGMENTS} (unchanged from 0xFFF93BDC)\n")
    print(f"{'clock':7s} {'original':>20s}   {'proposed':38s}")
    for cname, clk in CLOCKS:
        forig = clk / PERIOD
        orig = render(ORIGINAL_SEGMENTS, forig)
        save(outdir / f"{cname}_original.wav", orig)
        cell = []
        for band, hz in PROPOSED.items():
            sig = render(ORIGINAL_SEGMENTS, float(hz))
            save(outdir / f"{cname}_proposed_{band}.wav", sig)
            cell.append(f"{band}={peak_freq(sig):.0f}Hz")
        print(f"{cname:7s} {forig:8.1f} Hz (meas {peak_freq(orig):7.1f})   "
              + "  ".join(cell))
    print(f"\nwritten to {outdir}/  -- listen original vs proposed_<band> at the")
    print("same clock; the on/off rhythm is identical by construction.")


if __name__ == "__main__":
    main()
