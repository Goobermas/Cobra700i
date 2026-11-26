#!/usr/bin/env python3
"""Offline simulator for the proposed band-aware PWM sound engine.

Models the radar sounder recovered from the image and varies only the tone
period, so the pitch change can be auditioned before any firmware is touched.

Recovered behaviour (see BEEP_CALLGRAPH.md):

    engine 0xFFF93BCF
      gate A: 22[0x3C188] == 1  -> return   (sounder disabled in config)
      gate B: bit 5 of 0xAEB6   -> return when CLEAR (not armed)
      counter 84[0x3AFC4] += 1 per call      (1 ms, confirmed by the recording)
      state byte 0x19DE3

      state 0 -> 120[0x4C5D4] = 1, pin on, state = 1
      state 1 -> tone(P), counter = 0, state = 2
      state 2 -> at counter == 50: stop.
                 if 136[0x4C5D4] == 1: state = 3           (double-pulse mode)
                 else: 120 = 0, bclr #5, state = 0         (disarm, single pulse)
      state 3 -> at counter == 30: counter = 0, state = 4
      state 4 -> tone(P), counter = 0, state = 5
      state 5 -> at counter == 50: stop, 120 = 0, bclr #5, state = 0

    tone(P) = 0xFFFB2BA1: [0xC1218] = P-1, [0xC121A] = (P-1)>>1,
                          timer start, buzzer pin 0x8C022 bit 2 set.

Why `armed` matters
-------------------
An earlier note read the gate backwards (engine running while bit 5 is clear).
That reading makes every burst end by clearing the very bit that keeps it
running, so the machine would re-trigger itself with a ~2 ms gap and produce a
period of ~133 ms.  The recording shows 50 ms on / 30 ms off, period 80 ms, so
the gate must be the opposite: each burst DISARMS the engine, and the silence is
the interval until the detection path re-arms it again.

The simulator therefore needs the external re-arm interval.  It defaults to 30 ms
so that the burst plus the gap reproduces the measured 80 ms period; that value
is an assumption about the detection loop, not something read out of the image.

Usage:
    python3 tools/bandaware_sim.py
    python3 tools/bandaware_sim.py --mode double --ms 400
"""
import argparse
import struct
import wave
from pathlib import Path

# --- recovered constants ----------------------------------------------------
TIMER_CLOCK = 15_000_000     # measured: 999.98 Hz x 15000
STOCK_PERIOD = 15000         # the only period the stock firmware uses
ON_MS = 50                   # cmp #50 (0xFFF93C6A, 0xFFF93CFC)
GAP_MS = 30                  # cmp #30 (0xFFF93CC1)

# --- band table.  Codes are record dword 0, proven at 0xFFF867F2-0xFFF86809 ---
BANDS = {
    0x10: ("X", 1250),
    0x20: ("K", 1500),
    0x30: ("Ka", 2000),
    0x05: ("Ka", 2000),      # second Ka encoding in the same compare chain
    0x80: ("MRCD", 1250),    # follows X by choice, not by evidence
}


def period_for(code, clock=TIMER_CLOCK):
    """Proposed mapping. Unknown band -> stock period, so behaviour is unchanged."""
    if code not in BANDS:
        return STOCK_PERIOD
    d = int(round(clock / BANDS[code][1]))
    return d if 8 <= d <= 0xFFFF else STOCK_PERIOD


class Sounder:
    """Model of 0xFFF93BCF with a programmable period and an arm flag."""

    def __init__(self, code, clock=TIMER_CLOCK, double=False):
        self.band = code
        self.clock = clock
        self.double = double
        self.state = 0
        self.counter = 0
        self.one_shot = 0          # 120[0x4C5D4]
        self.armed = False         # bit 5 of 0xAEB6
        self.pin = False
        self.running = False
        self.period = STOCK_PERIOD
        self.log = []              # (t_ms, "on"|"off", period)

    def arm(self):
        self.armed = True

    def tone(self, t):
        self.period = period_for(self.band, self.clock)
        self.running = True
        self.pin = True
        self.log.append((t, "on", self.period))

    def stop(self, t):
        self.running = False
        self.log.append((t, "off", self.period))

    def tick(self, t):
        if not self.armed:          # gate B: engine returns, state frozen
            return
        self.counter += 1
        s = self.state
        if s == 0:
            self.one_shot = 1
            self.pin = True
            self.state = 1
        elif s == 1:
            self.tone(t)
            self.counter = 0
            self.state = 2
        elif s == 2:
            if self.counter == ON_MS:
                self.stop(t)
                self.counter = 0
                if self.double:
                    self.state = 3
                else:
                    self.one_shot = 0
                    self.armed = False      # bclr #5
                    self.state = 0
        elif s == 3:
            if self.counter == GAP_MS:
                self.counter = 0
                self.state = 4
        elif s == 4:
            self.tone(t)
            self.counter = 0
            self.state = 5
        elif s == 5:
            if self.counter == ON_MS:
                self.stop(t)
                self.one_shot = 0
                self.armed = False          # bclr #5
                self.state = 0


