# Beep call graph — band → sounder

Primary objective: connect each detected radar band to the routine that actually generates
the beep. Method is `tools/funcs.py` (function boundaries + `bsr` cross-references) and
`tools/dis_range.py`, not literal-offset matching.

Image base `0xFFF00000`, flat image `work/main_flat_fff00000.bin`
(sha256 `13545b58…c5789`, 1,048,576 bytes). All addresses below are absolute.

---

## 1. The bottom of the graph: one PWM writer

> **`0xFFFB2BA1` is the only code in the entire 1 MiB image that touches the beep timer.**

Searching every instruction for the timer base literal `0xC1218` returns **four** hits, all
inside `0xFFFB2BA1` (`0xFFFB2BD5`, `0xFFFB2BE2`, `0xFFFB2BE9`, `0xFFFB2BF1`). There is no
other writer, and no computed access to that base.

```
fffb2ba1:  sub   #8, r0                 ; frame
fffb2ba3:  mov.l r1, 4[r0]              ; ARG = r1 (period in timer ticks)
fffb2ba5:  bsr.a fffb25bf               ; "beep already active?" bookkeeping
fffb2ba9:  cmp   #0, r1
fffb2bab:  beq.s fffb2bb0
fffb2bac:  bsr.a fffb25b7               ;   restart path
fffb2bb0:  mov.l #0x19f4a, r14
fffb2bb6:  mov.b #1, [r14]              ;   busy flag
fffb2bb9:  mov.l #0x4c5d4, r14
fffb2bbf:  movu.b 120[r14], r14         ;   if config[+120] == 1
fffb2bc2:  cmp   #1, r14
fffb2bc4:  bne.b fffb2bd1
fffb2bc6:  bsr.a fffb25db               ;     stop tone first
fffb2bca:  mov.l #0x8c022, r14
fffb2bcf:  bclr  #2, [r14].b            ;     droop the buzzer/amp enable pin
fffb2bd1:  mov.l 4[r0], r1
fffb2bd3:  sub   #1, r1
fffb2bd5:  mov.l #0xc1218, r14
fffb2bda:  mov.w r1, [r14]              ; PERIOD  <- (arg - 1)      [0xC1218]
fffb2bdc:  mov.l 4[r0], r1
fffb2bde:  sub   #1, r1
fffb2be0:  shlr  #1, r1
fffb2be2:  mov.l #0xc1218, r2
fffb2be7:  mov.w r1, 2[r2]              ; DUTY    <- (arg - 1) >> 1 [0xC121A]
fffb2be9:  mov.l #0xc1218, r1
fffb2bee:  mov.w #0, 12[r1]             ; clear compare A
fffb2bf1:  mov.l #0xc1218, r1
fffb2bf6:  mov.w #0, 14[r1]             ; clear compare B
fffb2bf9:  bsr.a fffa774a               ; start the timer
fffb2bfd:  mov.l #0x8c022, r14
fffb2c02:  movu.b [r14], r14
fffb2c04:  bfmovz #2, #0, #1, r14, r14  ; r14 = !bit2
fffb2c09:  cmp   #0, r14
fffb2c0b:  beq.s fffb2c10
fffb2c0c:  mov.l #0, [r0]
fffb2c0f:  bra.s fffb2c13
fffb2c10:  mov.l #1, [r0]
fffb2c13:  mov.l [r0], r1
fffb2c15:  cmp   #0, r1
fffb2c17:  beq.s fffb2c21               ; pin already on -> leave it
fffb2c18:  mov.l #0x8c022, r14
fffb2c1d:  bset  #2, [r14].b            ; enable the buzzer/amp pin
fffb2c1f:  rtsd  #8
```

Signature: **`void tone(uint16 period_ticks)`**, one register argument (`r1`).
The duty is derived, never passed. At the measured 15 MHz, `tone(15000)` = 999.98 Hz.

Consequence: **frequency is decided by the caller's argument, and by nothing else** — no
timer prescaler, no second register, no per-band table.

---

## 2. The three wrappers

Only three functions call `0xFFFB2BA1`. Their call sites and the register state are:

