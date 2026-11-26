# RAD 700i — audio hardware map (verified from disassembly)

Image base `0xFFF00000`, full disassembly `work/main_full.dis` (binutils 2.42 `rx-elf`,
byte-exact from the S-records). Excerpt tool: `tools/dis_range.py LO HI`.
Labels: **[C]** confirmed from code, **[I]** inferred, **[O]** still open.

---

## 0. Summary of the corrected model

There are **two independent audio channels** in one timer block, both gated by the same
amplifier pin:

| | beep channel | clip/DSP channel |
|---|---|---|
| period register | `0xC1218` = d−1 | (free-running at fixed rate) |
| duty register | `0xC121A` = (d−1)>>1 (50 %) | — |
| data register | — | `0xC1228` (one 16-bit sample per tick) |
| start | `bset #6,[0xC1280]` (`0xFFFA774A`) | `bset #7,[0xC1280]` (`0xFFFB25D3`) |
| stop | `bclr #6,[0xC1280]` (`0xFFFA7752`) | `bclr #7,[0xC1280]` (`0xFFFB25DB`) |
| programmed by | `0xFFFB2BA1(d)` | ISR `0xFFFB2E56`, engine `0xFFFB27C0` |

**[C] The beep is a hardware square wave, not a stored clip.** The beep channel only ever
receives a period and a 50 % duty; nothing writes samples to it. Its pitch is therefore
`f_timer / d` and nothing else.

This replaces the earlier "hardware PWM *period* is pitch" guess with a precise statement,
and confirms why every constant call site passes the same value: **all beeps share one
pitch**. Band differentiation is colour + cadence, never pitch.

---

## 1. Objective 1 — the peripheral at `0xC1218` / `0xC121A`

**[C]** Register semantics are unambiguous from the only writer, `0xFFFB2BA1`:

```
fffb2ba1: sub   #8, r0
fffb2ba3: mov.l r1, 4[r0]          ; save argument d
fffb2ba5: bsr.a fffb25bf           ; query: is the output already running? (bit1 of 0xC120A)
fffb2ba9: cmp   #0, r1
fffb2bab: beq.s fffb2bb0
fffb2bac: bsr.a fffb25b7           ; bclr #1,[0xC120A]   -- release/stop
fffb2bb0: mov.l #0x19f4a, r14
fffb2bb6: mov.b #1, [r14]          ; 0x19F4A = "audio active" flag
fffb2bb9: mov.l #0x4c5d4, r14
fffb2bbf: movu.b 120[r14], r14     ; busy flag 0x4C5D4+120
fffb2bc2: cmp   #1, r14
fffb2bc4: bne.b fffb2bd1
fffb2bc6: bsr.a fffb25db           ; bclr #7,[0xC1280]  -- stop the clip channel
fffb2bca: mov.l #0x8c022, r14
fffb2bcf: bclr  #2, [r14].b        ; amp off
fffb2bd1: mov.l 4[r0], r1
fffb2bd3: sub   #1, r1
fffb2bd5: mov.l #0xc1218, r14
fffb2bda: mov.w r1, [r14]          ; *** 0xC1218 = d-1   (period) ***
fffb2bdc: mov.l 4[r0], r1
fffb2bde: sub   #1, r1
fffb2be0: shlr  #1, r1
fffb2be2: mov.l #0xc1218, r2
fffb2be7: mov.w r1, 2[r2]          ; *** 0xC121A = (d-1)>>1  (50 % duty) ***
fffb2be9: mov.l #0xc1218, r1
fffb2bee: mov.w #0, 12[r1]         ; 0xC1224 = 0
fffb2bf1: mov.l #0xc1218, r1
fffb2bf6: mov.w #0, 14[r1]         ; 0xC1226 = 0
fffb2bf9: bsr.a fffa774a           ; bset #6,[0xC1280]  -- start
fffb2bfd: mov.l #0x8c022, r14
fffb2c02: movu.b [r14], r14
fffb2c04: bfmovz #2, #0, #1, r14, r14   ; read amp bit
fffb2c09: cmp   #0, r14
fffb2c0b: beq.s fffb2c10
fffb2c0c: mov.l #0, [r0]  /  bra fffb2c13
fffb2c10: mov.l #1, [r0]
fffb2c13: mov.l [r0], r1
fffb2c15: cmp   #0, r1
fffb2c17: beq.s fffb2c21
fffb2c18: mov.l #0x8c022, r14
fffb2c1d: bset  #2, [r14].b        ; amp on (only if it was off)
fffb2c1f: rtsd  #8
```

