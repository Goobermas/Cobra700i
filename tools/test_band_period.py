#!/usr/bin/env python3
"""Executable unit tests for the proposed band_period() hook.

Two layers:

1. GOLDEN DECODE — every instruction form used by the hook is lifted byte for byte
   out of the firmware together with the disassembly text GNU objdump printed for
   it, and the interpreter must decode those bytes to that same text.  This pins the
   opcode assumptions to real machine code instead of to a table I typed.

2. BEHAVIOUR — the hook's 56 bytes are executed for all 256 band bytes:

       X   0x10 -> 12000      K  0x20 -> 10000
       Ka  0x30 -> 7500       Ka 0x05 -> 7500
       everything else -> 15000  (stock period: no band latched)

Run:  python3 tools/test_band_period.py
"""
import sys

BAND_ADDR = 0x3AFC4
BAND_OFF = 128
STOCK = 15000

# --- 1. golden instructions, bytes as they appear in the image ---------------
GOLDEN = [
    ("fb12c4af0300", "mov.l\t#0x3afc4, r1"),    # 0xFFF93BEE
    ("fb12096b0100", "mov.l\t#0x16b09, r1"),    # 0xFFF8682A
    ("59113f", "movu.b\t63[r1], r1"),           # 0xFFF866F6
    ("755132", "cmp\t#50, r1"),                 # 0xFFF93C6A
    ("75511e", "cmp\t#30, r1"),                 # 0xFFF93CC1
    ("2058", "beq.b\t0x5a"),                    # 0xFFF8636A (decoded at pc=0)
    ("210c", "bne.b\t0xe"),                     # 0xFFF93C88
    ("02", "rts"),                              # 0xFFF93D2A
]

# --- 2. the hook ------------------------------------------------------------
#   off  bytes                  instruction
#   00   fb12c4af0300           mov.l #0x3afc4, r1   base
#   06   591180                 movu.b 128[r1], r1   band code
#   09   755110                 cmp #16, r1          X
#   0c   2107                   bne 0x15
#   0e   fb12e02e0000           mov.l #12000, r1     X tone
#   14   02                     rts
#   15   755120                 cmp #32, r1          K
#   18   2107                   bne 0x21
#   1a   fb1210270000           mov.l #10000, r1     K tone
#   20   02                     rts
#   21   755130                 cmp #48, r1          Ka
#   24   2005                   beq 0x2b
#   26   755105                 cmp #5, r1           Ka alternative
#   29   2107                   bne 0x32             everything else
#   2b   fb124c1d0000           mov.l #7500, r1      Ka tone
#   31   02                     rts
#   32   fb12983a0000           mov.l #15000, r1     DEFAULT, only here
#   38   02                     rts
#
# The default is loaded on the unmatched path only.  Preloading it before the base
# pointer move is wrong: the pointer and the loaded byte both land in r1 and destroy
# it, so an unmatched code would return the band byte itself.
HOOK = bytes.fromhex(
    "fb12c4af0300"
    "591180"
    "755110"
    "2107"
    "fb12e02e0000"
    "02"
    "755120"
    "2107"
    "fb1210270000"
    "02"
    "755130"
    "2005"
    "755105"
    "2107"
    "fb124c1d0000"
    "02"
    "fb12983a0000"
    "02"
)

LAYOUT = [
    (0x00, 6, "mov.l\t#0x3afc4, r1"),
    (0x06, 3, "movu.b\t128[r1], r1"),
    (0x09, 3, "cmp\t#16, r1"),
    (0x0C, 2, "bne.b\t0x15"),
    (0x0E, 6, "mov.l\t#0x2ee0, r1"),
    (0x14, 1, "rts"),
    (0x15, 3, "cmp\t#32, r1"),
    (0x18, 2, "bne.b\t0x21"),
    (0x1A, 6, "mov.l\t#0x2710, r1"),
    (0x20, 1, "rts"),
    (0x21, 3, "cmp\t#48, r1"),
    (0x24, 2, "beq.b\t0x2b"),
    (0x26, 3, "cmp\t#5, r1"),
    (0x29, 2, "bne.b\t0x32"),
    (0x2B, 6, "mov.l\t#0x1d4c, r1"),
    (0x31, 1, "rts"),
    (0x32, 6, "mov.l\t#0x3a98, r1"),
    (0x38, 1, "rts"),
]