| wrapper | call sites | period passed | role |
|---|---|---|---|
| `0xFFF93BCF` | `0xFFF93C4B`, `0xFFF93CDD` | `0x3A98` = 15000 | **radar alert sounder** (repeating) |
| `0xFFF93D2B` | `0xFFF93D3A`, `0xFFF93D5B`, `0xFFF93D7C` | `0x3A98` = 15000 | triple burst (start-up / alarm) |
| `0xFFF93D9C` | `0xFFF93DA2` | **`2[r0]` — a variable** | generic UI beep |

`0xFFF93D9C` is the only place in the firmware where the beep frequency is not a literal:

```
fff93d9c:  sub   #4, r0
fff93d9e:  mov.w r1, 2[r0]        ; save caller's period
fff93da0:  movu.w 2[r0], r1
fff93da2:  bsr.a fffb2ba1         ; tone(period)
fff93da6:  mov.l #0x4c5d4, r14
fff93dac:  mov.b #1, 52[r14]
```

It has **42 callers**, all inside `0xFFF93E97`–`0xFFF94461` — the menu/UI sound player.
None of them is in the radar path. So even the parameterised entry is not band-aware.

### The radar sounder is a state machine

`0xFFF93BCF` is called from `0xFFF94AE2`, which is called from `0xFFFA40D5`.

```
fff93bcf:  mov.l #0x3c188, r1
fff93bd5:  movu.b 22[r1], r1
fff93bd7:  cmp   #1, r1
fff93bd9:  beq.w fff93d2a            ; muted by config[0x3C188+22]
fff93bdc:  mov.l #0xaeb6, r14
fff93be2:  movu.b [r14], r14
fff93be4:  bfmovz #5, #0, #1, r14, r14
fff93be9:  cmp   #0, r14
fff93beb:  beq.w fff93d2a            ; returns when bit 5 of 0xAEB6 is SET
fff93bee:  mov.l #0x3afc4, r1
fff93bf4:  mov.l 84[r1], r2
fff93bf6:  add   #1, r2
fff93bf8:  mov.l r2, 84[r1]          ; tick counter 84[0x3AFC4] += 1
fff93bfa:  mov.l #0x19de3, r14
fff93c00:  movu.b [r14], r14         ; state = [0x19DE3]
```

The state byte `0x19DE3` selects the branch; the counter `84[0x3AFC4]` is compared against
50 and 30:

| state | action | next |
|---|---|---|
| 0 | set `120[0x4C5D4]=1`, `bset #2,[0x8C022]`, state=1 | 1 |
| 1 | `tone(15000)` (`0xFFF93C47`), counter=0, state=2 | 2 |
| 2 | at counter == **50**: stop (`0xFFFA7752`); if `136[0x4C5D4]==1` → state=3, else clear pin, `120[0x4C5D4]=0`, state=0 | 3 or 0 |
| 3 | at counter == **30**: counter=0, state=4 | 4 |
| 4 | `tone(15000)` (`0xFFF93CD9`), counter=0, state=5 | 5 |
| 5 | at counter == **50**: stop, `bclr #5,[0xAEB6]`, clear pin, state=0 | 0 |

That is **50 ms on / 30 ms off / 50 ms on, repeating every 80 ms** — precisely the measured
Ka cadence. The `136[0x4C5D4]` branch selects single beep (state 0 → 2 → 0) versus double.

---

## 3. The alert display path — the "three PWM branches" are colours, not bands

Correcting an earlier reading of this file: the block at `0xFFF863CF` is **not** the radar
beep. It is the display-flash handler for a *colour index*, and the beep is a side effect.

