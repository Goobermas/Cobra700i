# The active radar record at the moment an alert is armed

Continues `787667a4`. No firmware was generated, modified or flashed.

## Answer up front

**There is no active record pointer and no slot index in the arm path.** The beeper
`0xFFFA606E` is called from 17 sites and every one of them loads the arm flag as an
*immediate* (`mov.l #0` or `mov.l #1`) — no caller passes a band, a record, or an index. The
alert identity travels in a separate message-queue post (`0xFFFA5024(id, flag)`), which the
sounder never reads.

So "identify the active record at the moment of arming" cannot be answered from the firmware
image: the answer is *there is no such link*. The beep is band-agnostic by construction, which
is exactly why the stock tone is a single 15000-period beep for every band.

Consequently the single-hook requirement cannot be met in the arm path, and the best remaining
candidate (one hook in the record-save copy) is shown by test to latch the *last saved* record
rather than the armed one. That is a negative result, and it is the honest one.

---

## 1. The array at `0x3BF88`

### Geometry

4 entries × 68 bytes = `0x3BF88..0x3C097`, proven by the two index computations
(`movu.b 11[r0], rN / mul #68, rN / mov.l #0x3bf88, rX / add rN, rX`).

### Every writer of dword 0

A scan that follows the base register and detects register-indexed addressing (`add rIdx, rBase`)
finds exactly four:

| site | instruction | meaning |
|---|---|---|
| `0xFFF7934E` | `mov.l [r14], [r2]` | **structure copy** — dword 0 of `0x397A8 + 68*src` into `0x3BF88 + 68*dst` |
| `0xFFF79599` | `mov.l #0, [r14]` | clear |
| `0xFFF7964C` | `mov.l #0, [r14]` | clear |
| `0xFFFA29AE` | `mov.l #0, [r14]` | clear (unindexed) |

There is **no** store of a band constant into the array anywhere. The only way a band gets in
is the copy from `0x397A8`.

### It is a history ring, not the active table

The copy routine clears a destination slot with `sstr.b` (`r2 = 0`, `r3 = 68` at
`0xFFF792E5`) and then advances a wrapping index:

```
fff792e9  mov.l 104[r0], r1
fff792eb  add   #1, r1
fff792ed  mov.l r1, 104[r0]
fff792ef  mov.l 104[r0], r1
fff792f1  cmp   #4, r1
fff792f3  blt.b fff792d5
fff792f5  mov.l #0, 104[r0]        ; wrap
```

so `0x3BF88` is a **4-deep ring of snapshots** appended from the working table at `0x397A8`.
Both arrays hold 68-byte records; `0x3BF88` is downstream.

### Field census (measured from both producers and consumers)

| offset | width | evidence |
|---|---|---|
| `+0` | dword | band/type code **plus flag bits**: the dispatch at `0xFFF867F0` compares it to `5, 16, 32, 48, 128`; `btst #6` is taken on it at `0xFFF79310` (none of those codes has bit 6 set) |
| `+4` | byte | **source kind, not band**: the laser builder writes `#4`; the sweep compares it against `+36` (`cmp 36[r2].ub, r1` at `0xFFF77758`) and logs it |
| `+20` | dword | logged and rendered: `mov.l 20[r15], 20[r14]`, `mov.l 20[r1], r1`, decimal digits built from it |
| `+25` | byte | logged by the sweep |
| `+28` | dword | `btst #6` at `0xFFF8671C` |
| `+32` | byte | `mov.b #1, 32[r1]` |
| `+36` | byte | decayed by ×4/5 each sweep (`shll #2` / `divu #5`) → strength |
| `+49`,`+50`,`+51` | byte | copied from `+24`,`+25`,`+26` |
| `+55`–`+58` | ASCII | decimal digits with `+59` = NUL |
| `+63`,`+64`,`+65` | byte | counters (`64[r1]` decremented per sweep) |

### Active vs historical

* `0x397A8` is the **working table**: producers write it directly (the laser builder writes slot 0
  with no index at all, `mov.l #0x397a8, r14`, then `mov.l [r15], [r14]`).
* `0x3BF88` is **historical**: only reachable through the ring copy, and the aging sweep at
  `0xFFF866B9` decays it.
