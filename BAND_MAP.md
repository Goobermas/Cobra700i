# Radar band → alert path (priority 1)

All excerpts are from `work/main_full.dis` (binutils 2.42 `rx-elf`, image based at
`0xFFF00000`), reproduced verbatim by `tools/dis_range.py LO HI`.
`rec` = the alert record; `r0` is the display/alert context the handler works on.

---

## What is proven

The alert sound selection is **three stacked dispatch layers**, not one table. Each is
located exactly; the values in each layer are known.

### Layer 1 — handler selection on `12[rec]`

```
fff86313: mov.l 60[r0], r1        ; r1 = rec
fff86315: mov.l 12[r1], r1        ; r1 = 32-bit field at offset 12
fff86317: cmp   #0, r1
fff86319: bne.s fff86320
fff8631a: mov.l #0, [r0]          ; 0 -> nothing
fff8631d: bra.w fff865a7
fff86320: mov.l #3, r1
fff86322: bsr.a fff7fa26          ; stop any current sound
fff86326: bsr.a fffa7752          ; bclr #6,[0xC1280]   -- stop beep channel
fff8632a: bset  #2, [0x8C022]  / bclr #0  / 61[0x4C5D4]=0
fff8633d: bsr.a fff7f862          ; repaint framebuffer (0)
fff86341: mov.l 60[r0], r1
fff86343: mov.l 12[r1], r1
fff86345: cmp   #6, r1 ; beq.w fff86598
fff8634a: cmp   #2, r1 ; beq.w fff863cf     <-- colour + beep path
fff8634f: cmp   #3, r1 ; beq.w fff86453
fff86354: cmp   #4, r1 ; beq.w fff864f6
fff86359: cmp   #5, r1 ; beq.w fff8652f
fff8635e: cmp   #1, r1 ; bne.w fff865a4
```

`12[rec]` ∈ **1..6**. Only value **2** reaches the colour+beep block that priority 3
patches; 1, 3, 4, 5 and 6 have their own handlers.

### Layer 2 — band/colour index on `32[rec]`, and the beep

```
fff863cf: mov.l #0x8c022, r14
fff863d4: bset  #2, [r14].b               ; audio/output enable
fff863d6: mov.l 60[r0], r1
fff863d8: movu.b 32[r1], r14              ; r14 = byte at offset 32
fff863db: cmp   #5, r14 ; beq.b fff86447
fff863df: cmp   #2, r14 ; beq.b fff86404
fff863e3: cmp   #3, r14 ; beq.b fff86417
fff863e7: cmp   #4, r14 ; beq.b fff8643b
fff863eb: cmp   #1, r14 ; bne.w fff865a4
```

| `32[rec]` | colour (`0xFFF7F862`) | beep `0xFFFB2BA1` | extra |
|---|---|---|---|
| 1 | `0xFFFF` white | `0x3A98` | — |
| 2 | `0x4FE0` cyan | `0x3A98` | — |
| 3 | `0x537E` blue | `0x3A98` | `bset #0,[0x8C022]`, `61[0x4C5D4]=1` |
| 4 | `0xF803` red | none | — |
| 5 | `0xFFE0` yellow | none | — |
| 0 / >5 | — | — | falls to `0xFFF865A4` |

So there are **five band classes**, three of which beep, and all three beep at the same
period. The beep sites are `0xFFF863F9` / `0xFFF8640C` / `0xFFF86430`.

### Layer 3 — raw band/event code, and a second sound generator

`0xFFF867A6` reads the **raw band byte at offset 33**:

```
fff867a6: movu.b 33[r14], r14
```

and a separate 32-bit **event code at offset 0 of `4[r0]`** is dispatched here:

```
fff867ee: mov.l 4[r0], r1
fff867f0: mov.l [r1], r14            ; 32-bit event code
fff867f2: cmp   #5,   r14 ; beq.b  fff86867
fff867f6: cmp   #128, r14 ; beq.w  fff86894      ; 0x80
fff867fc: cmp   #32,  r14 ; beq.b  fff8683a      ; 0x20
fff86801: cmp   #48,  r14 ; beq.b  fff86867      ; 0x30
fff86806: cmp   #16,  r14 ; bne.w  fff868bf      ; 0x10
```

Each branch collects four parameters from the record and calls the same generator:

```
fff8680c: mov.l 4[r0], r1
fff8680e: movu.b 64[r1], r2          ; level / SSM-ish
fff86811: movu.b 4[r1],  r3
fff86813: movu.b 25[r1], r4
fff86815: add   #-20, r0, r0
fff86818: mov.l r2, 16[r0]
fff8681a: mov.l r3, 12[r0]
fff8681c: mov.l r4,  8[r0]
fff8681e: mov.l 20[r1], 4[r0]
fff86822: mov.l #0xfff7395c, r14     ; pattern/sequence table
fff86828: mov.l r14, [r0]
fff8682a: mov.l #0x16b09, r1
fff86830: bsr.a fffc6e00             ; sequence player(entry)
fff86837: bra.w fff868bf
```

The constants `0x10` (X), `0x20` (K), `0x30` (Ka) and `0x80` (MRCD) recovered earlier are
exactly the case values of this dispatch, plus a fifth case `5`. `0xFFFC6E00` with table
`0xFFF7395C` is a **second, table-driven sound sequence generator**, separate from the
`0xC1218` beep channel.

---

## What is NOT proven

**[O] The assignment of `0x10/0x20/0x30/0x80` to X / K / Ka / MRCD is not established by
this trace.** The codes exist and are compared here, but the producer that *writes* the
event code into offset 0 of the record — i.e. the code that turns a detected radar band
into one of these constants — has not been located. Nor is the translation from band code
(offset 33 / event code) to the 1..5 colour-and-beep index of layer 2 traced.

Stating it plainly, because it matters for patching: **it is not yet proven which layer-2
index is X, which is K, and which is Ka.** Patching the three beep sites would therefore
change *some* three of the five band classes, and we cannot yet say which bands hear which
new pitch. The hardware conclusion is unaffected — all beeping classes share one period —
but a per-band pitch assignment is not safe to commit until this last link is traced.

Next concrete step: find the writers of the record fields `[rec+0]`, `[rec+32]`, `[rec+33]`.
The detector's own trace string `Alerting: X, Freq:%d, Lock:%d, SSM:%d, Hang:%d` sits in
the same module (`0xFFF86700` region), so the band byte is almost certainly produced in
that call chain; breakpointing one X alert and one K alert on hardware would settle it in
minutes.

---

## Correction to earlier notes

An earlier draft described "alert type dispatch on `32[r1]`" as *the* dispatch. It is the
**second** of three layers. The first (`12[rec]`) is what chooses the handler, and the
third (`[rec+0]`) drives the table-based sequence generator. Layer 2 is the only one that
starts the beep channel.