```
fff863cf:  mov.l #0x8c022, r14
fff863d4:  bset  #2, [r14].b         ; enable buzzer/amp first
fff863d6:  mov.l 60[r0], r1          ; r1 = ctx->item  (item pointer at ctx+60)
fff863d8:  movu.b 32[r1], r14        ; class = item->+32
fff863db:  cmp   #5, r14  ; beq fff86447
fff863df:  cmp   #2, r14  ; beq fff86404
fff863e3:  cmp   #3, r14  ; beq fff86417
fff863e7:  cmp   #4, r14  ; beq fff8643b
fff863eb:  cmp   #1, r14  ; bne fff865a4
; class 1
fff863f0:  mov.l #0xffff, r1         ; colour 0xFFFF = white
fff863f5:  bsr.a fff7f862            ; fill framebuffer
fff863f9:  mov.l #0x3a98, r1
fff863fd:  bsr.a fffb2ba1            ; tone(15000)
; class 2
fff86404:  mov.l #0x4fe0, r1         ; cyan
fff8640c:  mov.l #0x3a98, r1
fff86410:  bsr.a fffb2ba1            ; tone(15000)
; class 3
fff86417:  mov.l #0x537e, r1         ; blue
fff8641b:  bsr.a fff7f862
fff8641f:  mov.l #0x8c022, r14
fff86424:  bset  #0, [r14].b         ; a second pin, bit 0
fff86426:  mov.l #0x4c5d4, r14
fff8642c:  mov.b #1, 61[r14]         ; enable double beep
fff86430:  mov.l #0x3a98, r1
fff86434:  bsr.a fffb2ba1            ; tone(15000)
; class 4
fff8643b:  mov.l #0xf803, r1         ; red  (no tone)
fff86440:  bsr.a fff7f862
; class 5
fff86447:  mov.l #0xffe0, r1         ; yellow (no tone)
```

The five arguments are RGB565 display values, and `0xFFF7F862` is the framebuffer fill
(10 KiB at `0x00800000`). So classes 1–5 are **white, cyan, blue, red, yellow** — a visual
style index. Three of the five happen to beep; two do not. That is the whole explanation for
"three PWM branches", and it means the branches do **not** encode X, K and Ka.

The sibling block at `0xFFF86360` reads the same byte with a six-way range (1..6) and forwards
`r1 = class-1`, `r2 = ctx+36`, `r3 = 1` to `0xFFF82A3D` — again a display/serialise call, no
tone. The same field is read **63 times** across the image, which is why it is a style byte
rather than a band.

---

## 4. Laser

The laser handler chain starts at `0xFFF78F0A`, whose callees are exactly:
`0xFFF79030`, `0xFFFC6E00` (log printf), `0xFFF87DD2`, and a branch to `0xFFF79205`.

```
fff79030:  mov.l 104[r0], r1
fff79032:  add   #1, r1
fff79034:  mov.l r1, 104[r0]         ; laser hit counter
fff79036:  mov.l #0x3b218, r14
fff7903c:  movu.b 33[r14], r14
fff7903f:  cmp   #0, r14
fff79041:  beq.b fff7906f            ; silent when config[+33]==0
fff79043:  ... #0xfff72b51 = "Laser Alert: %d" ...
fff7905d:  bsr.a fffc6e00            ; log only
fff7906b:  bsr.a fff87dd2
fff7906f:  ... store thresholds ...
fff79092:  bra.w fff79205            ; continue in the tracker
```

There is **no call to `0xFFFB2BA1`** and none to `0xFFF93BCF` anywhere in this chain, and no
write to the `0xAEB6` mute/alert flag. So the laser path in this firmware version does not
generate a tone of its own: it logs, updates the hit counter, and hands off to the tracking
code at `0xFFF79205`. Any laser sound the user hears must therefore come from the shared
sounder being enabled elsewhere (the flag/state the engine reads), not from a laser-specific
beep routine. **[O]** which caller enables it for a laser event was not traced to a specific
instruction; the laser chain is short enough to settle with one breakpoint on `0xFFFB2BA1`.

---

## 5. Does the Ka beep come from the three immediate sites or from the engine?

**Answer: from the engine (`0xFFF93BCF`), not from the three display sites.**

Reasoning, in order of strength:

1. The display sites at `0xFFF863F9`/`0xFFF8640C`/`0xFFF86430` are guarded by the colour byte
   and fire **once per item insertion**, immediately after `0xFFF7F862` repaints the frame.
   A single `tone()` call sets a period and enables the pin — it does not schedule an end.