The `(period−1, half)` pair plus a 16-bit paired clear at `+0xC`/`+0xE` is a **16-bit
up-counter timer in PWM mode**: period `d`, compare/duty `d/2`. `0xC1224`/`0xC1226` are the
two spare compare registers of the same channel, zeroed so they never fire.

The block layout, from every reference in the image:

```
0xC11FE  channel/DSP struct base used by the clip path (0xFFFB2550..0xFFFB25A3)
0xC1200  block base; config at 0xFFFA76D5..0xFFFA7727
   +0x18  0xC1218  period          (written 0x3B2E = 15150 at boot config)
   +0x1A  0xC121A  duty            (written 0x1D97 =  7575 = exactly half)
   +0x24  0xC1224  compare 2       (0)
   +0x26  0xC1226  compare 3       (0)
   +0x28  0xC1228  clip/DSP sample register
   +0x4C  0xC124C  = 2             (config, 0xFFFA76E2)
0xC1280  start/stop byte:  bit6 = beep channel, bit7 = clip channel
0xC1284  written 1 then 0 during setup (0xFFFB254C / 0xFFFB25B2)
0xC1300  second block, 0x80 bytes on   (13 refs, 0xFFFB2F87..)
0xC1380  second block, 0x80 bytes on   (7 refs, 0xFFFB240E..)
```

Written during setup (`0xFFFA76B3`), immediately after unlocking pin-function writes:

```
fffa76b3: mov.l #0x80010, r14     ; bus/clock register
fffa76b8: mov.l [r14], r15
fffa76ba: bclr  #9, r15
fffa76bc: mov.l r15, [r14]
fffa76be: mov.l #0xc1280, r14
fffa76c3: bset  #0, 4[r14].b      ; 0xC1284
fffa76cb: bclr  #6, [r14].b       ; stop beep channel
fffa76d2: bclr  #6, 1[r14].b      ; 0xC1281 bit6
fffa76d5: mov.b #40, [0xc1200]    ; = 0x28
fffa76e2: mov.b #2,  76[0xc1200]  ; 0xC124C = 2
fffa76eb: mov.b #0,   8[0xc1200]  ; 0xC1208 = 0
fffa76f3: mov.b #2,   2[0xc1200]  ; 0xC1202 = 2
fffa76fb: mov.b #86,  4[0xc1200]  ; 0xC1204 = 0x56
fffa7703: mov.b #0,   5[0xc1200]  ; 0xC1205 = 0
fffa770b: mov.w #0x3b2e, 24[0xc1200]   ; period 15150
fffa7715: mov.w #0x1d97, 26[0xc1200]   ; duty    7575
fffa771f: mov.w #0, 36[0xc1200]        ; 0xC1224
fffa7727: mov.w #0, 38[0xc1200]        ; 0xC1226
```

**[C]** Two observations settle the "what is this" question:
* the pitch registers are the *period/duty* pair of a PWM-mode 16-bit timer, programmed
  through a single function;
* the pitch register is written with `d−1` while the boot config writes the *count*
  `0x3B2E`, i.e. `period = d` exactly.

### Part identification — best available evidence

| Evidence | Value | Points to |
|---|---|---|
| I/O base / port block | `0x0008_0000`, ports at `0x8C000` | RX600/RXv2 family [C] |
| Pin-function write-protect unlock | `0x803FE ← 0xA500` / `0xA502` / `0xA50B` | MPC.PWPR style register [C usage, I name] |
| PFS cluster | `0x8C11F`, `0x8C151`, `0x8C4CC` | pin-function registers above the port block [I] |
| Clock control | `0x80020` (SCKCR) | RX system clock control [C offset use] |
| **10 KiB framebuffer at `0x0080_0000`** | `0xFFF7F862` fills `0x800000..0x802800` | **on-chip expansion RAM at `0x0080_0000`** |
| **Option/ID region `0xFE7F_5D00–0x7D7C`** | 8 fragments in the S-records | the RX map that lists `FE7F5D00` |
| RAM used up to | `0x7EF38` (≈508 KiB) | ≥512 KiB of internal RAM |
| FPU + DSP instructions, `mvfaclo/mvtaclo` | throughout | RXv2 core |

