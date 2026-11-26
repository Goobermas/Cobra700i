# Timer clock, patch sites, and audio comparison (priorities 2-4)

Companion to `AUDIO_HW.md`. Excerpts from `work/main_full.dis`, image base `0xFFF00000`.

---

## Priority 2 — the timer clock

### What the firmware does with the clock

The clock-mode setter is `0xFFFA32D8(mode)`:

```
fffa32d8: sub   #4, r0
fffa32da: mov.l r1, [r0]
fffa32dc: mov.l #0x4918c, r14
fffa32e2: cmp   [r14].l, r1        ; same mode already applied?
fffa32e5: beq.w fffa33b3           ; yes -> return, do nothing
fffa32e8: mov.l #0x4918c, r14
fffa32ee: mov.l [r0], [r14]        ; cache the mode
fffa32f0: mov.w #0xa50b, 990[0x80020]   ; unlock protected writes
...  per-mode SCKCR edit, then store the resulting Hz ...
fffa33a6: mov.w #0xa500, 990[0x80020]   ; re-lock
```

**Callers and their argument [C]**

| caller | argument |
|---|---|
| `0xFFF9A9EE` | **immediate 2** (`mov.l #2, r1` at `0xFFF9A9EC`) |
| `0xFFF9AD0C` | **immediate 2** (`mov.l #2, r1` at `0xFFF9AD0A`) |
| `0xFFFA3CB0` | **immediate 2** (`mov.l #2, r1` at `0xFFFA3CAE`) |
| `0xFFF89144` | variable: `mov.l 176[0x3AB38], r1` |
| `0xFFF98404` | variable: `mov.l 176[0x3AB38], r1` |

Every immediate in the image is **2**. The two variable sites re-apply whatever mode is
cached at `0x3AB38+176`. `0x4918C` (the applied-mode cache) is written **only** inside
`0xFFFA32D8`; nothing initialises it elsewhere, so the first call with a non-matching value
takes effect.

**Per-mode configuration [C]** (`0xFFFA32F0`–`0xFFFA33A6`)

| mode | SCKCR edit | stored Hz | value |
|---|---|---|---|
| 0 | `bset #16` | `0x3938700` | 60 000 000 |
| 1 | `or #0x90000` | `0x2625A00` | 40 000 000 |
| 2 | `bset #17` | `0x1C9C380` | **30 000 000** |
| 3 | `or #0x30000` | `0xE4E1C0` | 15 000 000 |
| 4 | `bset #18` | `0x7270E0` | 7 500 000 |

Mode 2 modifies only bit 17 of SCKCR — a *divider* bit, not a PLL change — and records
30 MHz.

### Prescaler [C]

**No prescaler field is ever written for the audio timer.** The complete setup
(`0xFFFA76B3`–`0xFFFA7727` plus `0xFFFB2BA1`) writes period, duty, two spare compares, the
start bit and the mode bytes at `0xC1202`/`0xC1204`/`0xC1205`. The counter therefore runs
on the **undivided** clock of that block.

### Peripheral-clock derivation [C, partial]

The helper at `0xFFFAA209`–`0xFFFAA2A2` computes the peripheral frequency from SCKCR3 and
a PLL field rather than returning a constant:

```
fffaa230: r1 = movu.w 8[0x80020]        ; SCKCR3 word
fffaa237: bfmovz #8, #0, #6, r1, r1     ; 6-bit PLL multiplier field
fffaa23c: mul   #10, r1  /  add #10, r1  /  shlr #1, r1     ; -> 5*(field+1)
fffaa242: 20[r0] = ...                  ; multiplier
fffaa244: 16[r0] = 0x1c9c380            ; 30 000 000 base
fffaa252: bfmovz #4, #0, #1, ...        ; bit 4 selects a table-derived base instead
fffaa271: r2 = movu.w 8[0x80020] ; and #3 ; *10+10 ; >>1     ; 5*(div+1)
fffaa27e: divu  r2, r1
fffaa281: mul   20[r0].l, r1
fffaa285: 24[r0] = r1                   ; f = base / div * mult
fffaa291: bfmovz #8, #0, #4, ...        ; 4-bit field
fffaa29d: shlr  r14, r1
fffaa2a0: 28[r0] = r1                   ; a further divided clock
```

So PCLK = base ÷ (5·(div+1)) × 5·(mult+1), with a second clock divided again by the 4-bit
field. This is a proper PLL/divider computation, **not** a constant.

### Conclusion for priority 2

* **[C]** The selected clock mode is **2** — the only immediate used anywhere — and mode 2
  records 30 MHz.
* **[C]** The audio timer has **no prescaler** (divisor 1).
* **[C]** The peripheral clock is derived by the PLL/divider helper above.
* **[O]** The *numeric* PCLK still cannot be fixed, because the PLL multiplier/divider
  bitfields live in registers whose exact RX part definition is unavailable (no part number
  in the image). What can be said: the firmware's own mode-2 figure is 30 MHz, and if the
  audio block runs from that class of clock the beep is **2000 Hz**; if it runs from the
  15 MHz figure it is **1000 Hz**. 4 kHz (60 MHz) is **not** supported and is now
  **withdrawn** from `AUDIO_HW.md` as the working hypothesis.

