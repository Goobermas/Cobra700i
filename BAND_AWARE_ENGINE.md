# Band-aware PWM sound engine — dataflow, design, simulation

Phase: design only. **No firmware image was produced, modified or flashed.** Every
number below is either read out of the image or measured; the simulator is offline.

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

**Proposal: `band_code` at `0x3AFC4 + 128`**, inside the largest gap, away from the
hot fields (`+84` counter, `+46`, `+36`).

### 2.3 Where the hook lives

The image contains one large erased run: **`0xFFFD0C0B`, 193,477 bytes of `0xFF`**
to the end of flash. The hook is ~40 bytes:

```
band_period:
    mov.l  #0x3afc4, r14      ; fb ee c4 af 03 00
    movu.b 128[r14], r14      ; 59 ee 80
    cmp    #0x10, r14         ; 75 5e 10      X
    beq    .x
    cmp    #0x20, r14         ; 75 5e 20      K
    beq    .k
    cmp    #0x30, r14         ; 75 5e 30      Ka
    beq    .ka
    cmp    #0x05, r14         ; 75 5e 05      Ka (second encoding)
    beq    .ka
.x: mov.l  #12000, r1         ; fb 1a e0 2e   (or fall through to stock)
    rts                       ; 02
.k: mov.l  #10000, r1         ; fb 1a 10 27
    rts
.ka:mov.l  #7500, r1          ; fb 1a 4c 1d
    rts
.def:mov.l #15000, r1         ; fb 1a 98 3a   unknown band -> stock
    rts
```

`r1` is the only register written, which is exactly what the call sites expect
(they were about to load `r1` anyway), so **no register save/restore is needed and
no other live value changes**.

### 2.4 Latency of the band byte

The write side is the remaining open item, and it is deliberately kept separate:
whichever site latches the band must run **before** the sounder is armed. Two
candidates, both plausible from the disassembly:

* **A — latch at record registration.** At `0xFFF867EE` the band is already in
  `r14` (`mov.l [r1], r14`). Storing it needs a base register: `0x3AFC4` is not in
  a register at that point, so this needs 8 bytes, not 2 — it cannot be a pure
  in-place swap and would need a small trampoline.
* **B — latch where the sounder is armed** (the site that sets `0xAEB6` bit 5).
  This is the natural place: the value is current by construction, and the byte is
  then read microseconds later by the engine. Locating this site is the next task.

Because the fallback is "no band latched → 15000", a stale or never-written byte
degrades to **stock behaviour**, not to a wrong tone.

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

Double-pulse mode (`--mode double`) reproduces the same 50/30/80 train when the
re-arm interval is 30 ms, because 30 ms gap plus 50 ms pulse equals the same
period. The two modes only diverge when the detection path re-arms more slowly
than 30 ms, in which case double mode emits two pulses per arming. **This does not
affect pitch** and is left as an open behavioural question rather than guessed.

---

## 4. Memory

| item | size | location |
|---|---|---|
| `band_code` | 1 byte | RAM `0x3AFC4+128` (inside an untouched 49-byte gap) |
| `band_period()` | ~40 bytes | erased flash `0xFFFD0C0B` |
| call-site patches | 0 bytes net | 4-byte → 4-byte swap, in place |
| band table | 0 | immediates, no table in flash |

Total: **1 byte of RAM, ~40 bytes of flash**, no new allocation, no change to any
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
2. Dump `0xFFFD0C0B..0xFFFFFF` from a second, independently obtained image and
   confirm the tail is identical (i.e. erased, not board-specific).
3. Re-derive `0x3AFC4`'s allocation size to confirm `+128` is inside it.
4. Only then emit a patch plan, and only as a *plan* — no image.
