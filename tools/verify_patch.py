#!/usr/bin/env python3
"""Verify (a) the ADPCM encoder/decoder round-trip, (b) that each designed
tone survives the codec at the intended carrier, and (c) patch integrity.

Run:  python3 tools/verify_patch.py
Exit status 0 = all checks passed.
"""
import sys, json, math, hashlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from tonegen import (render_tone, to_pcm16, ima_encode, ima_decode,
                     BANDS, FS, SLOT_SAMPLES)

fails = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def peak(sig, fs=FS, half=2):
    """Dominant frequency and energy concentration.

    The FFT is NOT zero-padded: zero-padding spreads a tone's mainlobe over
    thousands of bins and makes any concentration figure meaningless. With
    n-point FFT the resolution is fs/n, so +-`half` bins is a few tens of Hz.
    """
    x = np.asarray(sig, dtype=float)
    x = x - x.mean()
    n = len(x)
    F = np.abs(np.fft.rfft(x * np.hanning(n)))
    P = F ** 2
    k = int(np.argmax(P[1:])) + 1
    f = k * fs / n
    conc = P[max(0, k-half):k+half+1].sum() / (P[1:].sum() + 1e-12)
    return f, float(conc)


def main():
    print("=== 1. codec round-trip ===")
    for band, b in BANDS.items():
        pcm = to_pcm16(render_tone(band, n=SLOT_SAMPLES))
        enc = ima_encode(pcm, 556)
        dec = ima_decode(enc)
        f_in, _ = peak(pcm)
        f_out, conc = peak(dec)
        if b["style"] == "warble":
            # a modulated tone is intentionally spread over f0..f1, so score
            # in-band energy rather than single-bin concentration
            x = np.asarray(dec, float); x -= x.mean()
            P = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
            fr = np.fft.rfftfreq(len(x), 1 / FS)
            lo, hi = b["f0"] - 80, b["f1"] + 80
            inband = P[(fr >= lo) & (fr <= hi)].sum() / (P[1:].sum() + 1e-12)
            ok = inband > 0.55
            check(f"{band}: warble stays in {b['f0']}-{b['f1']} Hz", ok,
                  f"in-band energy {100*inband:.0f}%, peak {f_out:.0f}Hz")
        else:
            target = b["f0"]
            ok = abs(f_out - target) <= 60 and conc > 0.35
            check(f"{band}: carrier survives ADPCM", ok,
                  f"wanted {target}Hz got {f_out:.0f}Hz conc={conc:.2f}")

    print("\n=== 2. codec envelope sweep (documented limitation) ===")
    print(f"{'freq':>6} {'amp':>5} {'peak_out':>9} {'conc':>6}")
    for f in (400, 600, 800, 1050, 1400, 1750, 2100, 2600, 3200):
        for amp in (0.4, 0.7):
            n = SLOT_SAMPLES
            sig = [amp * 32767 * math.sin(2*math.pi*f*i/FS) for i in range(n)]
            pcm = [int(x) for x in sig]
            dec = ima_decode(ima_encode(pcm, 556))
            fo, c = peak(dec)
            print(f"{f:6d} {amp:5.1f} {fo:9.0f} {c:6.2f}")

    print("\n=== 3. patch integrity ===")
    for band in BANDS:
        p = ROOT / "out" / f"RAD_700i_V1.2.0.1_tonepatched_{band}.bin"
        if not p.exists():
            check(f"{band}: patched image exists", False, str(p)); continue
        man = json.loads((ROOT / "out" / f"patch_manifest_{band}.json").read_text())
        data = p.read_bytes()
        check(f"{band}: size preserved", len(data) == man["size_delta"] + len(
            (ROOT / "RAD_700i_V1.2.0.1.bin").read_bytes()))
        check(f"{band}: sha256 matches manifest",
              hashlib.sha256(data).hexdigest() == man["output_sha256"])
        check(f"{band}: no stray byte changes",
              man["verification"]["stray_changes"] == 0,
              f"{man['verification']['changed_bytes']} bytes changed")

    print()
    if fails:
        print("FAILED:", fails)
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
