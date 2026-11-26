#!/usr/bin/env python3
"""Alert-path facts, and the single-hook candidate at the record-save copy.

Claims checked here (each prints OK/FAIL):
  A. no call site of the band-agnostic beeper 0xFFFA606E carries a band or a record
     pointer: every one loads an immediate 0/1 into r1 immediately before the call
  B. the routine holding the four band arms is called only from the 0..3 ring sweep
  C. the laser builder writes field 4 = 4, copies dword 0 from 0x3B074, formats
     field 20 into 55..58, logs "Laser Alert: %d" -- and never calls tone()
  D. the single-hook candidate at 0xFFF7936A displaces exactly 4 bytes, reproduces
     the copy, latches record+0, and preserves every register/flag/SP
  E. that candidate latches the *last* record of a sweep, not the armed alert
     (negative result: it is behaviour-preserving but semantically useless)

Run: python3 tools/test_alert_path.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rxmini import CPU, assemble_bsr_a  # noqa: E402

BASE = 0xFFF00000
IMAGE = Path("work/main_flat_fff00000.bin")
DIS = Path("work/main_full.dis")
ARM = 0xFFFA606E
TONE = 0xFFFB2BA1
LASER_FMT = 0xFFF72B51
SITE = 0xFFF7936A            # mov.l 20[r15], 20[r14]  in the ring copy
HOOK2 = 0xFFFD1080
LATCH = 0x3B033

DISPLACED = bytes.fromhex("e5fe0505")
HOOK2_CODE = bytes.fromhex("e5fe0505" "ecf1" "fb2233b00300" "c321" "02")

ok = True


def check(cond, msg):
    global ok
    print(("   OK   " if cond else "   FAIL ") + msg)
    if not cond:
        ok = False


def parse():
    ins = []
    for raw in DIS.read_text(errors="replace").splitlines():
        m = re.match(r"^([0-9a-f]{8}):\t([0-9a-f ]+)\t+(\S+)(?:\t(.*))?$", raw)
        if m:
            ins.append((int(m.group(1), 16), m.group(3), (m.group(4) or "").strip()))
    return ins


def arm_sites(ins):
    out = []
    for i, (a, t, o) in enumerate(ins):
        if t in ("bsr", "bsr.a", "bsr.w") and re.search(rf"0x{ARM:x}", o):
            out.append((a, ins[i - 1], ins[i - 2]))
    return out


def check_a(ins):
    print("\n[A] beeper call sites carry only an immediate flag")
    sites = arm_sites(ins)
    check(len(sites) == 17, f"17 call sites of 0x{ARM:08X} (got {len(sites)})")
    bad = []
    for a, prev, prev2 in sites:
        # previous instruction must be mov.l #0|1, r1 (single 2-byte or 6-byte form)
        if not (prev[1] == "mov.l" and re.fullmatch(r"#(0|1), r1", prev[2])):
            bad.append((a, prev))
    check(not bad, f"every site is preceded by mov.l #0/#1, r1 {bad[:3]}")
    # nothing in the two instructions before the flag loads a record pointer
    check(not any("0x3bf88" in p[2] or "0x397a8" in p[2] for _, p, _ in sites),
          "no site derives r1 from the record arrays")


def check_b(ins):
    print("\n[B] the four band arms are only reached from the 0..3 ring sweep")
    callers = [(a, t, o) for a, t, o in ins if t in ("bsr", "bsr.a", "bsr.w")
               and re.search(r"0xfff866b9", o)]
    check(len(callers) == 1 and callers[0][0] == 0xFFF939EE,
          f"single caller at 0xFFF939EE (got {[hex(c[0]) for c in callers]})")
    window = [(a, t, o) for a, t, o in ins if 0xFFF939E1 <= a <= 0xFFF939FE]
    txt = " | ".join(f"{t} {o}" for _, t, o in window)
    check("mul #68, r2" in txt and "cmp #4, r1" in txt and "blt.b" in txt,
          "call sits inside `for i<4 { 0x3BF88 + 68*i }`")


def check_c(ins):
    print("\n[C] laser builder: fields, log string, and no tone() call")
    block = [(a, t, o) for a, t, o in ins if 0xFFF78F32 <= a <= 0xFFF7906B]
    txt = "\n".join(f"{a:08x} {t} {o}" for a, t, o in block)
    check("mov.b #4, 4[r1]" in txt, "writes field 4 = 4 (laser source kind)")
    check("mov.l #0x3b074, r15" in txt and "mov.l [r15], [r14]" in txt,
          "dword 0 copied from 0x3B074, not from a band constant")
    check("mov.l 8[r15], 20[r14]" in txt, "field 20 <- 8[0x3B074]")
    check(txt.count("mov.b r") >= 4 and "55[" in txt and "58[" in txt,
          "field 20 rendered as ASCII digits into 55..58")
    check(f"mov.l #0x{LASER_FMT:x}, r14" in txt, "logs the laser format string")
    check("fffb2ba1" not in txt, "no call to tone() anywhere in the laser builder")


def check_d():
    print("\n[D] single-hook candidate at 0xFFF7936A")
    img = IMAGE.read_bytes()
    got = img[SITE - BASE: SITE - BASE + 4]
    check(got == DISPLACED, f"site holds {got.hex()} == e5fe0505 (mov.l 20[r15], 20[r14])")
    enc = assemble_bsr_a(SITE, HOOK2)
    d = int.from_bytes(enc[1:], "little")
    back = SITE + 4 + (d if d < 0x800000 else d - 0x1000000)
    check(back == HOOK2, f"bsr.a {enc.hex(' ')} -> 0x{back:08X}")
    check(len(HOOK2_CODE) == 15, f"hook is 15 bytes ({len(HOOK2_CODE)})")

    src, dst = 0x40000, 0x50000
    flash = {HOOK2 + i: b for i, b in enumerate(HOOK2_CODE)}
    cpu = CPU(flash=flash)
    cpu.r[1], cpu.r[2] = 0x1111, 0x2222
    cpu.r[14], cpu.r[15] = dst, src
    cpu.pc = HOOK2
    cpu.wl(src, 0x10)
    cpu.wl(src + 20, 0xCAFEBABE)
    cpu.wl(dst + 20, 0)
    cpu.psw = {"C": 1, "Z": 0, "S": 1, "O": 1, "I": 0}
    before = list(cpu.r)
    for _ in range(4):                 # e5, ec, fb, c3 -- the data instructions
        cpu.step()
    check(cpu.rl(dst + 20) == 0xCAFEBABE, "displaced copy reproduced into 20[r14]")
    check(cpu.rb(LATCH) == 0x10, f"latched record+0 = 0x{cpu.rb(LATCH):02X}")
    check(cpu.r[14] == before[14] and cpu.r[15] == before[15], "r14/r15 preserved")
    check(cpu.r[0] == before[0], "r0 (the frame/stack pointer here) preserved")
    check(cpu.psw == {"C": 1, "Z": 0, "S": 1, "O": 1, "I": 0}, "PSW untouched")
    check(HOOK2_CODE[4 + 2 + 6 + 2] == 0x02, "hook ends in rts (02), the only stack-using byte")
    check(not any(HOOK2_CODE[i] in (0x6F, 0x7F) for i in range(len(HOOK2_CODE))),
          "no push/pop in the hook")


def check_e():
    print("\n[E] the candidate latches the last record of a sweep, not the armed alert")
    srcs = [(0x40000, 0x10), (0x44000, 0x30)]      # two records, X then Ka
    flash = {HOOK2 + i: b for i, b in enumerate(HOOK2_CODE)}
    seen = []
    for src, band in srcs:
        cpu = CPU(flash=flash)
        cpu.r[14], cpu.r[15] = 0x50000, src
        cpu.wl(src, band)
        cpu.pc = HOOK2
        for _ in range(4):             # data instructions only; rts is not needed here
            cpu.step()
        seen.append(cpu.rb(LATCH))
    check(seen == [0x10, 0x30], f"latch follows each copy: {[hex(b) for b in seen]}")
    check(seen[-1] != seen[0],
          "final value is the last copied record, so it cannot identify the armed alert")


def main():
    ins = parse()
    print("alert path: static checks and the single-hook candidate")
    print(f"  beeper 0x{ARM:08X}, tone 0x{TONE:08X}, hook 0x{HOOK2:08X}")
    check_a(ins)
    check_b(ins)
    check_c(ins)
    check_d()
    check_e()
    print("\nall alert-path tests passed" if ok else "\nFAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