Combination that satisfies all of these — ≥512 KiB internal RAM **and** expansion RAM at
`0x0080_0000` **and** a `0xFE7F5D00` option region — is an **RXv2-class part with internal
RAM ≥ 512 KiB plus on-chip expansion RAM** (the RX65N/RX651 family documents exactly this
split: 256 KiB main + 384 KiB expansion at `0x0080_0000`, and RX72N/RX66N document
512 KiB + 512 KiB). **[I]** The exact part number is **not printed anywhere in the image**
(no `R5F…` string; verified), so it cannot be confirmed from firmware alone. Distinguishing
RX651 (256 KiB main) from RX72N/RX66N (512 KiB main) hinges on `0x7EF38`, which favours the
512 KiB-main parts — but that address is used in only a few places and is not proof.

The peripheral itself is a **16-bit PWM-mode timer channel with paired compare registers and
a per-channel start bit** — functionally the RX "MTU3" family's PWM mode (TGRA = period,
TGRB = duty), which is the only RX timer that pairs a period register with a 50 % duty
compare and is normally fed from PCLK. **[I]** Neither the peripheral's exact name nor its
clock input can be confirmed without the part number.

---

## 2. Objective 2 — clock and prescaler

**[C]** No prescaler field is ever written for this channel: the setup writes only
`period`, `duty`, two compare registers and the mode bytes at `0xC1202`/`0xC1204`/`0xC1205`.
The counter therefore runs on the **undivided peripheral clock** of that block.

**[C]** The system-clock table that the same init path uses is at `0xFFFA32F0`, and it stores
the resulting frequency in Hz at `0x3AB38+172`:

| case | SCKCR (`0x80020`) change | stored Hz | value |
|---|---|---|---|
| 0 | `bset #16` | `0x3938700` | 60 000 000 |
| 1 | `or #0x90000` | `0x2625A00` | 40 000 000 |
| 2 | `bset #17` | `0x1C9C380` | 30 000 000 |
| 3 | `or #0x30000` | `0xE4E1C0` | 15 000 000 |
| 4 | `bset #18` | `0x7270E0` | 7 500 000 |

So the hardware's possible peripheral clocks are **60 / 40 / 30 / 15 / 7.5 MHz**. The
firmware does not tell us which case is selected at run time without knowing the value it is
called with (`[r0]` is an argument).

**[O] This is the one genuinely unresolved number**, and it directly decides the beep pitch:

| f_timer | beep f = f/15000 |
|---|---|
| 60 MHz | **4000.0 Hz** |
| 40 MHz | 2666.7 Hz |
| 30 MHz | 2000.0 Hz |
| 15 MHz | 1000.0 Hz |
| 7.5 MHz | 500.0 Hz |

> **SUPERSEDED — see `CLOCK_AND_PATCH.md`.** The 60 MHz working hypothesis below is
> **withdrawn**: every immediate clock-mode argument in the image is **2**, and mode 2
> records **30 MHz**, not 60 MHz. The candidate pitches are therefore **2000 Hz** (30 MHz)
> or **1000 Hz** (15 MHz), never 4000 Hz. The text below is kept for the reasoning trail.

A 4 kHz piezo tone is by far the most plausible of these for a radar detector, and 60 MHz is
the first/default table entry, so **[I] 4000 Hz is the working hypothesis**. It is *not*
confirmed.