**This is the one number still missing for priority 4.** Measuring the buzzer settles it.

---

## Priority 3 — patch sites

Tool: `tools/patch_sites.py` (read-only; it never writes an image). Verified output:

```
image: work/main_flat_fff00000.bin  size 1048576 bytes, base 0xFFF00000
sha256: 13545b5838bab5aa44b7a3acbdb4cab93ea299160b97a4c7362613c3e0fc5789

handler                    load       bytes        instr               period
type 1 (0xFFF863F0)        0xFFF863F9 fb 1a 98 3a  mov.l #0x3A98,r1     15000
type 2 (0xFFF86404)        0xFFF8640C fb 1a 98 3a  mov.l #0x3A98,r1     15000
type 3 (0xFFF86417)        0xFFF86430 fb 1a 98 3a  mov.l #0x3A98,r1     15000
```

### Instruction form

`fb 1a <imm16 LE>` = `mov.l #imm16, r1` — **always exactly 4 bytes**, no branch target, no
delay slot, and the following instruction (`bsr.a 0xFFFB2BA1`) is untouched. Only bytes
`[2:4]` change.

| band | target | @60 MHz (withdrawn) | @30 MHz (mode 2) | @15 MHz |
|---|---|---|---|---|
| X | 1000 Hz | `fb 1a 60 EA` d=60000 | `fb 1a 30 75` d=30000 | `fb 1a 98 3A` d=15000 * |
| K | 1400 Hz | `fb 1a 69 A7` d=42857 | `fb 1a B5 53` d=21429 | `fb 1a DA 29` d=10714 |
| Ka | 2000 Hz | `fb 1a 30 75` d=30000 | `fb 1a 98 3A` d=15000 * | `fb 1a 4C 1D` d=7500 |
| LASER | 2600 Hz | `fb 1a 25 5A` d=23077 | `fb 1a 12 2D` d=11538 | `fb 1a 89 16` d=5769 |

`*` = identical to the existing bytes, i.e. that band would already sound at the target
pitch under that clock. Every candidate is ≤ 0xFFFF, so no prescaler change is needed.

### Control-flow integrity [C]

All three sites: 4-byte immediate form, size delta **0**, no other byte of the image moves,
no branch/call target in the changed bytes, fallthrough unchanged.

### Other users of the tone routine [C]

| site | argument | sound |
|---|---|---|
| `0xFFF863F9` | 15000 | radar class 1 — **patch candidate** |
| `0xFFF8640C` | 15000 | radar class 2 — **patch candidate** |
| `0xFFF86430` | 15000 | radar class 3 — **patch candidate** |
| `0xFFF93C47` | 15000 | generic beep engine, state 1 |
| `0xFFF93CD9` | 15000 | generic beep engine, state 4 |
| `0xFFF93D36` | 15000 | self-test beep, pulse 1 |
| `0xFFF93D57` | 15000 | self-test beep, pulse 2 |
| `0xFFF93D78` | 15000 | self-test beep, pulse 3 |
| `0xFFF93DA2` | variable | self-test beep with caller-chosen period |

There are no indirect calls to `0xFFFB2BA1` (its address is never taken), so this table is
complete.

### Blast radius [C]

`0xFFFB2BA1` touches only `0xC1218`/`0xC121A` (beep channel, start bit 6) and `0x8C022`
bit 2. The clip/voice channel is `0xC1228` + `0xC1280` bit 7 and is never referenced, so
**voice announcements, GPS/camera prompts and start-up sounds are unaffected**; menu and
self-test beeps keep their current pitch. The only behavioural interaction is the existing
one: a beep already pre-empts a clip (`cmp #1` on the busy flag → `bclr #7`).

---

## Priority 4 — original vs proposed audio

Tool: `tools/render_compare.py` → `out/compare/`. The cadence is **not** changed: every
render uses the firmware's own envelope (50 ms on / 30 ms off / 50 ms on), so the only
difference is pitch.

```
clock      original (measured)     proposed (measured)
60MHz      4000.0 Hz (4003.9)      X=997 Hz  K=1399 Hz  Ka=2002 Hz  LASER=2597 Hz
30MHz      2000.0 Hz (2001.9)      (same targets, same cadence)
15MHz      1000.0 Hz ( 997.1)      (same targets, same cadence)
```

Files: `<clock>_original.wav` and `<clock>_proposed_{X,K,Ka,LASER}.wav`. Listen to the pair
at the clock the hardware actually uses; the rhythm is identical by construction.

---

## Still blocking a firmware release

1. PCLK number (above) — needs one measurement or the part number.
2. Which layer-2 index is X / K / Ka (`BAND_MAP.md`).
3. Updater/bootloader validation and recovery path — still unverified (closed-source
   installer, not runnable here).

No flashable image has been produced. `out/` and `work/` are generated and excluded from
version control.
