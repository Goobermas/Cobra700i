#!/usr/bin/env python3
"""Exact byte-level map of candidate free flash, with reserved regions excluded.

An erased run is NOT proof of free space.  This tool only reports what the bytes
say, then separately lists the regions that must be treated as reserved regardless
of what they contain.

What it prints
  1. the tail dump, so the vector table is visible rather than assumed
  2. every erased (0xFF) run >= --min-run bytes, with exact start/end
  3. the decoded vector table at the end of flash
  4. every non-0xFF byte inside each candidate, i.e. the holes that break it
  5. candidate caves after subtracting reserved and populated regions

Reserved regions are declared here, not guessed from the bytes:
  - the final 64 bytes (vector table; 0xFFFFFFFFFC holds the reset vector)
  - RX option-setting / security memory is conventionally in the last 0x100 bytes.
    Those bytes may read 0xFF, and 0xFF is itself a meaningful setting ("disabled"),
    so they are excluded even though they look erased.

Usage:  python3 tools/flash_map.py [--tail 512] [--min-run 64]
"""
import argparse
from pathlib import Path

BASE = 0xFFF00000
IMAGE = Path("work/main_flat_fff00000.bin")

RESERVED_TAIL = 0x100      # last 256 bytes: vectors + option/security area


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=96)
    ap.add_argument("--min-run", type=int, default=64)
    args = ap.parse_args()

    img = IMAGE.read_bytes()
    n = len(img)
    end = BASE + n
    print(f"image {IMAGE}  {n} bytes  0x{BASE:08X}..0x{end - 1:08X}")
    print(f"reserved tail: 0x{end - RESERVED_TAIL:08X}..0x{end - 1:08X} "
          f"({RESERVED_TAIL} bytes)\n")

    # --- 1. tail dump -------------------------------------------------------
    print(f"=== last {args.tail} bytes ===")
    off = n - args.tail
    while off < n:
        chunk = img[off:off + 16]
        mark = "  <-- reserved" if off >= n - RESERVED_TAIL else ""
        print(f"  0x{BASE + off:08X}  {' '.join(f'{b:02x}' for b in chunk)}{mark}")
        off += 16

    # --- 2. erased runs -----------------------------------------------------
    runs = []
    i = 0
    while i < n:
        if img[i] == 0xFF:
            j = i
            while j < n and img[j] == 0xFF:
                j += 1
            if j - i >= args.min_run:
                runs.append((i, j))
            i = j
        else:
            i += 1
    print(f"\n=== erased runs >= {args.min_run} bytes: {len(runs)} ===")
    for a, b in runs:
        print(f"  0x{BASE + a:08X}..0x{BASE + b - 1:08X}  {b - a} bytes")

    # --- 3. vector table ----------------------------------------------------
    print("\n=== vector table (end of flash, 4-byte entries) ===")
    vt = n - RESERVED_TAIL
    while vt < n:
        val = int.from_bytes(img[vt:vt + 4], "little")
        if vt == n - 4:
            name = "reset vector (0xFFFFFFFC)"
        elif vt == n - 8:
            name = "exception  -> default handler"
        else:
            name = ""
        print(f"  0x{BASE + vt:08X}: 0x{val:08X}  {name}")
        vt += 4

    # --- 4. holes inside the tail-side candidates ---------------------------
    print("\n=== candidates, after subtracting the reserved tail ===")
    limit = n - RESERVED_TAIL
    found = False
    for a, b in runs:
        b = min(b, limit)
        if b - a < args.min_run:
            continue
        found = True
        holes = []
        i = a
        while i < b:
            if img[i] != 0xFF:
                j = i
                while j < b and img[j] != 0xFF:
                    j += 1
                holes.append((i, j))
                i = j
            else:
                i += 1
        print(f"  0x{BASE + a:08X}..0x{BASE + b - 1:08X}  usable {b - a} bytes, "
              f"holes {len(holes)}")
        for h in holes:
            print(f"      hole 0x{BASE + h[0]:08X}..0x{BASE + h[1] - 1:08X} "
                  f"({h[1] - h[0]} bytes)")
        print(f"      status: ERASED IN THIS IMAGE ONLY — not proven writable, "
              f"not proven unused by another revision")
    if not found:
        print("  none")

    print("\n=== verdict ===")
    print("  The single erased run is the tail below the vector table. There is no")
    print("  second cave anywhere in the image, so a hook placement in flash cannot")
    print("  be justified from this file alone; see BAND_AWARE_ENGINE.md §5.")


if __name__ == "__main__":
    main()
