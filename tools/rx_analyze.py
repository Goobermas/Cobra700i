#!/usr/bin/env python3
"""RX firmware analysis: instruction parsing, I/O-space usage, function map.

Inputs (read-only):  work/main_full.dis   (objdump -D of work/main.elf)
Outputs:             work/rx_model.json, work/io_histogram.txt,
                     work/functions.txt
"""
import re, json, collections, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
DIS = WORK / "main_full.dis"
BASE = 0xFFF00000

LINE = re.compile(r"^([0-9a-f]{8,16}):\t([0-9a-f ]+?)\s*\t(.*)$")
HEXCONST = re.compile(r"0x([0-9a-fA-F]+)")

# Renesas RX I/O register space
IO_LO, IO_HI = 0x00080000, 0x00100000


def parse(path):
    insns = []
    for line in path.read_text(errors="replace").splitlines():
        m = LINE.match(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        raw = m.group(2).replace(" ", "")
        text = m.group(3).strip()
        if "\t" in text:
            mn, _, ops = text.partition("\t")
        else:
            parts = text.split(None, 1)
            mn, ops = parts[0], (parts[1] if len(parts) > 1 else "")
        insns.append((addr, raw, mn, ops.strip()))
    return insns


def ioregs(insns):
    """Collect 32-bit immediate constants: I/O space, flash pointers, RAM."""
    io = collections.defaultdict(list)   # addr -> [insn addrs]
    flash = collections.defaultdict(list)
    low = collections.defaultdict(list)
    for addr, raw, mn, ops in insns:
        for h in HEXCONST.findall(ops):
            v = int(h, 16)
            if IO_LO <= v < IO_HI:
                io[v].append(addr)
            elif BASE <= v <= 0xFFFFFFFF:
                flash[v].append(addr)
            elif v < 0x00040000 and v >= 0x1000:
                low[v].append(addr)
    return io, flash, low


def func_starts(insns, io):
    """Function entry points: control-flow targets that land on a decoded insn."""
    addrs = {a for a, *_ in insns}
    starts = collections.Counter()
    for addr, raw, mn, ops in insns:
        if not (mn.startswith("bsr") or mn.startswith("jsr") or
                mn.startswith("bra") or mn.startswith("jmp")):
            continue
        for h in HEXCONST.findall(ops):
            t = int(h, 16)
            if BASE <= t <= 0xFFFFFFFF and t in addrs:
                starts[t] += 1
    return starts, addrs


def build_functions(insns, starts):
    """Assign each instruction to the most recent function start <= it."""
    order = sorted(starts)
    import bisect
    funcs = collections.defaultdict(list)
    for addr, raw, mn, ops in insns:
        i = bisect.bisect_right(order, addr) - 1
        key = order[i] if i >= 0 else None
        funcs[key].append((addr, mn, ops))
    return funcs


def main():
    data = json.loads((WORK / "rx_model.json").read_text()) if (WORK / "rx_model.json").exists() else {}
    insns = parse(DIS)
    print(f"decoded instructions: {len(insns)}")
    io, flash, low = ioregs(insns)
    starts, addrs = func_starts(insns, io)
    funcs = build_functions(insns, starts)

    # Per-function I/O fingerprint
    fmap = {}
    for fstart, body in funcs.items():
        if fstart is None:
            continue
        ios = sorted({int(h, 16) for a, mn, ops in body for h in HEXCONST.findall(ops)
                      if IO_LO <= int(h, 16) < IO_HI})
        if ios:
            fmap[fstart] = ios

    with open(WORK / "io_histogram.txt", "w") as f:
        f.write("distinct I/O addresses referenced with 32-bit immediates: %d\n\n" % len(io))
        for a in sorted(io):
            f.write(f"0x{a:08X}  refs={len(io[a]):3d}  from={[hex(x) for x in io[a][:12]]}\n")

    # cluster I/O addresses into peripheral blocks (0x100 granularity)
    blocks = collections.Counter()
    for a in io:
        blocks[a >> 8 << 8] += 1
    with open(WORK / "io_histogram.txt", "a") as f:
        f.write("\n\n=== 0x100-ALIGNED BLOCKS USED ===\n")
        for b in sorted(blocks):
            f.write(f"block 0x{b:08X}  distinct_regs={blocks[b]}\n")

    with open(WORK / "functions.txt", "w") as f:
        f.write(f"{len(fmap)} functions reference I/O registers\n")
        for fs in sorted(fmap):
            f.write(f"\n--- func 0x{fs:08X}  io={[hex(x) for x in fmap[fs]]}\n")
            for a, mn, ops in funcs[fs][:60]:
                f.write(f"  0x{a:08X}: {mn:10s} {ops}\n")

    (WORK / "rx_model.json").write_text(json.dumps({
        "insn_count": len(insns),
        "io_addrs": {hex(k): len(v) for k, v in io.items()},
        "flash_ptrs": {hex(k): len(v) for k, v in flash.items()},
        "func_count": len(fmap),
        "blocks": {hex(b): c for b, c in blocks.items()},
    }, indent=1))
    print("distinct I/O regs:", len(io))
    print("functions w/ I/O:", len(fmap))
    print("\n=== blocks ===")
    for b in sorted(blocks):
        print(f"  0x{b:08X}  regs={blocks[b]}")


if __name__ == "__main__":
    main()
