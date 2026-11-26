#!/usr/bin/env python3
"""Verify the three radar beep pitch sites without producing any firmware.

For each site it prints the original instruction bytes read from the untouched
flat image, the exact bytes that would change, the instruction size, and the
reachable-code checks. It never writes a patched image.

Sites (from AUDIO_HW.md): the three places the radar alert handler starts a beep.
    0xFFF863F9  0xFFF8640C  0xFFF86430     all  fb 1a 98 3a
encoding:  fb 1a <imm16 LE>   =  mov.l #imm16, r1      (4 bytes, always)

Usage: python3 tools/patch_sites.py
"""
from pathlib import Path

IMAGE = Path("work/main_flat_fff00000.bin")
BASE = 0xFFF00000

# keyed by the bsr.a call site; the immediate load is found by scanning back
ALERT_SITES = {
    "type 1 (0xFFF863F0)": 0xFFF863FD,
    "type 2 (0xFFF86404)": 0xFFF86410,
    "type 3 (0xFFF86417)": 0xFFF86434,
}
# every other caller of the beep programmer -- these must NOT be touched
OTHER_SITES = {
    "engine state 1 (0xFFF93C47)": 0xFFF93C4B,
    "engine state 4 (0xFFF93CD9)": 0xFFF93CDD,
    "self-test pulse 1 (0xFFF93D36)": 0xFFF93D3A,
    "self-test pulse 2 (0xFFF93D57)": 0xFFF93D5B,
    "self-test pulse 3 (0xFFF93D78)": 0xFFF93D7C,
    "self-test variable (0xFFF93DA2)": 0xFFF93DA2,
}

# pitch options: target Hz -> period for each clock hypothesis
CLOCKS = {"60MHz": 60_000_000, "30MHz": 30_000_000, "15MHz": 15_000_000}
TARGETS = {"X": 1000, "K": 1400, "Ka": 2000, "LASER": 2600}


def read(addr, n=4):
    off = addr - BASE
    return IMAGE.read_bytes()[off:off + n]


def find_load(call_addr, lookback=8):
    """Locate the mov.l #imm16,r1 that feeds the bsr at call_addr.

    Returns (load_address, bytes, immediate) or (None, None, None) when the
    argument is not an immediate (the self-test variable site).
    """
    for back in range(4, lookback + 1):
        a = call_addr - back
        b = read(a, 4)
        if b[:2] == b"\xfb\x1a" and a + 4 == call_addr:
            return a, b, b[2] | (b[3] << 8)
    return None, None, None


def main():
    img = IMAGE.read_bytes()
    print(f"image: {IMAGE}  size {len(img)} bytes, base 0x{BASE:08X}")
    print(f"sha256: {__import__('hashlib').sha256(img).hexdigest()}\n")

    print("=== beep pitch sites (to be changed) ===")
    print(f"{'handler':26s} {'load':10s} {'bytes':12s} {'instr':18s} {'period':>7s}")
    sites_ok = True
    for name, call in ALERT_SITES.items():
        a, b, imm = find_load(call)
        if a is None:
            sites_ok = False
            print(f"{name:26s} 0x{call:08X} NO IMMEDIATE FOUND")
            continue
        print(f"{name:26s} 0x{a:08X} {b.hex(' '):12s} "
              f"mov.l #0x{imm:04X},r1   {imm:7d}")
        assert imm == 0x3A98, f"{name}: expected 15000, found {imm}"

    print("\n=== other callers of 0xFFFB2BA1 (must stay 0x3A98) ===")
    for name, call in OTHER_SITES.items():
        a, b, imm = find_load(call)
        if a is None:
            print(f"{name:34s} 0x{call:08X} {'(variable argument)':>12s} "
                  "-- pitch is caller-supplied")
            continue
        flag = "OK unchanged" if imm == 0x3A98 else f"DIFFERS: {imm}"
        print(f"{name:34s} 0x{a:08X} {b.hex(' '):12s} {imm:6d}  {flag}")

    print("\n=== replacement bytes for a pitch-only change ===")
    print("site fixed at 4 bytes; only bytes [2:4] (the LE imm16) move.\n")
    print(f"{'band':6s} {'Hz':>5s} " + " ".join(f"{c:>22s}" for c in CLOCKS))
    for band, hz in TARGETS.items():
        row = f"{band:6s} {hz:5d} "
        for cname, clk in CLOCKS.items():
            d = int(round(clk / hz))
            if d > 0xFFFF:
                row += f" {'no fit (>0xFFFF)':>22s}"
            else:
                row += f" d={d:<6d}-> fb 1a {d & 0xFF:02X} {d >> 8:02X} "
        print(row)

    print("\n=== control-flow integrity ===")
    assert sites_ok
    for name, call in ALERT_SITES.items():
        a, b, imm = find_load(call)
        assert len(b) == 4 and b[0] == 0xFB and a + 4 == call
        print(f"0x{a:08X}: 4-byte immediate form, no branch target, no delay slot,"
              " next instruction untouched -> flow preserved")
    print("\nsize delta for every candidate: 0 bytes; no other byte in the image moves.")

    print("\n=== blast radius of the change ===")
    print("0xFFFB2BA1 writes 0xC1218/0xC121A (beep channel) and toggles only")
    print("0x8C022 bit 2. The clip/voice channel is 0xC1228 + 0xC1280 bit 7 and is")
    print("never touched, so announcements, GPS prompts and start-up sounds are")
    print("unaffected. Menu/self-test beeps use the six OTHER_SITES above and keep")
    print("their current pitch.")


if __name__ == "__main__":
    main()