def decode(buf, pc):
    """Decode one instruction of the subset the hook uses -> (text, size)."""
    op = buf[pc]
    if op == 0x02:
        return "rts", 1
    if op == 0xFB and buf[pc + 1] == 0x12:              # mov.l #imm32, r1
        imm = int.from_bytes(buf[pc + 2:pc + 6], "little")
        return f"mov.l\t#{hex(imm)}, r1", 6
    if op == 0x59 and buf[pc + 1] == 0x11:              # movu.b d8[r1], r1
        return f"movu.b\t{buf[pc + 2]}[r1], r1", 3
    if op == 0x75 and buf[pc + 1] == 0x51:              # cmp #uimm8, r1
        return f"cmp\t#{buf[pc + 2]}, r1", 3
    if op in (0x20, 0x21):                              # beq.b / bne.b
        disp = buf[pc + 1] - 0x100 if buf[pc + 1] > 0x7F else buf[pc + 1]
        return ("beq.b\t0x%x" % (pc + 2 + disp) if op == 0x20
                else "bne.b\t0x%x" % (pc + 2 + disp)), 2
    raise ValueError(f"undecodable 0x{op:02X} at 0x{pc:X}")


def interpret(band, base=BAND_ADDR, off=BAND_OFF):
    """Execute the hook with `band` stored at base+off. Returns the period in r1."""
    ram = bytearray(0x40000)
    ram[(base + off) & 0x3FFFF] = band
    r1 = 0
    zero = False
    pc = 0
    guard = 0
    while pc < len(HOOK):
        guard += 1
        if guard > 64:
            raise RuntimeError("hook did not terminate")
        text, size = decode(HOOK, pc)
        if text.startswith("mov.l"):
            r1 = int(text.split("#")[1].split(",")[0], 0)
            pc += size
        elif text.startswith("movu.b"):
            d8 = int(text.split("\t")[1].split("[")[0])
            r1 = ram[(base + d8) & 0x3FFFF]
            pc += size
        elif text.startswith("cmp"):
            zero = r1 == int(text.split("#")[1].split(",")[0], 0)
            pc += size
        elif text == "rts":
            return r1
        elif text.startswith("beq.b"):
            target = int(text.split("\t")[1], 16)
            pc = target if zero else pc + size
        elif text.startswith("bne.b"):
            target = int(text.split("\t")[1], 16)
            pc = target if not zero else pc + size
        else:
            raise RuntimeError(text)
    return r1


def test_golden():
    for raw, expected in GOLDEN:
        got, size = decode(bytes.fromhex(raw), 0)
        assert size == len(bytes.fromhex(raw)), f"size mismatch for {raw}"
        assert got == expected, f"{raw}: decoded {got!r}, objdump says {expected!r}"
    print(f"  golden decode : {len(GOLDEN)} firmware instructions decoded identically")


def test_layout():
    pc = 0
    for off, size, expected in LAYOUT:
        assert off == pc, f"layout: expected offset {off:#x}, got {pc:#x}"
        got, got_size = decode(HOOK, pc)
        assert got_size == size, f"@{off:#x}: size {got_size} != {size}"
        assert got == expected, f"@{off:#x}: {got!r} != {expected!r}"
        pc += size
    assert pc == len(HOOK), f"hook is {pc} bytes, expected {len(HOOK)}"
    print(f"  layout        : {len(LAYOUT)} instructions, {len(HOOK)} bytes as intended")


def test_mapping():
    want = {0x10: 12000, 0x20: 10000, 0x30: 7500, 0x05: 7500}
    for band, period in want.items():
        got = interpret(band)
        assert got == period, f"band 0x{band:02X}: got {got}, want {period}"
        print(f"  band 0x{band:02X}     : -> {got:5d}  OK")
    bad = [(b, interpret(b)) for b in range(256) if b not in want and interpret(b) != STOCK]
    assert not bad, f"fallback broken for {[(hex(b), g) for b, g in bad[:8]]}"
    print(f"  fallback      : {256 - len(want)} other values -> {STOCK}  OK")


def test_stale():
    for value in (0x00, 0xFF, 0x77, 0x80):
        got = interpret(value)
        assert got == STOCK, f"stale 0x{value:02X} -> {got}, want {STOCK}"
    print(f"  staleness     : 0x00/0xFF/0x77/0x80 -> {STOCK}  OK")


def main():
    print("band_period() hook tests")
    for fn in (test_golden, test_layout, test_mapping, test_stale):
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL in {fn.__name__}: {e}")
            return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