* **Active slot selection** is a caller-context field: `11[r0]` (`0xFFF777B2`), plus the ring
  indices `100[r0]` / `104[r0]`. There is no fixed global index, so no fixed address reproduces
  "the active slot".

Not settled: whether the four slots are four *rotating detections* or four *fixed channels*. The
copy takes an explicit source index and destination index, which favours rotating history, but
the decisive test is two bands in sequence while watching whether a given slot's dword 0 changes.

---

## 2. Alert activation: what the 17 sites actually are

Every site has the identical shape:

```
mov.l #1, r2
mov.l #0x21, r1          ; message id (33 here)
bsr.a 0xFFFA5024         ; post message
rtsd  #12
mov.l #1, r1             ; <-- arm flag as an IMMEDIATE
bsr.a 0xFFFA606E         ; beep
```

`0xFFFA5024` is not audio: it translates the id via `0xFFFA4FCF`, then writes a 16-bit entry into
a 15-slot ring at `0x4C5D4` (index at `+2`, entry at `base + 2*idx + 8`, latest dword at `+4`).
The ids observed at the arm sites are `6, 11, 17, 24, 25, 32, 33, 37, 62, 66, 67, 81, 82, 116`.

**Per alert class:**

| class | path | band available at arm? |
|---|---|---|
| X, K, Ka, MRCD | each arm site is preceded by `mov.l #0/#1, r1` + `bsr.a`; the band never appears | **no** |
| laser | separate builder `0xFFF78F32` (see §5) | **no** — it does not even arm |
| menu / UI | `0xFFF93D9C(period)` beeper, 42 callers, never goes through `0xFFFA606E` | n/a |
| 0xFFF7BC3C / `0xFFF7BC44` | the only pair that arms twice in one function (flag 0 and flag 1) — start/stop | **no** |

`0xFFFA606E` itself is 23 bytes: `bset #5` of `0xAEB6` (arm) and a byte into `0x4C5D4+136`
(double-pulse flag). It cannot know a band.

---

## 3. One hook: the best candidate, and why it still fails the requirement

**The arm path offers no hook**, so the only single site that both sees a band and can host a
4-byte call is inside the ring copy:

```
fff79362  mov.l #0x397a8, r15
fff79368  add   r2, r15          ; r15 = source record
fff7936a  mov.l 20[r15], 20[r14] ; <-- SITE, 4 bytes (e5 fe 05 05)
fff7936e  mov.l 104[r0], r2      ; r2 dead from here
```

Design, 15 bytes at `0xFFFD1080`:

```
e5 fe 05 05        mov.l 20[r15], 20[r14]   ; displaced instruction, verbatim
ec f1              mov.l [r15], r1          ; band = source record dword 0
fb 22 33 b0 03 00  mov.l #0x3b033, r2
c3 21              mov.b r1, [r2]           ; latch
02                 rts
```

Site encoding: `bsr.a` = `05 12 7d 05` → `0xFFFD1080`.

**Requirement check**

| requirement | status |
|---|---|
| preserve displaced instruction | ✓ executed verbatim as the hook's first instruction |
| preserve live registers | ✓ writes only `r1` and `r2`; `r1` is next written at `0xFFF793F8` and `r2` at `0xFFF7936E`, so both are dead; `r0`, `r14`, `r15` untouched (asserted) |
| flags | ✓ no flag-writing instruction (MOV only) |
| stack | ✓ only `rts` uses it, and the `bsr`/`rts` pair balances |
| stock tone for unrelated alerts | ✓ the byte holds band codes only; every other value maps to 15000 |
| **capture the correct active band** | **✗ — it latches whichever record was copied last** |
| **switching between simultaneous detections** | **✗ last-write-wins; no per-band arbitration** |

Test E demonstrates the failure directly: feeding X then Ka leaves the latch at `0x30`, so the
alert that was *just armed* for X would beep as Ka.

The reason is structural: the copy is itself a **loop** (`0xFFF792E9` increments the destination
index and continues while `< 4`), so this site is a sweep exactly like the logging arms.

---

## 4. Validation

`tools/test_alert_path.py`, exit 0:

```
[A] 17 call sites of 0xFFFA606E; each preceded by mov.l #0/#1, r1; none derives r1 from the arrays
[B] single caller 0xFFF939EE, inside `for i<4 { 0x3BF88 + 68*i }`
[C] laser builder: field 4 = 4; dword 0 from 0x3B074; field 20 -> 55..58 ASCII;
    logs 0xFFF72B51; no tone() call in the block
[D] site holds e5fe0505; bsr.a 05 12 7d 05 -> 0xFFFD1080; hook 15 bytes;
    copy reproduced; latch = 0x10; r0/r14/r15 preserved; PSW untouched; rts last; no push/pop
[E] two-record sweep: latch ends 0x30 (last), not 0x10
```

Existing suites still pass: `test_latch.py`, `test_band_period.py`, `test_scenarios.py`.

### Statically demonstrated

* the 17 arm sites carry only an immediate flag — no record, no band, no index;
* `0x3BF88` receives dword 0 only via the ring copy and clears;
* the ring indices live in a caller context, so no fixed address is "the active slot";
* the laser builder writes field 4 = 4 and does not call `tone()`;
* the single-hook candidate is behaviour-preserving but latches the last copied record.

### Requires hardware breakpoints

1. **Which arm call site fires for a given band.** Break on `0xFFFA606E`, record `r1` and the
   return address; that identifies the caller (and therefore the alert class) for one X, one K,
   one Ka, one MRCD and one laser alert.
2. **Whether the record is live at that moment.** At the same breakpoint, read
   `0x397A8 + 68*11[ctx]` and `0x3BF88` slots; compare dword 0 with the band the detector reports.
3. **History vs per-channel table** — two bands in sequence, watch whether a slot's dword 0 changes.
4. **Ordering** of any future latch relative to the burst: break on `0xFFFB2BA1` too.
5. **Laser audio.** Break on `0xFFFB2BA1` during a laser alert; if it never hits, break on the
   other two tone wrappers (`0xFFF93D2B` triple burst, `0xFFF93D9C` UI beeper) and on
   `0xC1218`/`0xC121A` writes to see which routine loads them.

---

## 5. Laser audio: what is established, and what is not

The recording is real; the *routine* is now partly identified, but not its sound generator.

**Established**

* The only reference to the string `Laser Alert: %d ` (`0xFFF72B51`) is `0xFFF7904F`, inside the
  laser record builder `0xFFF78F32..0xFFF7906B`.
* That builder: copies dword 0 and field 20 from the laser event struct at `0x3B074`
  (`mov.l [r15], [r14]`, `mov.l 8[r15], 20[r14]`), sets `mov.b #4, 4[r14]` (source kind = laser),
  renders field 20 as 2–4 decimal ASCII digits into `+55..+58` (two branches, `cmp #999`),
  increments the ring index `104[r0]`, logs, and refreshes the display via `0xFFF87DD2`.
* It contains **no** call to `tone()` (`0xFFFB2BA1`) and therefore writes neither `0xC1218` nor
  `0xC121A` — tone() is the only writer of the period register.
* So the laser *alert record* and the laser *sound* are produced in different places. The sound
  must come from whatever consumes the record and branches on field 4 = 4.

**Not established (needs the breakpoints in §4.5)**

* which routine actually generates the recorded laser sound. Candidate families: the two other
  `tone()` wrappers (`0xFFF93D2B` triple burst, `0xFFF93D9C` UI beeper, 42 callers) or a
  non-PWM path (the image also drives a DSP — `dpushm.d`, `dmul`, `ftod`, `utof` appear in the
  radar signal code — but no laser-path DSP write has been located).
* whether the recording's distinctive pattern is a cadence (multiple armed bursts) rather than a
  different waveform. That is decidable from the recording plus a breakpoint count on
  `0xFFFB2BA1` during one laser alert.

---

## 6. Recommendation

Do not patch anything yet. The next action is a 20-minute bench session, not more static work:

1. break on `0xFFFA606E`, note the caller for one alert of each class;
2. break on `0xFFFB2BA1` during a laser alert — this alone resolves §5;
3. with those two lists, re-run this analysis over the *specific* callers instead of all 17.

If step 1 shows a per-class caller, the latch belongs in that caller's record write, and the
15-byte trampoline in `LATCH_TRAMPOLINE.md` §3 is the ready-made mechanism.
