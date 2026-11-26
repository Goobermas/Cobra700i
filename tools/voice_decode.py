#!/usr/bin/env python3
"""Decode every voice-bank block once and cache raw PCM + index."""
import struct, json
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


def decode(payload, hi_first=True):
    out = bytearray()
    pred, idx = 0, 0
    for byte in payload:
        for nib in ((byte >> 4, byte & 0xF) if hi_first else (byte & 0xF, byte >> 4)):
            step = STEP[idx]
            diff = step >> 3
            if nib & 1: diff += step >> 2
            if nib & 2: diff += step >> 1
            if nib & 4: diff += step
            pred = pred - diff if nib & 8 else pred + diff
            if pred > 32767: pred = 32767
            elif pred < -32768: pred = -32768
            idx = max(0, min(88, idx + IDXADJ[nib & 7]))
            out += struct.pack("<h", pred)
    return bytes(out)


def main():
    d = SRC.read_bytes()
    n = (0x4F4 - 0x20) // 4
    tab = [struct.unpack(">I", d[0x20+4*i:0x24+4*i])[0] for i in range(n)]
    pcm = bytearray()
    index = []
    for i in range(n - 1):
        start, end = tab[i], tab[i+1]
        if start + 4 > len(d):
            break
        ln = struct.unpack(">I", d[start:start+4])[0]
        payload = d[start+4:min(start+4+ln, len(d))]
        p = decode(payload)
        index.append({"idx": i, "off": start, "payload": len(payload),
                      "pcm_off": len(pcm), "pcm_len": len(p),
                      "nsamp": len(p)//2})
        pcm += p
    (OUT / "voice.pcm").write_bytes(bytes(pcm))
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
    print(f"decoded {len(index)} blocks -> {len(pcm)} PCM bytes "
          f"({len(pcm)//2} samples)")


if __name__ == "__main__":
    main()
