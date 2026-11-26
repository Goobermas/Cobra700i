#!/usr/bin/env python3
"""KaLab v0.1 -- offline prototype: change the shared radar beep period only.

The five radar call sites all load the same immediate:

    fb 1a 98 3a      mov.l #0x3a98, r1      (0x3a98 = 15000)

and the tone routine computes the PWM period as `period - 1`, so the audible
frequency is 15 MHz / period.  Rewriting the 2-byte immediate at each site changes
the pitch and nothing else: no code cave, no RAM variable, no trampoline, no change
to cadence (the 50/30/80 ms scheduling lives elsewhere), strength handling, volume
or voice/sample playback.

Usage
    patch_shared_tone.py apply  --period 12000 [-o out/img.bin] [--srec out.s3]
    patch_shared_tone.py revert --patch out/img.bin -o reverted.bin
    patch_shared_tone.py verify --patch out/img.bin

The prototype never writes to the input image, and refuses to run unless every
site holds the expected original bytes.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

BASE = 0xFFF00000
SRC = Path("work/main_flat_fff00000.bin")
SITES = [0xFFF93C47, 0xFFF93CD9, 0xFFF863F9, 0xFFF8640C, 0xFFF86430]
ORIG = bytes.fromhex("fb1a983a")
STOCK_PERIOD = 0x3A98
TIMER_HZ = 15_000_000
# Everything the tone routine is entered with must stay a sane 16-bit period.
MIN_PERIOD, MAX_PERIOD = 64, 0xFFFF


def s3(addr, data):
    """One S3 record with a correct Motorola checksum."""
    n = len(data) + 5                       # count = len + addr(4) + checksum(1)
    body = bytes([n]) + addr.to_bytes(4, "big") + bytes(data)
    return "S3" + body.hex().upper() + f"{(~sum(body)) & 0xFF:02X}"


def s0(text):
    """S0 header record (2-byte address)."""
    data = text.encode()
    body = bytes([len(data) + 3, 0, 0]) + data
    return "S0" + body.hex().upper() + f"{(~sum(body)) & 0xFF:02X}"


def s5(count):
    """S5 record: 16-bit record count."""
    body = bytes([3, 0, 0]) + count.to_bytes(2, "big")
    return "S5" + body.hex().upper() + f"{(~sum(body)) & 0xFF:02X}"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def check_sites(img):
    bad = []
    for a in SITES:
        got = img[a - BASE: a - BASE + 4]
        if got != ORIG:
            bad.append((a, got.hex()))
    return bad


def freq(period):
    return TIMER_HZ / period


def cmd_apply(args):
    p = args.period
    if not (MIN_PERIOD <= p <= MAX_PERIOD):
        sys.exit(f"period {p} outside [{MIN_PERIOD}, {MAX_PERIOD}]")
    img = bytearray(SRC.read_bytes())
    bad = check_sites(img)
    if bad:
        sys.exit(f"original-byte verification FAILED at {bad}")
    before_n = sum(1 for i in range(len(img) - 3) if img[i:i + 4] == ORIG)
    # The encoding also appears at 26 non-radar uses (UI beeps, tables).  Only the five
    # listed sites are touched, so the count must drop by exactly len(SITES).
    print(f"  {ORIG.hex()} occurrences in the image: {before_n}")
    if before_n < len(SITES):
        sys.exit(f"expected at least {len(SITES)} copies of {ORIG.hex()}, found {before_n}")

    new_imm = p.to_bytes(2, "little")
    diffs = []
    for a in SITES:
        off = a - BASE
        old = bytes(img[off:off + 4])
        img[off + 2:off + 4] = new_imm
        diffs.append({"addr": a, "offset": off, "old": old.hex(),
                      "new": bytes(img[off:off + 4]).hex(),
                      "stock_hz": freq(STOCK_PERIOD), "new_hz": freq(p)})

    after_n = sum(1 for i in range(len(img) - 3) if img[i:i + 4] == ORIG)
    changed = [i for i in range(len(img)) if img[i] != SRC.read_bytes()[i]]
    expected = sorted(a - BASE + k for a in SITES for k in (2, 3))
    if changed != expected:
        sys.exit(f"byte-difference report FAILED: {len(changed)} bytes changed, expected {len(expected)}")
    if after_n != before_n - len(SITES):
        sys.exit(f"after patch {after_n} stock instructions remain, expected {before_n - len(SITES)}")
    print(f"  stock instructions left elsewhere (unrelated sounds): {after_n}")

    out = Path(args.out or "out/v0_1/img.bin")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(img)

    recs = []
    for d in diffs:
        line_start = d["offset"] & ~0xF
        line = bytes(img[line_start:line_start + 16])
        recs.append(s3(BASE + line_start, line))

    if args.srec:
        sp = Path(args.srec)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text("\n".join([s0("KaLab v0.1")] + recs + [s5(len(recs))]) + "\n")
        # verify the checksums we just wrote
        for line in sp.read_text().splitlines():
            if len(line) > 4:
                body = bytes.fromhex(line[2:-2])
                assert (~sum(body)) & 0xFF == int(line[-2:], 16), line

    manifest = {
        "image_in": str(SRC), "sha256_in": sha(SRC.read_bytes()),
        "image_out": str(out), "sha256_out": sha(bytes(img)),
        "stock_period": STOCK_PERIOD, "period": p,
        "stock_hz": round(freq(STOCK_PERIOD), 2), "new_hz": round(freq(p), 2),
        "changed_bytes": len(changed), "diffs": diffs,
        "srec": str(args.srec) if args.srec else None,
    }
    mp = out.with_suffix(".json")
    mp.write_text(json.dumps(manifest, indent=2))
    print(f"KaLab v0.1 shared-tone patch applied")
    print(f"  stock {STOCK_PERIOD} -> {freq(STOCK_PERIOD):.1f} Hz, new {p} -> {freq(p):.1f} Hz")
    for d in diffs:
        print(f"  0x{d['addr']:08X}  {d['old']} -> {d['new']}")
    print(f"  bytes changed: {len(changed)} (expected {len(expected)})")
    print(f"  {out}  sha256 {manifest['sha256_out']}")
    if args.srec:
        print(f"  {args.srec}  ({len(recs)} data records, checksums verified)")
    print(f"  manifest {mp}")


def cmd_revert(args):
    orig = SRC.read_bytes()
    patched = bytearray(Path(args.patch).read_bytes())
    if len(patched) != len(orig):
        sys.exit("size mismatch")
    diffs = [i for i in range(len(patched)) if patched[i] != orig[i]]
    if not diffs:
        sys.exit("patch image is identical to the original; nothing to revert")
    for i in diffs:
        patched[i] = orig[i]
    out = Path(args.out or "out/v0_1/reverted.bin")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(patched)
    same = sha(bytes(patched)) == sha(orig)
    print(f"reverted {len(diffs)} byte(s) -> {out}")
    print(f"  sha256 {sha(bytes(patched))}")
    print(f"  byte-identical to original: {same}")
    if not same:
        sys.exit(1)


def cmd_verify(args):
    img = Path(args.patch).read_bytes()
    orig = SRC.read_bytes()
    ok = True
    print("static verification of the patched image")
    print(f"  size {len(img)} (expected {len(orig)})", end="")
    ok &= len(img) == len(orig)
    print(" OK" if len(img) == len(orig) else " FAIL")
    changed = [i for i in range(len(orig)) if img[i] != orig[i]]
    sites_ok = all(bytes(img[a - BASE:a - BASE + 2]) == ORIG[:2] for a in SITES)
    print(f"  changed bytes {len(changed)} at {[hex(BASE + c) for c in changed]}")
    print(f"  every site still decodes as 'fb 1a' (mov.l #imm16, r1): {sites_ok}")
    periods = [int.from_bytes(img[a - BASE + 2:a - BASE + 4], "little") for a in SITES]
    print(f"  periods at the five sites: {periods}")
    uniform = len(set(periods)) == 1
    print(f"  all five sites share one period: {uniform}")
    inrange = all(MIN_PERIOD <= p <= MAX_PERIOD for p in periods)
    print(f"  period within [{MIN_PERIOD}, {MAX_PERIOD}]: {inrange}")
    ok &= sites_ok and uniform and inrange and len(changed) <= 2 * len(SITES)
    print("  RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply")
    a.add_argument("--period", type=int, required=True)
    a.add_argument("-o", "--out")
    a.add_argument("--srec")
    a.set_defaults(func=cmd_apply)
    r = sub.add_parser("revert")
    r.add_argument("--patch", required=True)
    r.add_argument("-o", "--out")
    r.set_defaults(func=cmd_revert)
    v = sub.add_parser("verify")
    v.add_argument("--patch", required=True)
    v.set_defaults(func=cmd_verify)
    args = ap.parse_args()
    if hasattr(args, "func"):
        args.func(args)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
