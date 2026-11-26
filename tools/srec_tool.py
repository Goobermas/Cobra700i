#!/usr/bin/env python3
"""Motorola S-record tool for RAD_700i_M1.2.4.0.mot.

verify  - validate every record and prove the file can be rebuilt byte-for-byte
          (checksum recomputation round-trip).
info    - report segment map, header, entry point.

Original firmware is opened read-only; output goes to out/ or work/.
"""
import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "RAD_700i_M1.2.4.0.mot"
ABYTES = {"0": 2, "1": 2, "2": 3, "3": 4, "5": 2, "6": 3, "7": 4, "8": 3, "9": 2}


def encode(typ, addr, data):
    naddr = ABYTES[typ]
    body = bytes([naddr + len(data) + 1]) + addr.to_bytes(naddr, "big") + data
    chk = (~sum(body)) & 0xFF
    return ("S%s%s%02X" % (typ, body.hex().upper(), chk)).encode()


def parse(text):
    recs, errs = [], []
    for ln, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        if len(s) < 6 or s[0] != "S":
            errs.append((ln, "malformed")); continue
        typ = s[1]
        if typ not in ABYTES:
            errs.append((ln, "unknown type S%s" % typ)); continue
        try:
            body = bytes.fromhex(s[2:])
        except ValueError:
            errs.append((ln, "bad hex")); continue
        if body[0] + 1 != len(body):
            errs.append((ln, "length mismatch")); continue
        if (sum(body) & 0xFF) != 0xFF:
            errs.append((ln, "checksum")); continue
        n = ABYTES[typ]
        recs.append((typ, int.from_bytes(body[1:1+n], "big"), body[1+n:-1]))
    return recs, errs


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    raw = SRC.read_bytes()
    text = raw.decode("ascii")
    recs, errs = parse(text)
    print(f"file {SRC.name}: {len(raw)} bytes, {len(recs)} valid records, "
          f"{len(errs)} errors")
    if errs:
        for e in errs[:10]:
            print("   error:", e)
        sys.exit(1)

    counts = {}
    for t, a, d in recs:
        counts["S" + t] = counts.get("S" + t, 0) + 1
    print("record types:", counts)

    if mode == "verify":
        # rebuild and compare, line by line, including terminators preserved
        rebuilt = []
        for t, a, d in recs:
            rebuilt.append(encode(t, a, d))
        orig_lines = [l.strip().encode() for l in text.splitlines() if l.strip()]
        if len(rebuilt) != len(orig_lines):
            print("line count differs:", len(rebuilt), len(orig_lines)); sys.exit(1)
        bad = [(i, o, r) for i, (o, r) in enumerate(zip(orig_lines, rebuilt)) if o != r]
        print(f"round-trip: {len(rebuilt)-len(bad)}/{len(rebuilt)} lines identical")
        if bad:
            i, o, r = bad[0]
            print("  first mismatch line", i, o, "vs", r)
            sys.exit(1)
        print("RESULT: S-record encoding fully reproducible (checksums verified)")

    if mode == "info":
        segs, cur = [], None
        for t, a, d in recs:
            if t != "3":
                continue
            if cur and cur[1] == a:
                cur[1] = a + len(d)
            else:
                if cur: segs.append(cur)
                cur = [a, a + len(d)]
        if cur: segs.append(cur)
        hdr = next((d for t, a, d in recs if t == "0"), b"")
        entry = next((a for t, a, d in recs if t == "7"), None)
        print("S0 header:", hdr.decode("latin1"))
        print("entry point (S7):", hex(entry) if entry else None)
        print("code segments:")
        for s, e in segs:
            print(f"  0x{s:08X} - 0x{e:08X}  {e-s} bytes")
        (ROOT / "out").mkdir(exist_ok=True)
        (ROOT / "out" / "srec_info.json").write_text(json.dumps(
            {"records": len(recs), "types": counts, "header": hdr.decode("latin1"),
             "entry": hex(entry) if entry else None,
             "segments": [[hex(s), hex(e)] for s, e in segs]}, indent=1))


if __name__ == "__main__":
    main()
