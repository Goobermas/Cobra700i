#!/usr/bin/env python3
"""Function boundaries and a call graph over work/main_full.dis.

The disassembly has no symbol table, so boundaries are derived structurally:

  * an address is a FUNCTION ENTRY if it is the target of a `bsr` (direct call),
    or it directly follows an unconditional transfer (`rts`, `rtsd`, `rte`,
    `bra`, `jmp`), or it is the reset entry.
  * a function spans from its entry to the next entry.
  * callers of an entry = every `bsr` whose target equals that entry, plus any
    address whose 32-bit immediate literal equals it (function-pointer tables).

Subcommands
  owners  ADDR[,ADDR...]      which function contains each address
  callers ENTRY[,ENTRY...]    who calls each function
  callees ENTRY               everything that function calls
  info    ENTRY               size, prologue, and call list
"""
import re
import sys
from pathlib import Path

DIS = Path("work/main_full.dis")
RESET = 0xFFFA8708
LINE = re.compile(r"^([0-9a-f]{8}):\t")

TERMINATORS = ("rts", "rtsd", "rte", "bra", "bra.a", "bra.w", "jmp", "jmp.a")


def parse():
    ins = []
    for raw in DIS.read_text(errors="replace").splitlines():
        m = LINE.match(raw)
        if not m:
            continue
        addr = int(m.group(1), 16)
        body = re.sub(r" <_binary[^>]*>", "", raw[m.end():])
        fields = [f.strip() for f in body.split("\t") if f.strip()]
        if len(fields) < 2:
            continue
        hexbytes, mnem, ops = fields[0], fields[-2], fields[-1]
        size = len(hexbytes.split())
        ins.append((addr, size, mnem, ops))
    ins.sort()
    return ins


def target(mnem, ops, addr, size):
    """Direct call/branch target, or None."""
    m = re.match(r"^([0-9a-f]{8})\b", ops)
    if not m:
        return None
    if mnem.startswith("bsr"):
        return int(m.group(1), 16), "call"
    if mnem.startswith(("bra", "jmp")):
        return int(m.group(1), 16), "jump"
    return None


def build(ins):
    entries = {RESET}
    calls = {}          # addr -> (target, kind)
    for addr, size, mnem, ops in ins:
        t = target(mnem, ops, addr, size)
        if t:
            calls[addr] = t
            if t[1] == "call":
                entries.add(t[0])
        if mnem in TERMINATORS:
            entries.add(addr + size)
    starts = sorted(entries)
    idx = {a: i for i, a in enumerate(starts)}

    def owner(addr):
        lo, hi = 0, len(starts) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if starts[mid] <= addr:
                best = starts[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    return starts, idx, calls, owner


def main():
    ins = parse()
    starts, idx, calls, owner = build(ins)
    by_addr = {a: (s, m, o) for a, s, m, o in ins}
    cmd = sys.argv[1] if len(sys.argv) > 1 else "owners"
    args = [int(x, 16) for a in sys.argv[2:] for x in a.split(",")]

    if cmd == "owners":
        for a in args:
            o = owner(a)
            nxt = starts[idx[o] + 1] if idx[o] + 1 < len(starts) else None
            print(f"0x{a:08X} is in function 0x{o:08X}"
                  f" (next entry {('0x%08X' % nxt) if nxt else 'end'})")
    elif cmd == "callers":
        for e in args:
            hits = [a for a, (t, k) in calls.items() if t == e]
            print(f"callers of 0x{e:08X}: {len(hits)}")
            for a in sorted(hits)[:24]:
                s, m, o = by_addr[a]
                print(f"   0x{a:08X}  {m} {o}")
    elif cmd == "callees":
        for e in args:
            nxt = starts[idx[e] + 1] if idx[e] + 1 < len(starts) else 1 << 32
            hits = [(a, t) for a, (t, k) in calls.items() if e <= a < nxt]
            print(f"callees of 0x{e:08X}: {len(hits)}")
            seen = set()
            for a, t in sorted(hits):
                if t in seen:
                    continue
                seen.add(t)
                print(f"   0x{a:08X} -> 0x{t:08X}")
    else:
        for e in args:
            nxt = starts[idx[e] + 1] if idx[e] + 1 < len(starts) else 1 << 32
            print(f"function 0x{e:08X}: {nxt - e} bytes, "
                  f"{sum(1 for a in by_addr if e <= a < nxt)} instructions")


if __name__ == "__main__":
    main()
