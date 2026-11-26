#!/usr/bin/env python3
"""Offline simulation of the RAD 700i beep channel, and of per-band replacements.

Model (see AUDIO_HW.md §1-§6):
  the beep is a hardware 16-bit timer in PWM mode, 50 % duty.
      period register 0xC1218 = d-1     duty 0xC121A = (d-1)>>1
      start = bset #6,[0xC1280]         stop  = bclr #6,[0xC1280]
      f_out = f_timer / d
  the envelope is the 0xFFF93BDC state machine: 50 ms on, 30 ms off, 50 ms on
  (0x4C5D4+136 == 1) or a single 50 ms pulse; the blocking self-test beep is
  3 x 60 ms on separated by an arbitrary gap.

Nothing here writes to, or derives from, a modified firmware image. It is a
pure signal model so candidate tones can be compared before anything is patched.

Usage: python3 tools/sim_audio.py [outdir]
"""
import sys
import wave
import math
from pathlib import Path

import numpy as np

FS = 48000                      # simulation rate for listening
CLOCKS = [                      # from the SCKCR table at 0xFFFA32F0
    ("60MHz", 60_000_000),
    ("40MHz", 40_000_000),
    ("30MHz", 30_000_000),
    ("15MHz", 15_000_000),
    ("7.5MHz", 7_500_000),
]
BEEP_PERIOD = 15000             # 0x3A98, every constant call site of 0xFFFB2BA1
BOOT_PERIOD = 15150             # 0x3B2E, parked value from 0xFFFA770B
MAX_PERIOD = 0xFFFF             # period register is 16-bit


def period_for(freq, clk):
    """16-bit period that produces freq on a clk-driven timer, or None."""
    d = int(round(clk / freq))
    return d if 1 <= d <= MAX_PERIOD else None


def tone(freq, ms, clk, fs=FS, ramp_ms=1.5):
    """One gated square-wave burst, as the hardware would emit it."""
    n = max(1, int(round(ms * fs / 1000)))
    t = np.arange(n) / fs
    sq = np.sign(np.sin(2 * math.pi * freq * t))
    sq[sq == 0] = 1.0
    r = max(1, int(round(ramp_ms * fs / 1000)))
    if 2 * r < n:
        env = np.ones(n)
        env[:r] = np.linspace(0, 1, r)
        env[-r:] = np.linspace(1, 0, r)
        sq *= env
    return sq


def envelope(segments, freq, clk, fs=FS):
    """segments: list of (ms, on?) -> concatenated signal."""
    out = [np.zeros(max(1, int(round(ms * fs / 1000)))) if not on
           else tone(freq, ms, clk, fs)
           for ms, on in segments]
    return np.concatenate(out)


def save(path, sig, fs=FS):
    pcm = np.clip(sig, -1, 1)
    pcm = (pcm * 32000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())


def measure(sig, fs=FS):
    """Dominant frequency of the non-silent part, for self-check."""
    nz = np.nonzero(np.abs(sig) > 0.2)[0]
    if len(nz) == 0:
        return 0.0
    seg = sig[nz[0]:nz[-1] + 1]
    seg = seg[: min(len(seg), fs)] * np.hanning(min(len(seg), fs))
    S = np.abs(np.fft.rfft(seg))
    f = np.fft.rfftfreq(len(seg), 1 / fs)
    return float(f[np.argmax(S)])


# --- the sound as the firmware produces it today -----------------------------
# 0xFFF93BDC states 1..5: start, wait 50 ticks, stop, wait 30, start, wait 50, stop
ALERT_DOUBLE = [(50, True), (30, False), (50, True)]
ALERT_SINGLE = [(50, True)]
SELFTEST_TRIPLE = [(60, True), (120, False), (60, True), (120, False), (60, True)]

