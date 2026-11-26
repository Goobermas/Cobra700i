# RAD 700i — sound mapping (traced)

All addresses from `work/main_full.dis` (binutils 2.42 `rx-elf`, image based at
`0xFFF00000`). **[C]** = confirmed from disassembly, **[O]** = open/unconfirmed.

## Correction to the earlier report

**[C] Voice blocks 16 / 101 / 170 / 184 are never played.** There are 41 call
sites of the voice player `0xFFFB28CE`; 37 pass a hard-coded clip ID and none of
them is 16, 101, 170 or 184. Four sites pass a register (see below), so an
indirect path is not 100 % excluded, but nothing in the code references those
four blocks. They are most likely **unused/legacy assets**, which matches the
by-ear result: they are not radar chimes.

**⇒ The earlier "patched voice image" candidates target an unused asset and
should not be flashed.** They are retained only as a format demonstration.

---

## 1. `0xAEB6` bit 5 — the tone request latch

| Role | Address | Instruction |
|---|---|---|
| **set** | `0xFFFA6072` | `bset #5, [r14].b` — inside `0xFFFA606E(arg)` |
| **read** | `0xFFF93BE4` | `bfmovz #5, #0, #1, r14, r14` then `cmp #0` → `beq 0xFFF93D2A` (rts) |
| **clear** | `0xFFF93CA3` | `bclr #5` (normal completion) |
| **clear** | `0xFFF93D14` | `bclr #5` (long-sequence completion) |

Both clears are always accompanied by `mov.b #0, 0x4C5D4+120` (busy) and
`mov.b #0, [0x19DE3]` (state → 0).

**[C] bit 0 of the same byte is a different, unrelated flag**: 12 `btst #0`
readers (`0xFFF939BC`, `0xFFF99795`, `0xFFF99AA6`, `0xFFF99E73`, `0xFFF99F76`,
`0xFFF9CB6B`, `0xFFF9D796`, `0xFFF9D9E7`, `0xFFF9E4B1`, `0xFFF9E794`,
`0xFFF9EB81`, `0xFFFA3E5C`), 8 setters, 5 clearers. Generic pending-event latch.

## 2. The "tone index" storage is **not** a clip ID