2. The measured Ka alert is a **repeating** 50 on / 30 off / 50 on pattern over many cycles.
   The only code that produces that pattern is the `0x19DE3` state machine, whose 50 and 30
   are counter limits in milliseconds (confirmed by the recording: 50.0 and 30.0 ms).
3. Therefore the engine was running during the recording, and it issues `tone(15000)` at
   `0xFFF93C47` and `0xFFF93CD9` — the two "generic" sites.

**But the distinction does not change the pitch.** All eight constant call sites pass
`0x3A98` = 15000, so every path in the firmware produces 999.98 Hz. The three display sites
and the engine sites are interchangeable as far as frequency goes; they differ only in
cadence and in what else they touch (framebuffer vs. state machine).

**[O]** Patching only the three display sites would leave the engine at 15000 and the Ka
tone unchanged. The site that matters for the audible alert is the engine pair.

---

## 6. The call graph

```
 radar band code (0x10 X / 0x20 K / 0x30 Ka / 0x80 MRCD)
        │                    proven earlier from the per-branch log strings
        ▼
 alert record  ──────────────────────────────────────────────┐
        │                                                    │
        │ ctx+60 → item                                      │ alert-active / mute state
        ▼                                                    ▼
 item renderer 0xFFF863CF                            0xFFFA40D5
   item->+32 = colour index 1..5                            │
   1 white / 2 cyan / 3 blue → tone(15000)                  ▼
   4 red  / 5 yellow        → silent                 0xFFF94AE2
        │                                                    │
        │                                                    ▼
        │                                          sounder state machine 0xFFF93BCF
        │                                          state 0..5 on 0x19DE3
        │                                          counter 84[0x3AFC4] vs 50 / 30
        │                                                    │
        │                              ┌─────────────────────┤
        │                              ▼                     ▼
        │                      0xFFF93C47             0xFFF93CD9
        │                      tone(15000)            tone(15000)
        │                              └─────────┬───────────┘
        └────────────────────────────────────────┤
                                                 ▼
                                       0xFFFB2BA1  tone(period)
                                       period-1 → [0xC1218]
                                       (period-1)>>1 → [0xC121A]
                                       clear +12 / +14, start timer 0xFFFA774A
                                       bset #2,[0x8C022]  (buzzer/amp on)
```

**There is no edge in this graph that carries the band.** The band code reaches the record and
the logs, but no branch anywhere selects a period by band. The firmware has exactly one radar
tone; "band → tone" is a constant function, which is why the earlier search for a band→class
writer kept failing: it does not exist.

---

## 7. What this means for a future patch (nothing built yet)

* The single choke point is `0xFFFB2BA1`. Nothing else writes `0xC1218`.
* To give X, K and Ka different pitches it is **not enough** to edit the three display
  immediately-loaded values: the audible alert comes from the engine's two sites
  (`0xFFF93C47`, `0xFFF93CD9`), and the UI beeper `0xFFF93D9C` is already parameterised.
* Two viable shapes, both still unbuilt:
  1. patch the engine pair plus the display trio (5 × 4-byte `mov.l #imm, r1`), keeping
     cadence untouched — but then every band still sounds alike, because no band value is in
     scope at those sites;
  2. make the engine read the band from the record it is already servicing and compute
     `period = 15e6 / f_band`, which requires proving which field holds the band — the open
     item in `BAND_MAP.md`.
* Either way, `mov.l #0x3A98, r1` is `fb 1a 98 3a` = `fb 1a <imm16 LE>`; only bytes [2:4]
  change, as verified in `CLOCK_AND_PATCH.md`.

## 8. The measurement that closes the last gap

Breakpoint `0xFFFB2BA1`, log the **return address** and `r1`:

* return `0xFFF863FD` / `0xFFF86410` / `0xFFF86434` → display path fired;
* return `0xFFF93C4B` / `0xFFF93CDD` → engine fired (expected for a sustained Ka alert);
* return `0xFFF93DA2` → the UI beeper.

`r1` should read `0x3A98` in every case. That single log line confirms or refutes §5 outright.
