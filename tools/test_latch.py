#!/usr/bin/env python3
"""Design and verify the band latch trampoline for the four record arms.

Sites (inside the record-aging routine at 0xFFF866B9):
    0xFFF8681E  X    band 0x10
    0xFFF8684C  K    band 0x20
    0xFFF86879  Ka   band 0x30 (also 0x05 on the same arm)
    0xFFF868A6  MRCD band 0x80

Each site holds `mov.l 20[r1], 4[r0]` = e5 10 05 01, exactly four bytes, so it can
be replaced by a `bsr.a` to a shared trampoline.

The trampoline must reproduce that store and additionally capture the band:

    e5 10 05 01      mov.l 20[r1], 4[r0]     <- the displaced instruction, verbatim
    ec 1e            mov.l [r1], r14         <- band = record dword 0 (re-read on purpose)
    fb 12 33 b0 03 00 mov.l #0x3b033, r1      <- byte 111 of the 0x3AFC4 object
    c3 1e            mov.b r14, [r1]         <- latch
    02               rts

15 bytes. No arithmetic or compare instruction appears, so PSW is untouched on
RX; no register other than r1 and r14 is written.

Run: python3 tools/test_latch.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rxmini import CPU, assemble_bsr_a  # noqa: E402

BASE = 0xFFF00000
IMAGE = Path("work/main_flat_fff00000.bin")
HOOK = 0xFFFD1040          # after the 57-byte period hook at 0xFFFD1000..0xFFFD1038
LATCH = 0x3B033            # 0x3AFC4 + 111, padding byte of a 112-byte object
ORIG = bytes.fromhex("e5100501")

HOOK_CODE = bytes.fromhex("e5100501" "ec1e" "fb1233b00300" "c31e" "02")

# site, next instruction, address of the bsr.a log call that ends the block, band, name
SITES = [
    (0xFFF8681E, 0xFFF86822, 0xFFF86830, 0x10, "X"),
    (0xFFF8684C, 0xFFF86850, 0xFFF8685E, 0x20, "K"),
    (0xFFF86879, 0xFFF8687D, 0xFFF8688B, 0x30, "Ka"),
    (0xFFF868A6, 0xFFF868AA, 0xFFF868B8, 0x80, "MRCD"),
]

RECORD = 0x20000
SETTLE = 0x30000           # value of SP on entry to the routine
SP_HERE = SETTLE - 20      # SP after `add #-20, r0, r0`, i.e. r0 at the sites

ok = True


def check(cond, msg):
    global ok
    print(("   OK   " if cond else "   FAIL ") + msg)
    if not cond:
        ok = False


def load_image():
    return IMAGE.read_bytes()


def block_bytes(img, lo, hi):
    return img[lo - BASE: hi - BASE]


def make_flash(img):
    flash = {}
    for i, b in enumerate(img):
        flash[BASE + i] = b
    return flash


def setup(cpu, band):
    """Identical starting state for the original and patched runs."""
    cpu.r[0] = SP_HERE
    cpu.r[1] = RECORD
    cpu.r[2] = 0x11
    cpu.r[3] = 0x22
    cpu.r[4] = 0x33
    cpu.r[14] = band
    cpu.r[15] = SP_HERE
    cpu.psw = {"C": 1, "Z": 0, "S": 1, "O": 1, "I": 0}
    for a, v in ((RECORD, band), (RECORD + 20, 0xDEADBEEF), (RECORD + 64, 7),
                 (SETTLE + 4, RECORD), (SP_HERE + 16, 0x11), (SP_HERE + 12, 0x22),
                 (SP_HERE + 8, 0x33)):
        cpu.wl(a, v)


def run_once(img, site, next_pc, call, band, patched, hook=HOOK_CODE):
    flash = make_flash(img)
    if patched:
        for i, b in enumerate(assemble_bsr_a(site, HOOK)):
            flash[site + i] = b
        for i, b in enumerate(hook):
            flash[HOOK + i] = b
    cpu = CPU(flash=flash)
    setup(cpu, band)
    cpu.pc = site
    cpu.run(stop_pcs={call})
    return cpu


def diff_mem(a, b):
    addrs = set(a.mem) | set(b.mem)
    return sorted(x for x in addrs if a.rb(x) != b.rb(x))


def liveness(img):
    """The displaced store must not disturb anything read before it is rewritten."""
    dis = Path("work/main_full.dis").read_text(errors="replace")
    ins = []
    for raw in dis.splitlines():
        m = re.match(r"^([0-9a-f]{8}):\t([0-9a-f ]+)\t+(\S+)(?:\t(.*))?$", raw)
        if m:
            ins.append((int(m.group(1), 16), m.group(3), (m.group(4) or "").strip()))
    print("\n[liveness] dead registers between each site and the log call")
    for site, nxt, call, band, name in SITES:
        window = [(a, t, o) for a, t, o in ins if nxt <= a < call]
        for reg in ("r1", "r2", "r3", "r4", "r14"):
            first = None
            for a, t, o in window:
                toks = [p.strip() for p in o.split(",")] if o else []
                if not any(re.fullmatch(rf"{reg}\b", tok) for tok in toks):
                    continue
                is_dest = toks[-1].endswith(reg) and re.fullmatch(rf"{reg}\b", toks[-1]) is not None
                first = (a, t, o, is_dest)
                break
            if first is None:
                check(True, f"{name} {reg}: never referenced in the window (dead)")
            else:
                a, t, o, is_dest = first
                check(is_dest, f"{name} {reg}: first use at 0x{a:08X} is a write ({t} {o})")


def encoding_checks():
    print("\n[encoding] trampoline bytes decode to the intended instructions")
    flash = {HOOK + i: b for i, b in enumerate(HOOK_CODE)}
    cpu = CPU(flash=flash)
    cpu.r[0], cpu.r[1], cpu.r[14] = SP_HERE, RECORD, 0x10
    cpu.r[15] = SP_HERE - 4              # as if entered by a bsr: PC already pushed
    cpu.wl(SP_HERE - 4, 0xDEAD0000)      # fake return address for rts
    cpu.wl(RECORD, 0x10)
    cpu.wl(RECORD + 20, 0xDEADBEEF)
    cpu.pc = HOOK
    seen = []
    for _ in range(5):
        t = cpu.step()
        seen.append(t)
    check(len(HOOK_CODE) == 15, f"hook is 15 bytes ({len(HOOK_CODE)})")
    check(cpu.rl(SP_HERE + 4) == 0xDEADBEEF, "displaced store reproduced: 4[r0] = 20[r1]")
    check(cpu.rb(LATCH) == 0x10, f"band latched at 0x{LATCH:X} = 0x{cpu.rb(LATCH):02X}")
    check(cpu.r[15] == SP_HERE, f"SP restored after rts (0x{cpu.r[15]:05X})")
    check(cpu.pc == 0xDEAD0000, f"rts returned to the pushed address (0x{cpu.pc:08X})")
    check(not any(t in (0x61, 0x75) for t in seen), "no compare instruction in the hook")


def equivalence(img):
    print("\n[equivalence] original block vs patched block, to the log call")
    for site, nxt, call, band, name in SITES:
        a = run_once(img, site, nxt, call, band, patched=False)
        b = run_once(img, site, nxt, call, band, patched=True)
        ra, rb = list(a.r), list(b.r)
        check(ra == rb, f"{name}: all 16 registers identical {ra if ra != rb else ''}")
        check(a.psw == b.psw, f"{name}: PSW identical {a.psw}")
        check(a.r[15] == b.r[15] == SP_HERE, f"{name}: SP identical and balanced")
        check(a.rl(SP_HERE + 4) == b.rl(SP_HERE + 4) == 0xDEADBEEF,
              f"{name}: argument slot 4[r0] holds record+20 in both")
        push = {SP_HERE - 4, SP_HERE - 3, SP_HERE - 2, SP_HERE - 1}
        d = diff_mem(a, b)
        check(set(d) == {LATCH} | push,
              f"{name}: only differences are the latch byte and the call's 4-byte stack slot"
              f" (got {[hex(x) for x in d]})")
        check(b.rb(LATCH) == band, f"{name}: latched 0x{b.rb(LATCH):02X} == band 0x{band:02X}")


def mutations(img):
    print("\n[mutation] the comparison must fail when behaviour changes")
    site, nxt, call, band, name = SITES[0]
    # (1) omit the displaced store
    broken = HOOK_CODE[4:]
    a = run_once(img, site, nxt, call, band, patched=False)
    b = run_once(img, site, nxt, call, band, patched=True, hook=broken)
    check(a.rl(SP_HERE + 4) != b.rl(SP_HERE + 4), "dropping the copy is detected")
    # (2) hook that performs the store but forgets to latch
    nolatch = bytes.fromhex("e5100501" "02")
    c = run_once(img, site, nxt, call, band, patched=True, hook=nolatch)
    push = {SP_HERE - 4, SP_HERE - 3, SP_HERE - 2, SP_HERE - 1}
    check(set(diff_mem(a, c)) != {LATCH} | push, "dropping the latch is detected")
    check(c.rb(LATCH) != band, f"no latch written (0x{c.rb(LATCH):02X} != 0x{band:02X})")


def displacements():
    print("\n[layout] bsr.a encodings to the shared trampoline")
    table = {}
    for site, nxt, call, band, name in SITES:
        enc = assemble_bsr_a(site, HOOK)
        d = int.from_bytes(enc[1:], "little")
        back = site + 4 + (d if d < 0x800000 else d - 0x1000000)
        table[name] = enc.hex(" ")
        check(back == HOOK, f"{name} 0x{site:08X}: {enc.hex(' ')} -> 0x{back:08X}")
    return table


def main():
    img = load_image()
    print("band latch trampoline: design and equivalence tests")
    print(f"  hook 0x{HOOK:08X}, latch byte 0x{LATCH:08X}")
    print("\n[bytes] every site currently holds the 4-byte displaced instruction")
    for site, nxt, call, band, name in SITES:
        got = block_bytes(img, site, site + 4)
        check(got == ORIG, f"{name} 0x{site:08X}: {got.hex()} == e5100501 "
                           f"(followed by {block_bytes(img, nxt, call).hex(' ')})")
    encoding_checks()
    liveness(img)
    displacements()
    equivalence(img)
    mutations(img)
    print("\nall latch trampoline tests passed" if ok else "\nFAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
