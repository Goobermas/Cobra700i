#!/usr/bin/env python3
"""Design replacement radar alert tones (Uniden R7/R8 character) and render
offline previews, including signal-strength-dependent cadence.

These tones are DESIGNED approximations of the R7/R8 alert character
(distinct pitch per band, fast Ka warble, laser staccato). They are not
derived from measured Uniden samples.

Also contains an IMA ADPCM encoder that exactly matches the decoder in
tools/voice_decode.py (high nibble first, initial predictor/index 0), so a
tone can be re-embedded in the voice bank at identical byte length.
"""
import math, struct, wave, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "tones"
OUT.mkdir(parents=True, exist_ok=True)

FS = 8000          # playback rate assumed for the voice bank
SLOT_SAMPLES = 1112  # 556 ADPCM bytes -> 1112 samples (existing beep size)

# Band definitions. Frequencies are deliberately kept inside the band the
# voice bank's 4-bit ADPCM stream can carry at 8 kHz: a *sine* is narrowband
# and survives the codec, whereas a high-frequency square wave (harmonic-
# rich, near Nyquist) does not. Measured during verification.
BANDS = {
    "X":    dict(f0=800,  f1=800,  warble_hz=0,  style="clean"),
    "K":    dict(f0=1050, f1=1050, warble_hz=0,  style="clean"),
    "Ka":   dict(f0=1400, f1=1700, warble_hz=30, style="warble"),
    "LASER": dict(f0=2100, f1=2100, warble_hz=80, style="staccato"),
}

# signal strength 1..8 -> seconds between beeps (stronger = faster)
SSM_INTERVAL = {1: 0.90, 2: 0.72, 3: 0.56, 4: 0.42,
                5: 0.32, 6: 0.24, 7: 0.17, 8: 0.11}


def render_tone(band, n=SLOT_SAMPLES, fs=FS):
    """Render one beep of n samples. Square-ish with slight low-pass for the
    'electronic' R-series character; Ka warbles, laser is staccato."""
    b = BANDS[band]
    out = []
    phase = 0.0
    for i in range(n):
        t = i / fs
        if b["style"] == "warble":
            f = b["f0"] + (b["f1"] - b["f0"]) * (0.5 - 0.5 *
                                                 math.cos(2 * math.pi * b["warble_hz"] * t))
        else:
            f = b["f0"]
        phase += 2 * math.pi * f / fs
        v = math.sin(phase)
        # a touch of 3rd harmonic gives the 'electronic' bite, but only when
        # it stays below the codec's usable band
        if 3 * f < 3400:
            v = 0.82 * v + 0.18 * math.sin(3 * phase)
        if b["style"] == "staccato":
            gate = 1.0 if (t * b["warble_hz"]) % 1.0 < 0.55 else 0.0
            v *= gate
        out.append(v * 0.72)
    # short raised-cosine attack/release to avoid clicks
    a = int(0.004 * fs)
    for i in range(min(a, n // 2)):
        g = 0.5 - 0.5 * math.cos(math.pi * i / a)
        out[i] *= g
        out[n - 1 - i] *= g
    return out


def to_pcm16(x):
    return [max(-32768, min(32767, int(round(v * 32767)))) for v in x]


def write_wav(path, samples, fs=FS):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))


STEP = [7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,
        73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,
        408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,
        1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,
        7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,
        22385,24623,27086,29794,32767]
IDXADJ = [-1,-1,-1,-1,2,4,6,8]


def ima_encode(samples, nbytes):
    """Encode to exactly nbytes. Matches decoder: hi nibble first,
    predictor/index start at 0, no header."""
    pred, idx = 0, 0
    nibs = []
    for s in samples:
        step = STEP[idx]
        diff = s - pred
        sign = 8 if diff < 0 else 0
        d = -diff if diff < 0 else diff
        nib = 0
        if d >= step:
            nib |= 4; d -= step
        if d >= (step >> 1):
            nib |= 2; d -= step >> 1
        if d >= (step >> 2):
            nib |= 1
        q = step >> 3
        if nib & 1: q += step >> 2
        if nib & 2: q += step >> 1
        if nib & 4: q += step
        # NOTE: the sign lives in `sign`, not in `nib` (it is OR-ed in only
        # when the nibble is emitted), so the reconstruction must test
        # `sign`, not `nib & 8`. Testing `nib & 8` made the encoder's
        # predictor monotonically increasing and made every stream diverge.
        pred = pred - q if sign else pred + q
        pred = max(-32768, min(32767, pred))
        idx = max(0, min(88, idx + IDXADJ[nib & 7]))
        nibs.append(nib | sign)
    out = bytearray()
    for i in range(0, len(nibs), 2):
        hi = nibs[i]
        lo = nibs[i+1] if i+1 < len(nibs) else 0
        out.append((hi << 4) | (lo & 0xF))
    out = bytes(out[:nbytes])
    if len(out) < nbytes:
        out += b"\x00" * (nbytes - len(out))
    return out


def ima_decode(payload):
    out = []
    pred, idx = 0, 0
    for byte in payload:
        for nib in (byte >> 4, byte & 0xF):
            step = STEP[idx]
            d = step >> 3
            if nib & 1: d += step >> 2
            if nib & 2: d += step >> 1
            if nib & 4: d += step
            pred = pred - d if nib & 8 else pred + d
            pred = max(-32768, min(32767, pred))
            idx = max(0, min(88, idx + IDXADJ[nib & 7]))
            out.append(pred)
    return out


def main():
    manifest = {}
    for band in BANDS:
        pcm = to_pcm16(render_tone(band))
        write_wav(OUT / f"beep_{band}.wav", pcm)
        enc = ima_encode(pcm, 556)
        dec = ima_decode(enc)
        write_wav(OUT / f"beep_{band}_adpcm_roundtrip.wav", dec)
        manifest[band] = {"samples": len(pcm), "adpcm_bytes": len(enc),
                          "sha256": __import__("hashlib").sha256(enc).hexdigest()}

    # full alert preview per band at a few signal strengths
    for band in BANDS:
        for ssm in (2, 5, 8):
            gap = SSM_INTERVAL[ssm]
            beep = to_pcm16(render_tone(band))
            total = int(FS * 2.0)
            buf = [0] * total
            pos = 0
            while pos < total:
                for i, s in enumerate(beep):
                    if pos + i < total:
                        buf[pos + i] = s
                pos += int(gap * FS)
            write_wav(OUT / f"alert_{band}_ssm{ssm}.wav", buf)

    (OUT / "tone_manifest.json").write_text(json.dumps(manifest, indent=1))
    print("bands:", list(BANDS))
    print("beep length: %d samples (%.0f ms @ %d Hz), 556 ADPCm bytes"
          % (SLOT_SAMPLES, 1000 * SLOT_SAMPLES / FS, FS))
    print("cadence (SSM->interval):", SSM_INTERVAL)
    print("wrote WAVs to out/tones/")


if __name__ == "__main__":
    main()
