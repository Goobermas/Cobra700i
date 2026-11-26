#!/usr/bin/env python3
"""Scan a flat firmware image: strings, pointer literals, and pointer tables.

Three techniques used throughout the analysis, made reproducible:

  strings   find printable strings, optionally filtered by keyword
  ptrs      find little-endian 32-bit literals equal to an address
            (a data-table entry pointing at a string, or a mov.l immediate)
  table     dump N words from an address, annotating any word that points at a
            printable string in the same image

Usage:
  image_scan.py strings IMAGE [--kw WORD[,WORD...]] [--min N]
  image_scan.py ptrs    IMAGE ADDR[,ADDR...]
  image_scan.py table   IMAGE ADDR [COUNT]

Addresses may be hex with or without 0x. IMAGE is a flat binary; --base sets the
address the first byte represents (default 0xFFF00000).
"""
import argparse
import re
import struct
import sys
from pathlib import Path

STR = re.compile(rb"[ -~]{4,}")


def load(path, base):
    return Path(path).read_bytes(), base


def printable_at(img, off):
    if not (0 <= off < len(img) - 4):
        return None
    s = img[off:off + 64].split(b"\x00")[0]
    if len(s) >= 3 and all(32 <= c < 127 for c in s):
        return s.decode("latin1")
    return None


def cmd_strings(img, base, kw, minlen):
    hits = 0
    for m in STR.finditer(img):
        s = m.group().decode("latin1")
        if len(s) < minlen:
            continue
        if kw and not any(k in s for k in kw):
            continue
        print(f"0x{base + m.start():08X}  {s[:90]}")
        hits += 1
    print(f"-- {hits} match(es)", file=sys.stderr)


def cmd_ptrs(img, base, addrs):
    for a in addrs:
        lit = struct.pack("<I", a)
        i, found = 0, []
        while True:
            i = img.find(lit, i)
            if i < 0:
                break
            found.append(base + i)
            i += 1
        where = " ".join(f"0x{x:08X}" for x in found[:12]) or "(none)"
        print(f"0x{a:08X} referenced from: {where}")


def cmd_table(img, base, addr, count):
    for k in range(count):
        a = addr + 4 * k
        w = struct.unpack_from("<I", img, a - base)[0]
        note = ""
        t = printable_at(img, w - base)
        if t:
            note = f"  -> {t[:48]!r}"
        print(f"  0x{a:08X}  {w:08X}{note}")


def num(s):
    return int(s, 16) if not s.lower().startswith("0x") else int(s, 16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("strings", "ptrs", "table"))
    ap.add_argument("image")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--base", default="0xFFF00000")
    ap.add_argument("--kw", default="")
    ap.add_argument("--min", type=int, default=5)
    ns = ap.parse_args()

    base = int(ns.base, 16)
    img, base = load(ns.image, base)

    if ns.cmd == "strings":
        kw = [k for k in ns.kw.split(",") if k]
        cmd_strings(img, base, kw, ns.min)
    elif ns.cmd == "ptrs":
        addrs = [int(x, 16) for a in ns.args for x in a.split(",")]
        cmd_ptrs(img, base, addrs)
    else:
        if not ns.args:
            ap.error("table needs an address")
        addr = int(ns.args[0], 16)
        count = int(ns.args[1], 0) if len(ns.args) > 1 else 8
        cmd_table(img, base, addr, count)


if __name__ == "__main__":
    main()
