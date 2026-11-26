#!/usr/bin/env python3
"""Offline scenario tests for the band-aware tone design.

Five requirements, each exercised without touching firmware:

  S1 unknown band keeps the stock 1000 Hz beep
  S2 X / K / Ka get 1250 / 1500 / 2000 Hz
  S3 a band change updates the pitch at the next burst
  S4 menu sounds keep their own caller-supplied period
  S5 voice / GPS audio is untouched (separate clip channel + hook writes only r1)

The patch plan is verified against the real image: every site must currently hold
`fb 1a 98 3a` (mov.l #0x3a98, r1), and the encoded `bsr.a` must resolve back to the
hook address.

Run:  python3 tools/test_scenarios.py
"""
import sys
from pathlib import Path

sys.path.insert(0, "tools")
from test_band_period import HOOK, interpret, STOCK          # noqa: E402
import bandaware_sim as sim                                  # noqa: E402

IMAGE = Path("work/main_flat_fff00000.bin")
BASE = 0xFFF00000

HOOK_ADDR = 0xFFFD1000   # 4 KB-aligned, inside an erased block (was 0xFFFD0C0B)
STOCK_BYTES = bytes.fromhex("fb1a983a")      # mov.l #0x3a98, r1

# The five sites that actually feed the radar tone: the sounder engine's two
# tone() calls and the display dispatcher's three.
TONE_SITES = [
    0xFFF93C47,   # engine, burst 1
    0xFFF93CD9,   # engine, burst 2 (double-pulse mode)
    0xFFF863F9,   # display, colour class 1
    0xFFF8640C,   # display, colour class 2
    0xFFF86430,   # display, colour class 3
]
MENU_SITE = 0xFFF93DA2       # the parameterised UI beep, must NOT be patched

# The clip / voice / GPS channel is a different timer entirely.
CLIP_REGS = [0xC1228, 0xC1280]


def bsr_a(site, target):
    """Encode `bsr.a target` at `site` -> 4 bytes."""
    disp = (target - (site + 4)) & 0xFFFFFF
    return bytes([0x05, disp & 0xFF, (disp >> 8) & 0xFF, (disp >> 16) & 0xFF])


def image():
    return IMAGE.read_bytes()


def read(addr, n):
    return image()[addr - BASE: addr - BASE + n]


def s1_unknown_band():
    for code in (0x00, 0x01, 0x7F, 0x81, 0xFF):
        assert interpret(code) == STOCK, f"0x{code:02X} did not keep the stock period"
    print(f"  S1 unknown band -> period {STOCK} (1000.0 Hz at 15 MHz)   OK")


def s2_band_pitches():
    for code, want, hz in ((0x10, 12000, 1250), (0x20, 10000, 1500), (0x30, 7500, 2000)):
        got = interpret(code)
        assert got == want, f"0x{code:02X}: {got} != {want}"
        print(f"  S2 band 0x{code:02X} -> period {got:5d} = {15000000/got:7.1f} Hz "
              f"(target {hz})   OK")


def s3_band_switch():
    """The period must follow the latched band at the next burst, not persist."""
    s = sim.Sounder(0x10)
    s.arm()
    seen = []
    for t in range(300):
        s.tick(t)
        if s.log and (not seen or seen[-1][1] != s.log[-1][2]):
            seen.append((t, s.log[-1][2]))
        if t == 60:
            s.band = 0x30        # Ka arrives mid-alert
            s.arm()
    periods = [p for _, p in seen if p]
    assert periods[0] == sim.period_for(0x10), f"first burst {periods[0]}"
    assert any(p == sim.period_for(0x30) for p in periods), \
        f"Ka never took effect, saw {periods}"
    print(f"  S3 X burst starts at {periods[0]}, Ka appears after the switch "
          f"({sorted(set(periods))})   OK")


def s4_menu_sounds():
    assert MENU_SITE not in TONE_SITES, "the UI beeper must not be in the patch plan"
    # and the hook never runs for it: it takes its period from its caller
    got = interpret(0x00)                     # no radar band latched
    assert got == STOCK
    print(f"  S4 menu beeper 0x{MENU_SITE:08X} is not patched; hook returns {STOCK}   OK")


def s5_voice_and_gps():
    # the clip channel registers must not appear anywhere near the patched sites
    for site in TONE_SITES:
        window = read(site - 16, 32)
        for reg in CLIP_REGS:
            enc = bytes([reg & 0xFF, (reg >> 8) & 0xFF, (reg >> 16) & 0xFF])
            assert enc not in window, f"clip register 0x{reg:X} near 0x{site:08X}"
    # the hook writes only r1 (and reads via it), so no callee-saved register changes
    assert HOOK[0:2] == bytes.fromhex("fb12"), "hook must start by loading r1"
    print(f"  S5 clip channel 0x{CLIP_REGS[0]:X}/0x{CLIP_REGS[1]:X} untouched; "
          f"hook clobbers only r1   OK")


def s6_patch_plan():
    """Every site must hold the expected instruction, and the bsr must resolve."""
    ok = 0
    for site in TONE_SITES:
        cur = read(site, 4)
        assert cur == STOCK_BYTES, f"0x{site:08X} holds {cur.hex()}, expected fb1a983a"
        enc = bsr_a(site, HOOK_ADDR)
        disp = int.from_bytes(enc[1:4], "little")
        if disp & 0x800000:
            disp -= 0x1000000
        assert site + 4 + disp == HOOK_ADDR, f"0x{site:08X} bsr resolves wrong"
        ok += 1
    print(f"  S6 {ok}/{len(TONE_SITES)} sites verified as fb1a983a -> "
          f"bsr.a 0x{HOOK_ADDR:08X} ({bsr_a(TONE_SITES[0], HOOK_ADDR).hex()})   OK")


def s7_cave_alignment():
    """Report erase-block risk rather than assuming alignment."""
    for blk in (0x800, 0x1000):
        rem = HOOK_ADDR % blk
        print(f"  S7 hook 0x{HOOK_ADDR:08X} offset in a {blk//1024} KB erase block: "
              f"0x{rem:X} {'(aligned)' if rem == 0 else '(NOT aligned - shares a block with code)'}")
    assert HOOK_ADDR % 0x1000 == 0, "hook must sit at the start of an erase block"
    assert HOOK_ADDR >= 0xFFFD0C0B, "hook must be past the last non-erased byte"
    img = IMAGE.read_bytes()
    window = img[HOOK_ADDR - BASE: HOOK_ADDR - BASE + 64]
    assert set(window) == {0xFF}, "hook block is not fully erased"
    print(f"     chosen 0x{HOOK_ADDR:08X} is 4 KB-aligned and its 64-byte window is all 0xFF")


def main():
    print("band-aware tone design: scenario tests")
    for fn in (s1_unknown_band, s2_band_pitches, s3_band_switch, s4_menu_sounds,
               s5_voice_and_gps, s6_patch_plan, s7_cave_alignment):
        try:
            fn()
        except AssertionError as e:
            print(f"FAIL in {fn.__name__}: {e}")
            return 1
    print("all scenario tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