Note the arithmetic coincidence worth recording and *not* relying on: `120 MHz / 15000` is
exactly 8000 Hz, which would make the clip channel an 8 kHz stream and would "confirm" the
8 kHz ADPCM assumption. 120 MHz is **not** in the clock table, so that route is unsupported.
A content-based check was attempted instead (energy above 1.8 kHz across the 25 referenced
clips): the median is 0.14 % of total energy, with a maximum of 19 % (clip 115). That is far
too little high-frequency content to separate 4 kHz from 8 kHz recording, so **the clip rate
remains unconfirmed** and the 8 kHz figure stays an assumption.

---

## 3. Objective 3 — frequency produced by period `0x3A98`

**[C]** `0x3A98` = 15000. `0xFFFB2BA1` writes `d−1` = 14999 and `(d−1)>>1` = 7499, so the
counter counts 15000 states and the compare flips at 7500 → **50 % duty**.

`f_out = f_timer / 15000` → **4000 Hz** under the 60 MHz hypothesis (250 µs period,
125 µs high, 125 µs low), 2666.7 Hz / 2000 Hz / 1000 Hz / 500 Hz for the other table entries.

Sanity check on the boot config: period `0x3B2E` = 15150, duty `0x1D97` = 7575, which is
exactly half of 15150 — the same 50 % relationship, and 15150 rather than 15000 is the
"parked" value written before any beep (it produces 3960.4 Hz at 60 MHz). Playback then
re-writes 15000 on every beep.

---

## 4. Objective 4 — every call to `0xFFFB2BA1`

**[C] Nine call sites, all direct `bsr.a`; the function's address is never taken, so there are
no indirect or computed calls.** Argument per site:

| site | argument | context |
|---|---|---|
| `0xFFF863FD` | `0x3A98` | alert handler, type 1 |
| `0xFFF86410` | `0x3A98` | alert handler, type 2 |
| `0xFFF86434` | `0x3A98` | alert handler, type 3 |
| `0xFFF93C4B` | `0x3A98` | beep state machine, state 1 (first pulse) |
| `0xFFF93CDD` | `0x3A98` | beep state machine, state 4 (second pulse) |
| `0xFFF93D3A` | `0x3A98` | blocking 3-pulse beep, pulse 1 |
| `0xFFF93D5B` | `0x3A98` | blocking 3-pulse beep, pulse 2 |
| `0xFFF93D7C` | `0x3A98` | blocking 3-pulse beep, pulse 3 |
| `0xFFF93DA2` | **variable** (loaded from `[r0]`) | blocking beep with caller-chosen period |

```
fff863fd: bsr.a fffb2ba1     fff86410: bsr.a fffb2ba1     fff86434: bsr.a fffb2ba1
fff93c4b: bsr.a fffb2ba1     fff93cdd: bsr.a fffb2ba1
fff93d3a: bsr.a fffb2ba1     fff93d5b: bsr.a fffb2ba1     fff93d7c: bsr.a fffb2ba1
fff93da2: bsr.a fffb2ba1
```

**[C]** Eight of nine sites pass the identical constant. `0xFFF93DA2` is the only site that
can produce a different pitch, and it is reached only from the blocking-beep entry
(`0xFFF93D2B…`), i.e. from **menu / self-test sounds**, not from radar alerts.

---

## 5. Objective 5 — the X / K / Ka / laser alert paths

The alert handler `0xFFF863CF` is the only place that both starts a beep and paints the
screen for an alert:

```
fff863cf: mov.l #0x8c022, r14
fff863d4: bset  #2, [r14].b            ; amp/output enable, common to all types
         ... dispatch on 32[alert] ...
type 1 -> 0xFFF863F0: 0xFFF7F862(0xFFFF) ; 0xFFFB2BA1(0x3A98)
type 2 -> 0xFFF86404: 0xFFF7F862(0x4FE0) ; 0xFFFB2BA1(0x3A98)
type 3 -> 0xFFF86417: 0xFFF7F862(0x537E) ; bset #0,[0x8C022] ; 61[0x4C5D4]=1 ; 0xFFFB2BA1(0x3A98)
type 4 -> 0xFFF8643B: 0xFFF7F862(0xF803)
type 5 -> 0xFFF86447: 0xFFF7F862(0xFFE0)
```

