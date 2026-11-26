#!/usr/bin/env python3
"""Spectral classification of the decoded voice bank.

A stored electronic beep is quasi-stationary and narrowband: high energy
concentration in a few FFT bins, low spectral flatness, and a dominant
frequency that barely moves between frames. Speech is the opposite.
"""
import json, hashlib, struct
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
V = ROOT / "work" / "voice"
FS = 8000


def features(s):
    n = len(s)
    if n < 256:
        return None
    x = s.astype(np.float64)
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 1.0:
        return {"flat": 1.0, "conc": 0.0, "f0": 0.0, "f0cv": 9.9,
                "rms": rms, "n": n}
    W = 512
    frames = [x[i:i+W] for i in range(0, max(1, n-W+1), W)]
    if not frames:
        frames = [x[:W]] if n >= W else [np.pad(x, (0, W-n))]
    concs, flats, f0s = [], [], []
    for f in frames:
        f = f - f.mean()
        if len(f) < W:
            f = np.pad(f, (0, W-len(f)))
        w = f * np.hanning(W)
        P = np.abs(np.fft.rfft(w)) ** 2
        P = P[1:]  # drop DC
        tot = P.sum()
        if tot <= 1e-9:
            continue
        k = int(np.argmax(P))
        # energy within +-1 bin of the peak
        lo, hi = max(0, k-1), min(len(P), k+2)
        concs.append(float(P[lo:hi].sum() / tot))
        flats.append(float(np.exp(np.mean(np.log(P + 1e-12))) /
                           (np.mean(P) + 1e-12)))
        f0s.append((k+1) * FS / W)
    if not concs:
        return None
    f0s = np.array(f0s)
    # only consider frames that are actually loud
    return {"flat": float(np.median(flats)),
            "conc": float(np.median(concs)),
            "f0": float(np.median(f0s)),
            "f0cv": float(np.std(f0s)/(np.mean(f0s)+1e-9)),
            "rms": rms, "n": n, "nfr": len(f0s)}


def main():
    pcm = np.frombuffer((V / "voice.pcm").read_bytes(), dtype="<i2")
    idx = json.loads((V / "index.json").read_text())
    rows = []
    hashes = {}
    for e in idx:
        s = pcm[e["pcm_off"]//2:(e["pcm_off"]+e["pcm_len"])//2]
        f = features(s)
        if not f:
            continue
        h = hashlib.md5(s.tobytes()).hexdigest()[:12]
        hashes.setdefault(h, []).append(e["idx"])
        f.update(idx=e["idx"], off=e["off"], payload=e["payload"], dup=h,
                 dur=e["nsamp"]/FS)
        rows.append(f)

    dups = {h: v for h, v in hashes.items() if len(v) > 1}
    print(f"clips: {len(rows)}   distinct payloads: {len(hashes)}   "
          f"duplicate groups: {len(dups)}")
    print("duplicate groups:", list(dups.values())[:10])

    # tone score: narrowband + stable + concentrated
    for r in rows:
        r["tone"] = (r["conc"] * (1.0 - min(1.0, r["flat"] * 10)) *
                     (1.0 / (1.0 + 6 * r["f0cv"])))
    rows.sort(key=lambda r: -r["tone"])
    print(f"\n{'idx':>3} {'off':>8} {'durs':>6} {'f0Hz':>7} {'conc':>5} "
          f"{'flat':>8} {'f0cv':>5} {'rms':>6} tone")
    for r in rows[:28]:
        print(f"{r['idx']:3d} 0x{r['off']:06X} {r['dur']:6.2f} {r['f0']:7.1f} "
              f"{r['conc']:5.2f} {r['flat']:8.4f} {r['f0cv']:5.2f} "
              f"{r['rms']:6.0f} {r['tone']:.3f}")

    with open(V / "features.csv", "w") as f:
        f.write("idx,off,payload,dur_s,f0_hz,conc,flat,f0cv,rms,tone,dup\n")
        for r in rows:
            f.write(f"{r['idx']},0x{r['off']:06X},{r['payload']},{r['dur']:.3f},"
                    f"{r['f0']:.1f},{r['conc']:.4f},{r['flat']:.6f},"
                    f"{r['f0cv']:.4f},{r['rms']:.1f},{r['tone']:.4f},{r['dup']}\n")

    # write WAVs of the best candidates
    import wave
    for rank, r in enumerate(rows[:16]):
        e = idx[r["idx"]]
        s = pcm[e["pcm_off"]//2:(e["pcm_off"]+e["pcm_len"])//2]
        with wave.open(str(V / f"cand_{rank:02d}_idx{r['idx']:03d}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(FS)
            w.writeframes(s.astype("<i2").tobytes())
    print("\nwrote 16 candidate WAVs + features.csv in work/voice/")


if __name__ == "__main__":
    main()
