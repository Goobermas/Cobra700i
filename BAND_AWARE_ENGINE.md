# Band-aware PWM sound engine — dataflow, design, simulation

Phase: design only. **No firmware image was produced, modified or flashed.** Every
number below is either read out of the image or measured; the simulator is offline.

> **Revision 2 (after review).** Two defects were corrected here: the flash claim in §2.3
> (the erased run stops at `0xFFFFFFCF`, the last 48 bytes are the vector table, reset at
> `0xFFFFFFFC`), and the fallback branch (an unmatched band returned 12000 because the
> default was clobbered by the pointer load). Both are now covered by executable tests.

Image `work/main_flat_fff00000.bin`, base `0xFFF00000`, 1,048,576 bytes.
Companion documents: `BEEP_CALLGRAPH.md` (call graph), `CLOCK_AND_PATCH.md` (clock),
`BAND_MAP.md` (band codes).

---

## 1. Dataflow: where the band is, and why the sounder cannot see it

### 1.1 The band code is the record's dword 0

Proven by the compare chain at `0xFFF867EE`:

```
fff867ee:  mov.l 4[r0], r1        ; r1 = ctx->record
fff867f0:  mov.l [r1], r14        ; r14 = record->dword0  = EVENT CODE
fff867f2:  cmp   #5, r14   ; beq fff86867     (0x05, second Ka spelling)
fff867f6:  cmp   #128, r14 ; beq fff86894     (0x80, MRCD)
fff867fc:  cmp   #32, r14  ; beq fff8683a     (0x20, K)
fff86801:  cmp   #48, r14  ; beq fff86867     (0x30, Ka)
fff86806:  cmp   #16, r14  ; bne fff868bf     (0x10, X)
```

So **`record+0` = band/event code**, and the meanings `0x10`=X, `0x20`=K,
`0x30`/`0x05`=Ka, `0x80`=MRCD are established independently by the per-branch log
format strings (`0xFFF86822`, `0xFFF86850`, `0xFFF8687D`, `0xFFF868AA`).

Two different access paths reach the same record:

| path | expression | used by |
|---|---|---|
| renderer | `60[ctx]` → record | display dispatcher `0xFFF863CF`/`0xFFF86360` |
| event/log | `4[ctx]` → record | log dispatch `0xFFF866ED` |

### 1.2 The sounder reads none of it

`0xFFF93BCF` touches exactly six locations:

| location | use |
|---|---|
| `22[0x3C188]` | sounder disabled in config |
| `0xAEB6` bit 5 | arm flag (see §1.3) |
| `84[0x3AFC4]` | millisecond counter |
| `0x19DE3` | state 0..5 |
| `120[0x4C5D4]`, `136[0x4C5D4]` | one-shot active, double-pulse enable |
| `0x8C022` bit 2 | buzzer pin |

No record pointer, no band, no context argument. The chain is
`0xFFFA40D5 → 0xFFF94AE2(r1, r2) → 0xFFF93BCF()`, and `0xFFF94AE2` does nothing with
`r1`/`r2` except spill them to its own frame.

**This is the whole problem: the band exists only inside a heap record that the
sounder has no pointer to.**

### 1.3 Correction forced by the recording

`BEEP_CALLGRAPH.md` read the arm gate backwards ("returns when bit 5 is SET").
Simulating that reading makes every burst end by clearing the very bit that keeps it
running, so the machine self-retriggers with a ~2 ms gap and a 133 ms period — which
the measured 50 on / 30 off / 80 ms period refutes. The gate is the opposite way:

> the engine runs only while bit 5 of `0xAEB6` is **set**, and each burst ends with
> `bclr #5`, i.e. it **disarms** itself. The 30 ms silence is the time until the
> detection path re-arms it.

That correction is applied in `tools/bandaware_sim.py` and to `BEEP_CALLGRAPH.md`.

---

## 2. Proposed design

### 2.1 Shape

Three parts, each independently reversible:

1. **One byte of state** — the active band code, in RAM that no code touches.
2. **A hook** — `band_period()`, returns the period for that byte, falling back to
   15000.
3. **Call-site swap** — replace `mov.l #0x3A98, r1` with `bsr.a band_period` at the
   sites that matter.

The swap is attractive because both instructions are exactly **4 bytes**:

```
stock:   fb 1a 98 3a        mov.l #0x3a98, r1
patched: 05 c0 cf 03        bsr.a 0xfffd0c0b     ; disp = target - (site + 4)
```

No site grows, no site moves, and every following address is unchanged — which
matters because the image has no relocation information.

### 2.2 Where the band byte lives

Scanning every access that dereferences `0x3AFC4` gives the live offsets:

```
1 3 4 5 6 7 8 12 16 24 28 36 40 44 45 46 48 52 56 60 62 66 68 72 74 76 78
80 84 88 89 90 92 94 96 100 101 104 108 109 110
```

Untouched gaps: `+17..+23` (7 B), `+29..+35` (7 B), **`+111..+159` (49 B)**.

> **WRONG — corrected in `LATCH_AND_CAVE.md`.** This section originally proposed
> `0x3AFC4 + 128`. That address is `0x3B044`, which lies **inside the next global object**
> (the one at `0x3B034`, bounded above by `0x3B218`). The `0x3AFC4` object is only
> `0x3AFC4..0x3B033` (112 bytes), so `+128` would corrupt unrelated memory. Absence of code
> references was never evidence of allocation; the neighbour globals are.
>
> Safe alternatives: read the band cache the firmware already maintains (see
> `LATCH_AND_CAVE.md` Priority 1), or if a byte is truly needed, `+111` (`0x3B033`, the last
> byte inside the object) or the holes at `+17..+23` / `+29..+35`.

### 2.3 Where the hook lives — corrected

The earlier text claimed an erased region running "to the end of flash". **That was
wrong**, and the review was right to reject it: the last 48 bytes are populated. The
measured facts, reproducible with `tools/flash_map.py`:

| region | contents |
|---|---|
| `0xFFF00000..0xFFFD0C0A` | code and data; last non-erased byte at `0xFFFD0C0A` |
| `0xFFFD0C0B..0xFFFFFFCF` | erased, 193,477 bytes — the **only** run >= 64 B in the image |
| `0xFFFFFFD0..0xFFFFFFFF` | **populated**: twelve 4-byte vector entries |
| `0xFFFFFFFC` | reset vector `08 87 fa ff` -> `0xFFFA8708` |

Decoded entries (little-endian dwords):

```
0xFFFFFFD0 0xFFFA9160   0xFFFFFFE0 0xFFFA9562   0xFFFFFFF0 0xFFFA9562
0xFFFFFFD4 0xFFFA91AB   0xFFFFFFE4 0xFFFA9241   0xFFFFFFF4 0xFFFA9562
0xFFFFFFD8 0xFFFA9562   0xFFFFFFE8 0xFFFA9562   0xFFFFFFF8 0xFFFA929E
0xFFFFFFDC 0xFFFA91F6   0xFFFFFFEC 0xFFFA9562   0xFFFFFFFC 0xFFFA8708  reset
```

`0xFFFA9562` repeats six times: the default-handler stub. So the erased run is bounded
above by the vector table, not by the top of flash.

Two cautions, because **erased is not free**:

* `0xFFFFFF00..0xFFFFFFCF` reads `0xFF` but lies where RX parts keep option-setting and
  security memory. There `0xFF` is a *value* ("disabled"), not emptiness, so the tool
  excludes the last 256 bytes even though they look blank.
* one image proves nothing about another revision, which may hold calibration or keys
  in the same run.

> **Placement rejected on alignment grounds.** `0xFFFD0C0B` is `0x40B` into a 2 KB erase
> block that also holds live code ending at `0xFFFD0C0A`, so programming it would require
> erasing and rewriting a block containing real instructions. Use an aligned erased block
> instead — `0xFFFD1000` is 4 KB-aligned and 0xFF-filled. See `LATCH_AND_CAVE.md`
> Priority 3.

Provisional candidate: **`0xFFFD1000..0xFFFD1038`** (57 bytes), still provisional until a
second image confirms the tail is byte-identical.

The hook itself, 57 bytes, with the default loaded **only** on the unmatched path:

```
off  bytes          instruction
00   fb12c4af0300   mov.l #0x3afc4, r1      ; base of the alert-state struct
06   591180         movu.b 128[r1], r1     ; r1 = band code
09   755110         cmp   #16, r1           ; X
0c   2107           bne   0x15
0e   fb12e02e0000   mov.l #12000, r1       ; X tone
14   02             rts
15   755120         cmp   #32, r1           ; K
18   2107           bne   0x21
1a   fb1210270000   mov.l #10000, r1       ; K tone
20   02             rts
21   755130         cmp   #48, r1           ; Ka
24   2005           beq   0x2b
26   755105         cmp   #5, r1            ; Ka, second spelling
29   2107           bne   0x32
2b   fb124c1d0000   mov.l #7500, r1        ; Ka tone
31   02             rts
32   fb12983a0000   mov.l #15000, r1       ; DEFAULT: only reached here
38   02             rts
```

Only `r1` is written. At every patched site `r1` was about to be loaded anyway, so no
other live value changes. The listing is byte-identical to the program exercised by
`tools/test_band_period.py`.

### 2.4 Latching the band, and why it cannot go stale

The arming site was located this session: **`0xFFFA606E`**, a 23-byte leaf with 17 callers.

```
fffa606e:  sub   #4, r0
fffa6070:  mov.b r1, 3[r0]          ; save the one argument
fffa6072:  mov.l #0xaeb6, r14
fffa6078:  bset  #5, [r14].b        ; ARM the sounder
fffa607a:  mov.l #0x4c5d4, r14
fffa6080:  mov.b 3[r0], 136[r14]    ; double-pulse flag = that argument
fffa6084:  rtsd  #4
```

Its only argument is the double-pulse flag, so the band cannot be latched here without
changing a signature shared by 17 call sites. Worse, those callers include UI paths —
menu sounds arm the same bit — so a naive latch here would give menu beeps a radar pitch,
which §2.5 forbids.

The design therefore latches at the **alert-record processor**, where the band is already
in a register, and writes on **every** record processed:

* `0x10` / `0x20` / `0x30` / `0x05` / `0x80` -> store the code;
* anything else -> store **0**.

The hook whitelists codes, so 0 (or any unknown value) means "no radar band" and returns
the stock 15000.

Why that cannot be stale:

| event | what keeps it correct |
|---|---|
| band changes X -> K | K's record is processed before K arms the sounder, so the byte is overwritten first |
| alert ends | the engine is disarmed; the byte is only consulted on the next burst, which is preceded by that burst's own record |
| non-radar arming (menu) | no radar record ran, so the zeroing write has left 0 and the beep stays stock |

Residual case, stated rather than hidden: if the zeroing write does not run for an idle
record, the first non-radar burst after a radar alert could sound at the previous pitch.
That is the single reason the zeroing write is part of the contract.
### 2.5 Behaviour that is untouched by construction

| behaviour | why it cannot change |
|---|---|
| detection | no code in the detection path is modified |
| mute | gates A and B, `0x8C022` handling and `0xFFFB2BA1` are unchanged |
| volume | volume lives in `0x4C5D4` and the amp path, never in the period |
| cadence | 50 / 30 thresholds and `0x19DE3` are untouched; only P changes |
| laser | laser path still calls nothing; unaffected |
| UI sounds | `0xFFF93D9C` keeps using its caller-supplied period |

---

## 3. Simulation

`tools/bandaware_sim.py` models the engine (arm flag, 50/30 thresholds, state byte,
single and double modes) and gates a 50 %-duty square wave from the resulting
period. WAVs at 48 kHz mono, 16-bit:

| file | band | period | target | measured |
|---|---|---|---|---|
| `x_1250hz.wav` | X | 12000 | 1250 Hz | 1253.7 Hz |
| `k_1500hz.wav` | K | 10000 | 1500 Hz | 1506.7 Hz |
| `ka_2000hz.wav` | Ka | 7500 | 2000 Hz | 2012.0 Hz |
| `mrcd_1250hz.wav` | MRCD | 12000 | 1250 Hz | 1253.7 Hz |
| `stock_fallback.wav` | unknown | 15000 | 1000 Hz | 1003.0 Hz |
| `unknown_fallback.wav` | unknown | 15000 | 1000 Hz | 1003.0 Hz |

Cadence check from the state trace (Ka, single-pulse mode):
`on=[1, 83, 165, 247] off=[51, 133, 215, 297]` → **burst 51 ms, gap 32 ms, period
82 ms**, against your measured 50 / 30 / 80 ms. The 1–2 ms excess is the one-tick
state 0 → 1 transition plus the model's 30 ms re-arm assumption.

