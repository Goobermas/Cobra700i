# Radar band → alert path (priority 1)

All excerpts from `work/main_full.dis` (binutils 2.42 `rx-elf`, image base `0xFFF00000`),
reproduced by `tools/dis_range.py LO HI`. `rec` = alert record; `r0` = handler context.

---

## 1. Band codes — now proven

The dispatch at `0xFFF867EE` compares a 32-bit **event code** at `[4[r0] + 0]` against five
values, and each branch formats a log line with a *different format string*:

```
fff867ee: mov.l 4[r0], r1
fff867f0: mov.l [r1], r14          ; event code
fff867f2: cmp   #5,   r14 ; beq.b  fff86867
fff867f6: cmp   #128, r14 ; beq.w  fff86894      ; 0x80
fff867fc: cmp   #32,  r14 ; beq.b  fff8683a      ; 0x20
fff86801: cmp   #48,  r14 ; beq.b  fff86867      ; 0x30
fff86806: cmp   #16,  r14 ; bne.w  fff868bf      ; 0x10
```

The string each branch loads is conclusive:

| branch | code | loads | string at that address |
|---|---|---|---|
| `0xFFF8680C` | **`0x10`** | `0xFFF86822: mov.l #0xfff7395c` | `"Alerting: X, Freq:%d, Lock:%d, SSM:%d, Hang:%d"` |
| `0xFFF8683A` | **`0x20`** | `0xFFF86850: mov.l #0xfff7398c` | `"Alerting: K, Freq:%d, Lock:%d, SSM:%d, Hang:%d"` |
| `0xFFF86867` | **`0x30` and `0x05`** | `0xFFF8687D: mov.l #0xfff739bc` | `"Alerting: Ka, Freq:%d, Lock:%d, SSM:%d,Hang:%d"` |
| `0xFFF86894` | **`0x80`** | `0xFFF868AA: mov.l #0xfff739ec` | `"Alerting: MRCD, Freq:%d, Lock:%d, SSM:%d,Hang:%d"` |

**[C] Band codes: `0x10` = X, `0x20` = K, `0x30` = Ka, `0x05` = Ka (second Ka code),
`0x80` = MRCD/MRCT.** Both Ka codes share one branch, so they are the same band family.

This closes the earlier open item: the codes are no longer guesses from string proximity —
each is tied to its own format string inside its own branch.

**Correction to the previous revision of this file:** `0xFFF7395C` was described there as a
"pattern table" fed to a sound generator. It is a **printf format string**, and
`0xFFFC6E00` is the logging/format routine. This dispatch produces trace output; it does
**not** produce audio.

---

## 2. Laser is a separate path — and it does not beep

Laser is **absent** from the five event codes above. It has its own handler, anchored by the
string pointer literal found at `0xFFF79051`:

```
fff79030: mov.l 104[r0], r1
fff79032: add   #1, r1
fff79034: mov.l r1, 104[r0]                 ; laser event counter
fff79036: mov.l #0x3b218, r14
fff7903c: movu.b 33[r14], r14               ; 0x3B239 -- laser logging enable
fff7903f: cmp   #0, r14
fff79041: beq.b fff7906f
fff79043: mov.l #0x3b074, r14
fff79049: sub   #8, r0
fff7904b: mov.l 8[r14], 4[r0]               ; laser data field
fff7904f: mov.l #0xfff72b51, r14            ; "Laser Alert: %d \n"
fff79055: mov.l r14, [r0]
fff79057: mov.l #0x16b09, r1
fff7905d: bsr.a fffc6e00                    ; log
fff79061: add   #8, r0
fff79063: mov.l #0x7e53c, r14
fff79069: mov.l [r14], r1
fff7906b: bsr.a fff87dd2                    ; laser alert post-processing
fff7906f: mov.l #0x3ab2c, r14
fff79075: mov.l [r14], r14
fff79077: mov.l [r14], 92[r0]
fff7907a: mov.l #0x3ab2c, r14
fff79080: mov.l [r14], r14
fff79082: mov.l #0x3b034, r15
fff79088: mov.l [r14], 36[r15]
fff7908b: mov.b #0, 111[r0]
fff7908f: mov.l #0, 100[r0]
fff79092: bra.w fff79205
fff79095: mov.l 104[r0], r2
fff79097: mul   #68, r2
fff7909a: mov.l #0x397a8, r1
fff790a0: add   r2, r1
```

**[C] There is no `0xFFFB2BA1` call anywhere in this handler**, so laser does not configure
the PWM beep channel. Laser's audible alert must come from the clip/voice path or from
`0xFFF87DD2`, not from the `0xC1218` beep.

---

## 3. The audio path (layer 2) and why only three branches beep

The colour+beep block is reached only from layer 1 (`12[rec] == 2`) and dispatches on a
**byte at `32[rec]`**, five values, of which exactly three start a beep:

```
fff863d6: mov.l 60[r0], r1
fff863d8: movu.b 32[r1], r14
fff863db: cmp   #5, r14 ; beq.b fff86447     ; colour only
fff863df: cmp   #2, r14 ; beq.b fff86404     ; colour + beep
fff863e3: cmp   #3, r14 ; beq.b fff86417     ; colour + beep + 0x8C022 bit0
fff863e7: cmp   #4, r14 ; beq.b fff8643b     ; colour only
fff863eb: cmp   #1, r14 ; bne.w fff865a4     ; colour + beep
```