# --- proposed per-band tones ------------------------------------------------
# Only the period constant at the three alert call sites changes, so each band
# gets ONE fixed pitch; distinction comes from pitch + pulse count/spacing,
# exactly the two degrees of freedom the hardware actually has.
PROPOSED = {
    "X":     dict(freq=1000, seg=[(90, True), (100, False), (90, True)]),
    "K":     dict(freq=1400, seg=[(70, True), (70, False), (70, True)]),
    "Ka":    dict(freq=2000, seg=[(45, True), (45, False)] * 3 + [(45, True)]),
    "LASER": dict(freq=2600, seg=[(30, True), (25, False)] * 5 + [(30, True)]),
}


def main():
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "out/sim")
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"beep period from firmware: 0x{BEEP_PERIOD:04X} = {BEEP_PERIOD}")
    print(f"duty: (d-1)>>1 = {(BEEP_PERIOD - 1) >> 1} (50 %)\n")
    print("existing beep frequency by clock hypothesis:")
    print(f"  {'clock':8s} {'f = clk/15000':>14s}   {'period us':>10s}")
    for name, clk in CLOCKS:
        f = clk / BEEP_PERIOD
        print(f"  {name:8s} {f:12.1f} Hz   {1e6 / f:10.1f}")
    print(f"\n  parked boot value 0x3B2E = {BOOT_PERIOD}: "
          f"{60_000_000 / BOOT_PERIOD:.1f} Hz at 60 MHz")

    # simulate under the 60 MHz working hypothesis (documented as unconfirmed)
    clk = CLOCKS[0][1]
    made = []

    for label, seg in (("double", ALERT_DOUBLE), ("single", ALERT_SINGLE)):
        sig = envelope(seg, clk / BEEP_PERIOD, clk)
        p = outdir / f"current_alert_{label}.wav"
        save(p, sig)
        made.append((p, measure(sig), len(sig) / FS * 1000))

    sig = envelope(SELFTEST_TRIPLE, clk / BEEP_PERIOD, clk)
    p = outdir / "current_selftest_triple.wav"
    save(p, sig)
    made.append((p, measure(sig), len(sig) / FS * 1000))

    print("\nproposed per-band tones (period written at the alert call sites):")
    print(f"  {'band':6s} {'freq':>7s} {'period@60MHz':>13s} {'period@30MHz':>13s} "
          f"{'fits 16-bit':>12s}  pulses")
    for band, spec in PROPOSED.items():
        f = spec["freq"]
        d60 = period_for(f, 60_000_000)
        d30 = period_for(f, 30_000_000)
        ok = "yes" if d60 else "NO"
        npul = sum(1 for _, on in spec["seg"] if on)
        print(f"  {band:6s} {f:5d}Hz {str(d60):>13s} {str(d30):>13s} {ok:>12s}  {npul}")
        sig = envelope(spec["seg"], f, clk)
        p = outdir / f"proposed_{band.lower()}.wav"
        save(p, sig)
        made.append((p, measure(sig), len(sig) / FS * 1000))

    # full alert at three signal-strength cadences. The tick thresholds in the 47
    # engine call sites (500 / 280 / 120 ms from the compare chains) are treated
    # here as repetition intervals; the gap never goes below 10 ms because a burst
    # cannot be shorter than itself.
    burst_ms = sum(ms for ms, on in PROPOSED["Ka"]["seg"] if on)
    for ssm, interval in (("weak", 500), ("mid", 280), ("strong", 120)):
        segs = []
        f = PROPOSED["Ka"]["freq"]
        gap = max(10, interval - burst_ms)
        for _ in range(4):
            segs += PROPOSED["Ka"]["seg"] + [(gap, False)]
        sig = envelope(segs, f, clk)
        p = outdir / f"proposed_ka_repeat_{ssm}.wav"
        save(p, sig)
        made.append((p, measure(sig), len(sig) / FS * 1000))

    print("\nwritten:")
    for p, f0, ms in made:
        print(f"  {p.name:34s} {ms:7.0f} ms  measured {f0:7.1f} Hz")


if __name__ == "__main__":
    main()