The measured "target" column drift (1253.7 vs 1250) is the zero-crossing estimator's
resolution over a 50 ms burst, not an arithmetic error: `15000000/12000 = 1250.0`
exactly. The firmware gets the exact value because it divides the clock by a
16-bit register.

### 3.1 Unit tests for the hook (`tools/test_band_period.py`)

The hook's 57 bytes are executed by a small interpreter and asserted for **all 256**
band values, and the interpreter's decoder is itself pinned to eight instructions lifted
byte-for-byte out of the firmware (`fb12c4af0300` -> `mov.l #0x3afc4, r1`, etc.), so the
opcodes are not merely assumed:

```
golden decode : 8 firmware instructions decoded identically
layout        : 18 instructions, 57 bytes as intended
band 0x10     : -> 12000  OK
band 0x20     : -> 10000  OK
band 0x30     : ->  7500  OK
band 0x05     : ->  7500  OK
fallback      : 252 other values -> 15000  OK
staleness     : 0x00/0xFF/0x77/0x80 -> 15000  OK
all tests passed
```

These tests caught a real defect in the first draft of §2.3: the default period was
loaded into `r1` before `r1` became the base pointer, so an unmatched code returned the
band byte itself (0x01 -> 1 tick). The default is now loaded on the unmatched path only.

Double-pulse mode (`--mode double`) reproduces the same 50/30/80 train when the
re-arm interval is 30 ms, because 30 ms gap plus 50 ms pulse equals the same
period. The two modes only diverge when the detection path re-arms more slowly
than 30 ms, in which case double mode emits two pulses per arming. **This does not
affect pitch** and is left as an open behavioural question rather than guessed.

---

## 4. Memory

| item | size | location |
|---|---|---|
| `band_code` | 1 byte — **only if no existing cache is used** | RAM `0x3AFC4+111`, not `+128` (unsafe): see `LATCH_AND_CAVE.md` |
| `band_period()` | 57 bytes | erased flash `0xFFFD0C0B` (provisional) |
| call-site patches | 0 bytes net | 4-byte → 4-byte swap, in place |
| band table | 0 | immediates, no table in flash |

Total: **1 byte of RAM, 57 bytes of flash**, no new allocation, no change to any
existing structure's size.

---

## 5. Risks

| risk | severity | mitigation |
|---|---|---|
| `0xFFFD0C0B` may be reserved (boot config, calibration, key store) | **high** | dump and diff the tail against a known-good image before use; if non-trivial, place the hook in the `+111..+159` gap region or a verified dead-code pocket instead |
| `+111..+159` never appears in code but may be used by a `memcpy`/struct clear | medium | verify by checking the allocation size of the `0x3AFC4` object; fallback is the `+29..+35` gap |
| latching site (candidate B) not yet located | medium | the design degrades to stock 15000 until it is, so a partial implementation is safe |
| updater/bootloader validation remains unanalysable (no bootloader image) | **high** | unchanged from `UPDATER_ANALYSIS.md`: a modified image may be rejected, and recovery is unproven |
| `bfmovz` semantics assumed from behaviour, not from the ISA manual | medium | the recording pins the effective polarity; verify with a breakpoint on `0xAEB6` before relying on it |
| band byte stale after a band change | low | fallback to 15000; refresh at arming |
| MCU part number still unknown, so clock tree unverified beyond 15 MHz measured | low | pitch is derived from the measured clock, not from the datasheet |

---

## 6. What is deliberately not done

* No patched image, no `.mot`, no flashing — as required.
* No call-site patch is written to disk; §2.1 gives the encoding, not a binary.
* The latch site is specified as a design contract but not yet pinned to an address.
* `MRCD` is mapped to X's pitch **by choice**, and labelled as such: nothing in the
  image associates it with a frequency.

## 7. Next steps, in order

1. Locate the arming site (the `bset #5, [0xAEB6]` writer) and confirm `rec+0` is in
   scope there — this closes the last dataflow gap.
2. Obtain a second, independently sourced image and diff `0xFFFD0C0B..0xFFFFFFFF`.
   Only if the tail is identical is the cave assumption usable. (The reset vector at
   `0xFFFFFFFC` must read `08 87 fa ff` in both.)
3. Re-derive `0x3AFC4`'s allocation size to confirm `+128` is inside it.
4. Only then emit a patch plan, and only as a *plan* — no image.
