# Is `0x3BF88` the live band? Evidence, verdict, and consequences

Continues `5946424c`. No firmware was built, modified or flashed.

## Verdict

**No. `0x3BF88` cannot be the live radar band, because no instruction in the image ever
writes it.** It has **83 reads across 43 functions** (`+0`: 44, `+28`: 39) and **zero
writes**. A location with no writer cannot track detections, so it is either configuration
copied in at boot or a value initialised by bulk copy — but it is not per-alert state.

Consequently the "read an existing live band value" design has no candidate in this image,
and the latch is unavoidable if pitch is to follow the band.

---

## 1. What `0x3BF88` actually is

Access census (operand polarity, not pattern matching on offsets):

| access | count | shape |
|---|---|---|
| read `[0x3BF88]` | 44 | `mov.l #0x3bf88, rN` / `mov.l [rN], rD` |
| read `28[0x3BF88]` | 39 | `mov.l #0x3bf88, rN` / `mov.l 28[rN], rD` |
| **write** | **0** | none |

The reads feed compare chains against the band codes, e.g.

```
fff84301  mov.l #0x3bf88, r14
          mov.l [r14], r14
          cmp   #16, r14        ; X
fff84326  ...                   cmp #32   ; K
fff84357  ...                   cmp #48   ; Ka
```

So the *type* is right — a band-code-shaped value — but the lifetime is wrong: with no
writer, it is constant for the life of the program (or until a bulk copy that this
disassembly does not expose as an individual store). Two readings remain, and neither is
"current detection":

* **configuration** — e.g. the user's per-band enable/sensitivity profile, stored as band
  identifiers;
* **boot-time snapshot** — filled by a `memcpy`-style loop the byte-level scan cannot see.

Either way the value is not updated when a new alert arrives.

### The other candidate I raised is also wrong

`0x3BD94+12` was reported earlier as "compared to Ka and X". It is compared to **2, 3, 4,
13, 49, 50** at its 17 read sites (`0xFFF814A8`, `0xFFF814D1`, `0xFFF93A12`, `0xFFFA47C8`,
`0xFFFA47D5`, `0xFFFA47EE`, …) — a **mode/state enum**, not a band. That claim is withdrawn.

---

## 2. The record's band is never persisted — and that is the real finding

Searching all 38 band-load sites (`mov.l 4[r0], r1` / `mov.l [r1], rD`) for a follow-up
store of the loaded register to memory within an 8-instruction window returns **nothing**.
There is no `record.band -> global` caching path anywhere in this firmware.

Combined with §1, the picture is now consistent and simple:

```
detection -> record (heap) -> consumers read record+0 directly, every time
```

Every consumer (`0xFFF84301`, `0xFFF858D8`, `0xFFF861F9`, `0xFFF973E1`, `0xFFF9CB9C`, …)
re-reads the record. Nothing copies the band into RAM for later use, which is exactly why
the sounder — which holds no record pointer — cannot know the band.

---

## 3. Comparison with the arming function

`0xFFFA606E(uint8 double_beep)`:

```
fffa606e  sub   #4, r0
fffa6070  mov.b r1, 3[r0]
fffa6072  mov.l #0xaeb6, r14
fffa6078  bset  #5, [r14].b      ; arm
fffa607a  mov.l #0x4c5d4, r14
fffa6080  mov.b 3[r0], 136[r14]  ; double-pulse flag
fffa6084  rtsd  #4
```

* 17 callers, none of which passes a band.
* No function that reads `[0x3BF88]` or `28[0x3BF88]` calls it (checked by xref).
* No function that loads the record band calls it either.

So arming and band-awareness are disjoint in the call graph; the ordering is temporal, not
lexical, and can only be observed at runtime.

---

## 4. Recommendation: latch at the band branch, four 4-byte swaps

Since no live value exists to read, the cheapest correct design is to create one, at the
only place where the band is already in a register *and* a 4-byte instruction is available
to replace.

Inside `0xFFF866ED`, each band branch contains

```
fff8681e  mov.l 20[r1], 4[r0]      ; e5 10 05 01  (4 bytes), r1 = record
```

`r1` still points at the record there, so a `bsr.a latch` (4 bytes) can replace it exactly,
with the hook performing both the original copy and the latch:

```
latch:                       ; entered with r1 = record
    mov.l 20[r1], r2         ; reproduce the replaced instruction
    mov.l r2, 4[r0]
    mov.l [r1], r2           ; record dword 0 = band code
    mov.l #0x3afc4, r0       ; careful: r0 is the frame pointer here
    ...
```

**This is not yet a finished hook.** `r0` cannot be clobbered — it is the caller's frame
pointer at that site — so the store needs a register that is dead across the branch tail, or
a short save/restore. Confirming which of `r2..r15` is dead there is the next mechanical
step, and it must be done per branch (K, Ka, MRCD each have their own copy at
`0xFFF8683A`, `0xFFF86867`, `0xFFF86894`).

Because a real latch is required, a **1-byte RAM cell is unavoidable after all** — at
`0x3AFC4+111` (`0x3B033`, the last byte inside the object bounded by `0x3B034`), never at
`+128`.

---

## 5. Branch displacements for `0xFFFD1000` (recalculated and tested)

All five sites hold `fb 1a 98 3a` and were re-encoded for the new target:

| site | displacement | bytes |
|---|---|---|
| `0xFFF93C47` | `0x03D3B5` | `05 b5 d3 03` |
| `0xFFF93CD9` | `0x03D323` | `05 23 d3 03` |
| `0xFFF863F9` | `0x04AC03` | `05 03 ac 04` |
| `0xFFF8640C` | `0x04ABF0` | `05 f0 ab 04` |
| `0xFFF86430` | `0x04ABCC` | `05 cc ab 04` |

`tools/test_scenarios.py` now uses `HOOK_ADDR = 0xFFFD1000` and re-derives each displacement
from the encoding, asserting it resolves back to the hook:

```
S6 5/5 sites verified as fb1a983a -> bsr.a 0xFFFD1000 (05b5d303)   OK
S7 0xFFFD1000 offset in a 2 KB erase block: 0x0 (aligned)
S7 0xFFFD1000 offset in a 4 KB erase block: 0x0 (aligned)
   chosen 0xFFFD1000 is 4 KB-aligned and its 64-byte window is all 0xFF
```

The displacements *inside* the hook are relative to its own offsets and are unaffected by
where it is placed; they remain as tested in `tools/test_band_period.py`.

---

## 6. Verified facts vs assumptions

| statement | status |
|---|---|
| `0x3BF88` has 83 reads, 0 writes, 43 functions | **verified** (operand-polarity scan of all 373,310 instructions) |
| `0x3BF88` is not updated per detection | **verified** for direct stores; a bulk copy would still not update it per alert |
| no record-band → global store exists | **verified** within an 8-instruction window at all 38 load sites; a longer-lived sequence cannot be fully excluded |
| `0x3BD94+12` is a mode enum | **verified** (compared to 2/3/4/13/49/50) |
| last non-erased byte is `0xFFFD0C0A` | **verified** (byte scan) |
| `0xFFFD1000` is 4 KB-aligned and reads `0xFF` for 64 bytes | **verified** |
| `0xFFFD1000..0xFFFFFFCF` is erased | **verified** in this image only |
| erase-block size is 2 KB or 4 KB | **assumption** — the part number is unknown; both sizes give the same verdict for `0xFFFD0C0B` and the same alignment for `0xFFFD1000` |
| code at `0xFFFD1000` is executable | **assumption** — same flash bank as the rest of the code, but MPU/region configuration is not analysable from the image |
| the updater programs this range | **assumption** — the image is a full 1 MiB flat file; the DFU path was never captured |
| no integrity check covers the hook | **assumption** — no `CRC` string and no digest in the containers is weak evidence, not proof |
| the latch executes before the sounder arms | **unverified** — disjoint call graphs; needs a breakpoint on `0xFFFA606E` and on the latch |

---

## 7. Next actions

1. Pick a dead register for the latch write per branch (r2..r15) at `0xFFF8681E`,
   `0xFFF8684A`-area, `0xFFF86867`-area and `0xFFF86894`-area.
2. Breakpoint `0xFFFA606E` and the latch: confirm the latch runs first on one X and one K
   alert.
3. Second image: confirm `0xFFFD0C0B..0xFFFFFFFF` is byte-identical before trusting the cave.
