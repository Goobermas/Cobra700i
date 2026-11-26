#!/usr/bin/env python3
"""RAD 700i voice bank analyser.

Parses the V1.2.0.1 container (offset table + [u32 BE len][payload] blocks),
decodes the nibble ADPCM payloads with the standard IMA/DVI scheme, and
classifies each clip as tone-like (electronic beep) vs speech-like using
autocorrelation periodicity and envelope statistics.

Pure-stdlib fallback; uses numpy when present for speed.
"""
import struct, math, sys, wave, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "RAD_700i_V1.2.0.1.bin"
OUT = ROOT / "work" / "voice"
OUT.mkdir(parents=True, exist_ok=True)

STEP = [7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,
        73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,
        408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,
        1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,
        7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,
        22385,24623,27086,29794,32767]
IDXADJ = [-1,-1,-1,-1,2,4,6,8]


def parse(path):
    d = path.read_bytes()
    n = (0x4F4 - 0x20) // 4
    tab = [struct.unpack(">I", d[0x20+4*i:0x24+4*i])[0] for i in range(n)]
    blocks = []
    for i in range(n - 1):
        start, end = tab[i], tab[i+1]
        if start + 4 > len(d):
            break
        ln = struct.unpack(">I", d[start:start+4])[0]
        payload = d[start+4:min(start+4+ln, len(d))]
        blocks.append({"idx": i, "off": start, "declared": ln,
                       "payload": payload})
    return d, tab, blocks


def decode_ima(payload, hi_first=False, init_pred=0, init_idx=0,
               header=False):
    """Decode 4-bit IMA ADPCM. Returns list of signed 16-bit samples."""
    p = payload
    if header:
        if len(p) < 4:
            return []
        init_pred = struct.unpack("<h", p[0:2])[0]
        init_idx = min(p[2], 88)
        p = p[4:]
    out = []
    pred = init_pred
    idx = init_idx
    for byte in p:
        nibs = (byte >> 4, byte & 0x0F) if hi_first else (byte & 0x0F, byte >> 4)
        for nib in nibs:
            step = STEP[idx]
            diff = step >> 3
            if nib & 1: diff += step >> 2
            if nib & 2: diff += step >> 1
            if nib & 4: diff += step
            if nib & 8: pred -= diff
            else:        pred += diff
            if pred > 32767: pred = 32767
            elif pred < -32768: pred = -32768
            idx += IDXADJ[nib & 7]
            if idx < 0: idx = 0
            elif idx > 88: idx = 88
            out.append(pred)
    return out


def stats(s):
    n = len(s)
    if n < 32:
        return None
    mean = sum(s)/n
    var = sum((x-mean)**2 for x in s)/n
    rms = math.sqrt(var)
    zc = sum(1 for i in range(1, n) if (s[i-1] < 0) != (s[i] < 0))
    # envelope variance over 64-sample windows
    env = []
    W = 64
    for i in range(0, n-W, W):
        env.append(math.sqrt(sum(x*x for x in s[i:i+W])/W))
    e_mean = sum(env)/len(env) if env else 0
    e_var = (sum((e-e_mean)**2 for e in env)/len(env)) if env else 0
    # autocorrelation pitch search on a central 512-sample window
    c = n//2
    a = s[max(0, c-256):max(0, c-256)+512]
    m = sum(a)/len(a)
    a = [x-m for x in a]
    best_lag, best_r = 0, 0.0
    energy = sum(x*x for x in a) or 1.0
    for lag in range(8, min(400, len(a)-1)):
        r = sum(a[i]*a[i+lag] for i in range(len(a)-lag))
        r /= energy
        if r > best_r:
            best_r, best_lag = r, lag
    return {"n": n, "rms": rms, "peak": max(abs(x) for x in s), "zcr": zc/n,
            "env_cv": (math.sqrt(e_var)/e_mean) if e_mean else 99.0,
            "periodic": best_r, "lag": best_lag}


def write_wav(path, samples, fs):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs)
        w.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, x)))
                               for x in samples))


def main():
    d, tab, blocks = parse(SRC)
    print(f"container: {len(blocks)} blocks, file {len(d)} bytes")
    # choose decode variant by minimising clipped samples across a sample set
    probes = blocks[::37][:8]
    variants = []
    for name, kw in [("lo-first,no-hdr", dict(hi_first=False)),
                     ("hi-first,no-hdr", dict(hi_first=True)),
                     ("lo-first,hdr4", dict(hi_first=False, header=True)),
                     ("hi-first,hdr4", dict(hi_first=True, header=True))]:
        clip = tot = 0
        for b in probes:
            s = decode_ima(b["payload"], **kw)
            clip += sum(1 for x in s if x in (32767, -32768))
            tot += len(s)
        variants.append((clip/tot if tot else 1, name, kw))
        print(f"  variant {name:18s} clipped={100*clip/tot:6.2f}%")
    variants.sort()
    _, vname, vkw = variants[0]
    print(f"selected decode variant: {vname}")

    fs = 8000
    rows = []
    for b in blocks:
        s = decode_ima(b["payload"], **vkw)
        st = stats(s)
        if not st:
            continue
        st.update(idx=b["idx"], off=b["off"], bytes=len(b["payload"]),
                  dur=len(s)/fs)
        rows.append((st, s))

    rows.sort(key=lambda r: -r[0]["periodic"])
    print(f"\n{'idx':>3} {'offset':>8} {'bytes':>6} {'sec@8k':>6} {'rms':>6} "
          f"{'zcr':>6} {'per':>5} {'envCV':>6} {'f0(Hz)':>7}")
    for st, s in rows[:30]:
        f0 = fs/st["lag"] if st["lag"] else 0
        print(f"{st['idx']:3d} 0x{st['off']:06X} {st['bytes']:6d} "
              f"{st['dur']:6.2f} {st['rms']:6.0f} {st['zcr']:6.3f} "
              f"{st['periodic']:5.2f} {st['env_cv']:6.2f} {f0:7.1f}")

    # export the most tone-like and a few speech-like for listening
    tone = [r for r in rows if r[0]["periodic"] > 0.75 and r[0]["dur"] < 1.2]
    print(f"\ntone-like candidates (periodic>0.75, <1.2s): {len(tone)}")
    for st, s in tone[:24]:
        write_wav(OUT / f"tone_{st['idx']:03d}.wav", s, fs)
    for st, s in rows[-4:]:
        write_wav(OUT / f"speech_{st['idx']:03d}.wav", s, fs)
    print("wrote WAVs to work/voice/")


if __name__ == "__main__":
    main()