**[C] `0xFFF7F862` is a screen fill, not audio.** It splits the 16-bit value into two bytes
and writes the pair 5120 times over `0x00800000`/`0x00800001` (`cmp #0x2800` loop bound), i.e.
it fills a 10 KiB RGB565 framebuffer with one colour. `0xFFFF`, `0x4FE0`, `0x537E`, `0xF803`,
`0xFFE0` are colours (white, cyan-green, blue-green, red, yellow), **not** tones.

**Consequences [C]:**
* every band's beep uses the *same* period → **identical pitch**;
* types 1–3 beep, types 4–5 change colour only;
* the band identity that a user perceives per type is colour + cadence;
* **[O]** which of types 1–5 is X / K / Ka / laser is **not** established. The mapping from
  the detector's band code (`0x10`=X, `0x20`=K, `0x30`/`0x05`=Ka, `0x80`=MRCD, decoded earlier
  from `0xFFF86700–0xFFF86900`) to the 1–5 dispatch index was not traced to a specific
  compare; that is the next concrete step and it needs the record's band byte followed into
  `32[alert]`.

---

## 6. Objective 6 — can bands use different periods?

**Yes, mechanically.** Each beep is one call to `0xFFFB2BA1(d)`, so giving a band its own
pitch means giving its call site its own constant — a 6-byte `mov.l #imm, r1` per site, in
place, with no size change. The three alert sites (`0xFFF863FD`, `0xFFF86410`, `0xFFF86434`)
are exactly the places to change, and there is no shared "current pitch" variable to update.

Constraints to respect:

1. **16-bit period.** `d` must be ≤ 65535, so with a 60 MHz clock the lowest reachable
   frequency is 60e6/65536 = **915.5 Hz**; `d = 60000` gives 1000 Hz. Frequencies needing a
   larger divisor would require also changing the timer's prescaler, which the firmware never
   touches — that would be a real code change, not a data change.
2. **No interference with other sounds.** The beep channel (`0xC1218`, start bit 6) is
   separate from the clip channel (`0xC1228`, start bit 7). Changing a beep period cannot
   alter a voice announcement. The only shared resources are:
   * `0x8C022` bit 2 (amp enable) — sequential use only;
   * `0x4C5D4+120` (busy flag) — `0xFFFB2BA1` stops the *clip* channel when it finds the
     player busy (`cmp #1` → `bclr #7`), so a beep always pre-empts a clip. That behaviour is
     unchanged by a period edit.
3. `0xFFFB2BA1`'s first act is to stop a running beep (`0xFFFB25B7`) and to re-arm the amp,
   so successive beeps do not accumulate.

So per-band pitch is feasible **without touching the voice bank and without touching the
clip path** — the change is limited to the constants at the three alert call sites.

---

## 7. Objective 7 — signal strength to cadence

**[C]** The repetition rate is not a lookup table. The sparse beep engine
(`0xFFF93BDC`, state byte `0x19DE3`, tick counter `0x3AFC4+84`) runs:

```
state 0  0xFFF93C1E  if busy==0: busy=1 ; bset #2,[0x8C022] ; state=1
state 1  0xFFF93C47  0xFFFB2BA1(0x3A98) ; tick=0 ; state=2
state 2  0xFFF93C62  wait tick==50 -> 0xFFFA7752 (stop)
                     tick=0 ; if 0x4C5D4+136 == 1 -> state=3
                              else clear 0xAEB6 bit5, busy=0, state=0
state 3  0xFFF93CB9  wait tick==30 -> state=4
state 4  0xFFF93CDD  0xFFFB2BA1(0x3A98) ; tick=0 ; state=5
state 5  0xFFF93CF4  wait tick==50 -> 0xFFFA7752 ; clear bit5, busy=0, state=0
```

