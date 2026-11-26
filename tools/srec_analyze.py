#!/usr/bin/env python3
"""RAD 700i (.mot) S-record parser, validator and segment mapper.

Reads the original Motorola S-record file read-only, validates every record
(type, length, checksum), reports the address-space map and dumps selected
regions. Writes only to work/.
"""
import sys, json, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "RAD_700i_M1.2.4.0.mot"
OUT = ROOT / "work"
OUT.mkdir(exist_ok=True)

LEN_BY_TYPE = {"0": 2, "1": 2, "2": 3, "3": 4, "5": 2, "6": 3, "7": 4,
               "8": 3, "9": 2}


def parse(path):
    recs = []
    bad = []
    counts = collections.Counter()
    for lineno, raw in enumerate(path.read_text("ascii", "replace").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line[0] != "S" or len(line) < 4:
            bad.append((lineno, "not an S-record", raw[:60]))
            continue
        typ = line[1]
        counts[typ] += 1
        try:
            body = bytes.fromhex(line[2:])
        except ValueError:
            bad.append((lineno, "bad hex", raw[:60]))
            continue
        if body[0] + 1 != len(body):
            bad.append((lineno, f"length byte {body[0]} != {len(body)-1}", raw[:60]))
            continue
        if (sum(body) & 0xFF) != 0xFF:
            bad.append((lineno, f"checksum (sum=0x{sum(body)&0xFF:02x})", raw[:60]))
            continue
        abytes = LEN_BY_TYPE.get(typ)
        if abytes is None:
            bad.append((lineno, f"unknown type S{typ}", raw[:60]))
            continue
        addr = int.from_bytes(body[1:1 + abytes], "big")
        data = body[1 + abytes:-1]
        recs.append((typ, addr, data, lineno))
    return recs, bad, counts


def build_image(recs, base=0xFFF00000, size=0x100000):
    img = bytearray(b"\xff" * size)
    covered = bytearray(size)  # 1 = explicitly written by a record
    out_of_range = []
    overlaps = []
    for typ, addr, data, lineno in recs:
        if typ != "3":
            continue
        if not (base <= addr and addr + len(data) <= base + size):
            out_of_range.append((hex(addr), len(data), lineno))
            continue
        off = addr - base
        for i in range(len(data)):
            if covered[off + i]:
                overlaps.append((hex(addr + i), lineno))
            covered[off + i] = 1
            img[off + i] = data[i]
    return img, covered, out_of_range, overlaps


def segments(covered, base=0xFFF00000):
    segs = []
    start = None
    for i, c in enumerate(covered):
        if c and start is None:
            start = i
        elif not c and start is not None:
            segs.append((base + start, base + i))
            start = None
    if start is not None:
        segs.append((base + start, base + len(covered)))
    return segs


def main():
    recs, bad, counts = parse(SRC)
    img, covered, oor, ov = build_image(recs)
    segs = segments(covered)
    written = sum(covered)
    print("=== S-RECORD VALIDATION ===")
    print("records parsed OK :", len(recs))
    print("record types      :", dict(sorted(counts.items())))
    print("invalid records   :", len(bad))
    for b in bad[:10]:
        print("   ", b)
    print("bytes written     :", written, f"of {len(img)} ({100*written/len(img):.1f}% non-0xFF)")
    print("out-of-range recs :", len(oor))
    print("overlapping bytes :", len(ov))

    hdr = [r for r in recs if r[0] == "0"]
    hdr_txt = hdr[0][1:3] if hdr else None
    print("S0 header         :", hdr_txt[1].decode("latin1") if hdr else None)
    starts = [r for r in recs if r[0] in ("7", "8", "9")]
    for t, a, d, l in starts:
        print(f"start address S{t} : 0x{a:08x}")

    print("\n=== ADDRESS SEGMENTS (code flash 0xFFF00000+) ===")
    print(f"{len(segs)} contiguous segments")
    for s, e in segs:
        print(f"  0x{s:08X} - 0x{e:08X}  ({e-s:6d} bytes)")

    reset = int.from_bytes(img[-4:], "little")
    nmi = int.from_bytes(img[-8:-4], "little")
    print(f"\nvector 0xFFFFFFFC (reset) = 0x{reset:08x}")
    print(f"vector 0xFFFFFFF8 (NMI?)  = 0x{nmi:08x}")

    print("\n=== INTERRUPT/EXCEPTION VECTOR TABLE 0xFFFFFF80..0xFFFFFFFF ===")
    for off in range(0xFFFFFF80, 0x100000000, 4):
        v = int.from_bytes(img[off - 0xFFF00000: off - 0xFFF00000 + 4], "little")
        tag = {0xFFFFFFFC: "RESET", 0xFFFFFFF8: "NMI/OSC?"}.get(off, "")
        print(f"  0x{off:08X}: 0x{v:08X} {tag}")

    # save artifacts
    (OUT / "main_flat_fff00000.bin").write_bytes(bytes(img))
    (OUT / "srec_report.json").write_text(json.dumps({
        "records": len(recs), "types": dict(counts), "invalid": len(bad),
        "bytes_written": written, "segments": [[hex(s), hex(e)] for s, e in segs],
        "reset_vector": hex(reset), "start_address": [hex(s[1]) for s in starts],
        "header": hdr_txt[1].decode("latin1") if hdr else None,
    }, indent=2))
    print("\nwrote work/main_flat_fff00000.bin, work/srec_report.json")


if __name__ == "__main__":
    main()