| Location | Writers | Readers |
|---|---|---|
| `0x4C5D4 + 0x88` (136) | **one**: `0xFFFA6080` `mov.b 3[r0], 136[r14]` (copies `0xFFFA606E`'s argument) | **one**: `0xFFF93C83` `movu.b 136[r14]` → `cmp #1` |
| `0x4C5D4 + 0x78` (120) | busy flag, set/cleared by both players | polled as a spin-wait |
| `0x4C5D4 + 0x3D` (61) | set to 1 at `0xFFF8642C` (alert type 3) | — |
| `0x4C5D4 + 0x38` (56) | written at `0xFFFA54C8` context | `mov.l 56[r1], r1` → `play_voice` (**dynamic ID site**) |

**[C]** Only 0 or 1 are ever stored, and only `== 1` is tested. So this is a
**short-vs-long beep selector**, not a sound ID. The BLE "play tone" command
(`0xFFF7BC3E`) passes 0 or 1 → it triggers a *beep*, not a voice clip.

## 3. Playback chains — there are two, and they are separate

### (a) Beep engine (locally generated tone)

```
request          0xFFFA606E(arg)  -> 0xAEB6 |= 0x20 ; 0x4C5D4+0x88 = arg
state machine    0xFFF93BDC       state byte at 0x19DE3, tick counter 0x3AFC4+84
  state 0  0xFFF93C1E  if 0x4C5D4+120 == 0 -> set 120=1 ; bset #2,[0x8C022] ; state=1
  state 1  0xFFF93C47  0xFFFB2BA1(0x3A98) ; tick=0 ; state=2
  state 2  0xFFF93C62  wait tick==50 -> 0xFFFA7752 ; tick=0 ;
                       if 0x4C5D4+136 == 1 -> state=3
                       else clear bit5, 120=0, state=0
  state 3  0xFFF93CB9  wait tick==30 -> state=4
  state 4  0xFFF93CD9  0xFFFB2BA1(0x3A98) ; tick=0 ; state=5
  state 5  0xFFF93CF4  wait tick==50 -> 0xFFFA7752 ; clear bit5, 120=0, state=0
blocking variant 0xFFF93D2B(duration)  3 pulses, 60 ms on, `duration` off
```
`0xFFFB2BA1(d)` programs a **16-bit period with 50 % duty**:
```
0xC1218 = d-1
0xC121A = (d-1) >> 1
0xC1224 = 0
0xC1226 = 0
0xFFFA774A       (enable)
0xFFFA7752       bclr #6,[0xC1280]
```
Everything that programs it passes the **same constant `0x3A98` (15000)**:
`0xFFF863FD`, `0xFFF86410`, `0xFFF86434`, `0xFFF93C4B`, `0xFFF93CDD`,
`0xFFF93D3A`, `0xFFF93D5B`, `0xFFF93D7C`
(plus `0xFFF93DA2`, which passes a variable).

**[C]** ⇒ **beep pitch is identical for X, K, Ka and laser.** With a fixed
divisor there is no per-band pitch in this design.

### (b) Voice clip player

```
0xFFFB28CE(id):
   if 0x3BD94+196 == 1            -> 0xFFFA34B8(1) ; return   (voice unavailable gate)
   if [0x19F4A] == 1              -> bclr #2,[0x8C022] ; delay(10,1000000) ; 0xFFFA7752 ; delay(10,1000)
   bclr #2,[0x8C022]
   delay(10, 1000000)             ; 0xFFFA8797(a,b)
   0x4C5D4+120 = 1                ; busy
   while (0xFFF948D7() != 0)      ; spin
   0xFFF93DB2()                   ; run beep/voice engine step
   0x3AFC4+78 = 0
```
41 call sites, 25 distinct hard-coded IDs:
`2, 12, 13, 51, 52, 53, 54, 55, 56, 63, 69, 71, 78, 79, 83, 86, 104, 107,
110, 114, 115, 121, 132, 305, 306`
Plus 4 dynamic sites: `0xFFFA3D77`, `0xFFFA4F9B`, `0xFFFA4FB4`, `0xFFFA54C8`.

## 4. What actually differs per band

The alert handler branch at `0xFFF863CF` dispatches on `32[alert]`:

| type | handler | value passed to `0xFFF7F862` | additionally |
|---|---|---|---|
| 1 | `0xFFF863F0` | `0xFFFF` | `0xFFFB2BA1(0x3A98)` |
| 2 | `0xFFF86404` | `0x4FE0` | `0xFFFB2BA1(0x3A98)` |
| 3 | `0xFFF86417` | `0x537E` | `bset #0,[0x8C022]`, `61[@]=1`, `0xFFFB2BA1(0x3A98)` |
| 4 | `0xFFF8643B` | `0xF803` | — |
| 5 | `0xFFF86447` | `0xFFE0` | — |

**[C] `0xFFF7F862` is not audio.** It splits the value into two bytes and writes
that pair 5120 times to `0x00800000`/`0x00800001` (`cmp #0x2800` loop) — i.e. it
**fills a 10 KiB display buffer with a 16-bit colour**. `0xFFFF`, `0x4FE0`,
`0x537E`, `0xF803`, `0xFFE0` are RGB565 colours, not pitches.

⇒ **[C] Bands are distinguished by (i) display colour and (ii) beep cadence —
not by tone pitch and not by different stored clips** (in this path).

## 5. Cadence / repetition

Tick counter `0x3AFC4+78` is compared against fixed thresholds inside the 47
call sites of `0xFFF93DB2`, e.g.:
- `8, 24, 40, 56, 72, 88, 104, 120` (`0xFFF93F2C … 0xFFF94045`) — 16-tick spacing
- `40, 120, 200, 280, 320` (`0xFFF942B3 … 0xFFF9433F`)
- `368` (`0xFFF94893`), `500` (`0xFFF947A3`)

**[C]** Cadence is therefore a per-alert-type compare chain, not a lookup table.
**[O]** The exact SSM→interval mapping was not extracted; the alert record carries
SSM at `64[rec]` and a hang counter at `64[rec]`/`65[rec]` (see trace strings
`Alerting: X, Freq:%d, Lock:%d, SSM:%d, Hang:%d`).

## 6. Open items

1. **[O]** Whether `0x8C022` bit 2 / bit 0 are the audio-amp enable or LCD
   control lines (both appear in beep *and* voice paths → suggestive of a shared
   audio enable, but not proven).
2. **[O]** Which of alert types 1–5 corresponds to X / K / Ka / laser / MRCD.
3. **[O]** Whether the "chime" heard on hardware is the `0x3A98` beeper or one of
   the 25 voice IDs (a clip-level identification by ear is the fastest route).
4. **[O]** The clock feeding the `0xC1218` timer, hence the actual beep frequency
   (`f = f_clk / 15000`).

## 7. Practical consequence for the modification

The pitch control point is the `0x3A98` immediate at 8 call sites. Patching
those to different divisors would give per-band pitch for the first time, and
each site is a 6-byte `mov.l #imm, r1` instruction. That is a far better target
than the voice bank — but which site belongs to which band must be established
first (open item 2), so no patch is proposed here.