That is a **50 ms on / 30 ms off / 50 ms on** double pulse when `0x4C5D4+136 == 1`, and a
single 50 ms pulse otherwise. `0x4C5D4+136` has exactly one writer (`0xFFFA6080`, copying
`0xFFFA606E`'s argument) and one reader (`0xFFF93C83`, `cmp #1`), so it is a 0/1 selector, not
an ID.

`0xFFF93E0E` is the *retrigger* wrapper: it clears the amp bit, calls the engine, then
**resets the tick counter `0x3AFC4+78` to 0** and clears a flag at `0x3C188+9`. The 47 call
sites of the engine are each gated on `0x3AFC4+78` against a constant, and those constants are
the alert rate:

```
8, 24, 40, 56, 72, 88, 104, 120      (16-tick spacing, 0xFFF93F2C..0xFFF94045)
40, 120, 200, 280, 320               (0xFFF942B3..0xFFF9433F)
368                                  (0xFFF94893)
500                                  (0xFFF947A3)
```

**[C]** So cadence is coded as *compare chains over a tick counter*, in at least four families
of 16-tick-spaced thresholds. **[O]** The mapping from the alert record's SSM field (`64[rec]`,
printed by the trace string `Alerting: X, Freq:%d, Lock:%d, SSM:%d, Hang:%d`) to which chain is
selected was not recovered; the tick counter's own unit (1 ms vs 0.5 ms) is also unconfirmed,
so the table above is in ticks and the millisecond figure assumes 1 ms.

---

## 8. What is confirmed vs open

**Confirmed by disassembly [C]**
1. Beep = 16-bit timer, PWM mode, period `0xC1218`, 50 % duty `0xC121A`, start/stop bit 6 of
   `0xC1280`. Only writer `0xFFFB2BA1`.
2. Pitch is uniform for all radar alerts: 8 of 9 call sites pass `0x3A98` (15000); the only
   variable site belongs to menu/self-test beeps.
3. Clip audio is a separate channel: sample register `0xC1228`, start/stop bit 7 of
   `0xC1280`, fed by ISR `0xFFFB2E56` from a 40-word ring buffer at `0x712F4` (end `0x71344`),
   engine start `0xFFFB27C0`.
4. Per-band differences are framebuffer colour (`0xFFF7F862` writes `0x800000`, 5120 RGB565
   pixels) and cadence — not pitch, not clip choice, in the alert path.
5. Alert envelope: 50/30/50 ms double pulse, or a single 50 ms pulse.
6. Peripheral clock choices are 60/40/30/15/7.5 MHz, stored as Hz at `0x3AB38+172`.

**Open [O]**
1. Exact MCU part number — not present in the image; family evidenced, part not provable.
2. Which of the five clock modes is active → beep pitch is 4000 Hz *under hypothesis*.
3. Clip stream rate (4 kHz vs 8 kHz) — content analysis was inconclusive.
4. Which of alert types 1–5 is X / K / Ka / laser.
5. Which cadence chain corresponds to which SSM value.
6. Whether `0x8C022` bit 2 is an amplifier enable or a port direction bit; both audio paths
   touch it, so it is an audio gate either way.

**The single test that would close 1–3**: measure the beep with a microphone or a scope on the
buzzer pin. 4000 Hz vs 1000 Hz is not subtle, and it confirms the clock mode and the divisor in
one measurement. Nothing in this document should be treated as a licence to flash until then.

---

## 9. Hardware register cheat-sheet

```
0x00080000  I/O base                     0x00080010  bus control (bit 9 cleared at audio init)
0x00080020  SCKCR (clock select)         0x000803FE  write-protect unlock (0xA500 / 0xA502 / 0xA50B)
0x0008C000  port block base              0x0008C022  audio/output enable, bits 0/2/4 used
0x000C1200  audio timer block            +0x18 period  +0x1A duty  +0x24/+0x26 spare compare
                                         +0x28 clip sample register  +0x4C = 2
0x000C1280  start/stop: bit 6 beep, bit 7 clip
0x000C1300  second timer block (0x80 stride)     0x000C1380  third
0x0004C5D4  audio state struct (+120 busy, +136 pulse-count selector, +0x88 = 136)
0x00019DE3  beep state byte             0x0003AFC4  tick counters (+78 rate, +84 engine)
0x00019F4A  audio-active flag           0x00712F4   clip ring buffer struct (40 words)
0x000712D8  clip engine state           0x0071368   clip end threshold (2 × [0x7E6F4])
0x00800000  10 KiB display framebuffer (5120 × RGB565)
```
