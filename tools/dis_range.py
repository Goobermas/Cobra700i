#!/usr/bin/env python3
"""Print disassembly lines whose address falls in [lo, hi].

Usage: dis_range.py LO HI [file]
Addresses are hex, with or without 0x prefix. Default file is work/main_full.dis.
Keeps the instruction-boundary lines produced by objdump -D, so the result is
always a valid instruction stream (never a mid-instruction slice).
"""
import sys
from pathlib import Path

lo = int(sys.argv[1], 16)
hi = int(sys.argv[2], 16)
path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("work/main_full.dis")

import re
LINE = re.compile(r"^([0-9a-f]{8}):\t")
for raw in path.read_text(errors="replace").splitlines():
    m = LINE.match(raw)
    if not m:
        continue
    a = int(m.group(1), 16)
    if lo <= a <= hi:
        # strip the long objdump symbol annotations for readability
        print(re.sub(r" <_binary[^>]*>", "", raw))
