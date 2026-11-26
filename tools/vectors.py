#!/usr/bin/env python3
"""Decode the relocated RX interrupt vector table and profile every handler.

INTB was set to 0xFFF57750 by the startup code, so vectors live there.
For each distinct handler we report the I/O registers it touches, which is
how we identify which peripherals the firmware actually drives.
"""
import re, collections, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
IMG = (WORK / "main_flat_fff00000.bin").read_bytes()
BASE = 0xFFF00000
INTB = 0xFFF57750
NVEC = 256

LINE = re.compile(r"^([0-9a-f]{8,16}):\t([0-9a-f ]+?)\s*\t(.*)$")
HEX = re.compile(r"0x([0-9a-fA-F]+)")


def load_dis():
    by_addr = {}
    for line in (WORK / "main_full.dis").read_text(errors="replace").splitlines():
        m = LINE.match(line)
        if not m:
            continue
        a = int(m.group(1), 16)
        nbytes = len(m.group(2).replace(" ", "")) // 2
        by_addr[a] = (nbytes, m.group(3).strip())
    return by_addr


def rd32(a):
    return int.from_bytes(IMG[a - BASE:a - BASE + 4], "little")


def main():
    dis = load_dis()
    vec = []
    for i in range(NVEC):
        v = rd32(INTB + 4 * i)
        vec.append(v)

    handlers = collections.Counter(v for v in vec if 0xFFF00000 <= v <= 0xFFFFFFFF)
    print(f"vector table @0x{INTB:08X}: {len(vec)} entries")
    print(f"distinct handlers: {len(handlers)}\n")

    # walk each handler to the first rts/bra-away, collecting I/O touches
    report = []
    for h, count in handlers.most_common():
        a = h
        ios, sio = [], []
        n = 0
        while n < 60 and a in dis:
            nb, txt = dis[a]
            for x in HEX.findall(txt):
                v = int(x, 16)
                if 0x00080000 <= v < 0x00100000:
                    ios.append((a, v))
            txtm = txt
            sio.append((a, txtm))
            a += nb
            n += 1
            # stop at return / unconditional jump within first block
            mn = txt.split()[0] if txt else ""
            if mn in ("rts", "rtsd") or mn.startswith("bra") or mn.startswith("jmp"):
                break
        regs = sorted({hex(v) for _, v in ios})
        report.append({"handler": h, "nvec": count, "io": regs, "len": n})
        vecs = [i for i, v in enumerate(vec) if v == h]
        print(f"--- handler 0x{h:08X}  vectors={vecs[:14]}{'...' if len(vecs)>14 else ''} "
              f"({len(vecs)} total)")
        if regs:
            print(f"    I/O: {regs}")
        for a2, t in sio[:8]:
            print(f"      0x{a2:08X}: {t}")

    (WORK / "vector_report.json").write_text(json.dumps(
        {"intb": hex(INTB), "vectors": [hex(v) for v in vec], "handlers": report}, indent=1))


if __name__ == "__main__":
    main()