| `32[rec]` | colour | PWM period | notes |
|---|---|---|---|
| 1 | `0xFFFF` white | `0x3A98` at `0xFFF863F9` | |
| 2 | `0x4FE0` cyan | `0x3A98` at `0xFFF8640C` | |
| 3 | `0x537E` blue | `0x3A98` at `0xFFF86430` | also `bset #0,[0x8C022]`, `61[0x4C5D4]=1` |
| 4 | `0xF803` red | — | no beep |
| 5 | `0xFFE0` yellow | — | no beep |

**Why three:** the PWM period is written by exactly the branches that also call
`0xFFFB2BA1`. Branches 4 and 5 are colour-only, so they get their sound from somewhere else
— the same conclusion the laser evidence points to. Any class that does not reach
`0xFFFB2BA1` cannot use the beep channel.

---

## 4. What is still NOT proven — and why I am not guessing

### Correction: an earlier claim in this file was based on a broken search

A previous revision stated that no writer of `32[rec]` exists, because `mov.b #imm, 32[reg]`
and `mov.b reg, 32[reg]` returned zero matches. **That search was invalid**: the patterns
contained `\t`, which `grep -E` does not expand, so they were searching for a literal `t`.
Re-run with a correct parser over all 373,310 instructions, the real census is:

| access | count |
|---|---|
| readers `movu.b 32[rX]` | **63** |
| stores `mov.b #0/#1, 32[rX]` | ~166 |
| stores of any other constant | **1** (`0xFFF7F147: mov.b #4, 32[r14]`) |
| stores `mov.b rX, 32[rY]` | 52 |
| stores `mov.b #16/#32/#48/#128, 33[…]` | **0** |
| stores `mov.b rX, 33[rY]` | 5 (`0xFFF98C80`, `0xFFFA25F3`, `0xFFFA2692`, `0xFFFC92E9`, `0xFFFC92F8`) |

That census **undermines the "five-value class" reading** rather than confirming it: byte 32
is overwhelmingly a 0/1 flag with 63 readers, and the only other constant ever stored into it
is `#4`. A field that only ever holds 0/1 cannot exercise branches comparing it against 2, 3
and 5. So either the item at `60[r0]` is not the object compared at `0xFFF863D8`, or the
1..5 comparisons are on a field written by a path the census does not show (a wider store, a
struct copy, or the register stores above).

**Net effect: the band → audio-class mapping is not merely unproven, the static evidence for
the five-class model is now doubtful.** I am not going to resolve that by eye; it needs the
runtime value.

So, explicitly: **the three PWM branches are audio classes 1, 2 and 3. I cannot prove
which of those is X, K or Ka.** Two orderings remain possible (e.g. 1/2/3 = X/K/Ka, or
1/2/3 = Ka/X/K, etc.), and choosing one would be exactly the assumption this task forbids.

The display-name table does **not** resolve it: it is a localised *label* table, ordered
X, K-low, K, Ka, Laser, MultaRadar, LowVoltage with an EN/ES pair each —

```
0xFFF57C4C -> 'X BAND'      0xFFF57C50 -> 'BANDA X'
0xFFF57C54 -> 'K LOW BAND'  0xFFF57C58 -> 'BANDA K BAJA'
0xFFF57C5C -> 'K BAND'      0xFFF57C60 -> 'BANDA K'
0xFFF57C64 -> 'KA BAND'     0xFFF57C68 -> 'BANDA KA'
0xFFF57C6C -> 'LASER'       0xFFF57C70 -> 'LASER'
0xFFF57C74 -> 'MULTARADAR'  0xFFF57C78 -> 'MULTARADAR'
0xFFF57C7C -> 'LOW V. WARN' 0xFFF57C80 -> 'LOW V. WARN'
```

— which is a UI string table indexed by band, not by audio class (seven bands, not five
classes; and it contains no MRCD entry under that name).

### The two tests that would settle it

1. **Hardware, definitive:** breakpoint on `0xFFF863D8` (`movu.b 32[r1], r14`) and read
   `r14` **and the object `r1` points at** during one X alert and one K alert. Given the
   census above, dump 48 bytes from `r1` as well — that shows which offset actually carries
   the band, even if it is not 32. Five minutes with an E1/E2 and one detection.
2. **Static, slower:** find the writer by searching for the alert-record constructor —
   the object at `60[r0]` is produced by the caller of this handler; walking its callers
   and watching which routine zero-initialises bytes 30–40 (as `0xFFF862E3`–`0xFFF86311`
   does for a neighbouring record) will expose the assignment.

Until one of these is done, any per-band pitch assignment stays unproven and is not
implemented.

---

## 5. Correction to earlier notes

An earlier revision called `32[r1]` *the* dispatch and `0xFFF7395C` a sound table. Corrected
here: there are three layers — `12[rec]` (handler), `32[rec]` (audio class), `[rec+0]`
(event code, logging) — and the layer-3 target is a format string, not audio.

---

## See also

`BEEP_CALLGRAPH.md` traces the alert path to the actual tone routine and shows why
this file's "audio class" question had no answer: the five-way field is a display
colour index, and the firmware contains exactly one radar tone.