def run(code, ms=400, clock=TIMER_CLOCK, rate=48000, double=False, rearm_ms=GAP_MS):
    """Simulate the engine plus the external re-arm loop; return per-ms state."""
    s = Sounder(code, clock=clock, double=double)
    s.arm()
    frames = []                                  # (tone_on, period)
    next_arm = None
    for t in range(ms):
        s.tick(t)
        if not s.armed and s.state == 0:
            if next_arm is None:
                next_arm = t + rearm_ms
            if t >= next_arm:
                s.arm()
                next_arm = None
        frames.append((s.pin and s.running, s.period))
    return frames, s


def pwm(frames, clock, rate):
    """Gate a 50 %-duty square wave of the current period into the frame plan."""
    dur = rate // 1000
    buf = []
    phase = 0.0
    for on, period in frames:
        if not on:
            phase = 0.0
            buf.extend([0.0] * dur)
            continue
        half = period / 2.0
        for _ in range(dur):
            phase += clock / rate
            if phase >= period:
                phase -= period
            buf.append(1.0 if phase < half else -1.0)
    return buf


def measure(samples, rate):
    """Fundamental of the first burst, from rising zero crossings."""
    rises = []
    prev = False
    for i, v in enumerate(samples):
        now = v > 0
        if now and not prev:
            rises.append(i)
            if len(rises) == 8:
                break
        prev = now
    if len(rises) < 3:
        return 0.0
    span = rises[-1] - rises[0]
    return (len(rises) - 1) * rate / span if span else 0.0


def write_wav(path, samples, rate=48000, amp=8000):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(v * amp)) for v in samples))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="out/bandaware")
    ap.add_argument("--clock", type=int, default=TIMER_CLOCK)
    ap.add_argument("--ms", type=int, default=400)
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--mode", choices=("single", "double"), default="single")
    args = ap.parse_args()
    double = args.mode == "double"
    d = Path(args.dir)
    d.mkdir(parents=True, exist_ok=True)

    print(f"clock {args.clock/1e6:.3f} MHz   mode {args.mode}-pulse   "
          f"cadence 50 on / 30 off (unchanged)")
    print(f"{'file':<24}{'band':<6}{'period':>7}{'target':>8}{'measured':>10}")
    rows = [(c, n, f) for c, (n, f) in BANDS.items() if c != 0x05]
    for code, name, freq in rows:
        frames, _ = run(code, args.ms, args.clock, args.rate, double)
        p = period_for(code, args.clock)
        path = d / f"{name.lower()}_{freq}hz.wav"
        write_wav(path, pwm(frames, args.clock, args.rate), args.rate)
        print(f"{path.name:<24}{name:<6}{p:>7}{freq:>8}{measure(pwm(frames, args.clock, args.rate), args.rate):>10.1f}")

    for tag, code in (("stock_fallback", 0x00), ("unknown_fallback", 0x77)):
        frames, _ = run(code, args.ms, args.clock, args.rate, double)
        path = d / f"{tag}.wav"
        write_wav(path, pwm(frames, args.clock, args.rate), args.rate)
        print(f"{path.name:<24}{'-':<6}{period_for(code, args.clock):>7}{'-':>8}"
              f"{measure(pwm(frames, args.clock, args.rate), args.rate):>10.1f}")

    # cadence evidence straight from the state trace
    frames, s = run(0x30, 400, args.clock, args.rate, double)
    ons = [t for t, w, _ in s.log if w == "on"]
    offs = [t for t, w, _ in s.log if w == "off"]
    print(f"\nswitch times for Ka: on={ons[:4]} off={offs[:4]}")
    if len(ons) >= 2 and offs:
        print(f"burst={offs[0]-ons[0]+1} ms  gap={ons[1]-offs[0]} ms  "
              f"period={ons[1]-ons[0]} ms")


if __name__ == "__main__":
    main()
