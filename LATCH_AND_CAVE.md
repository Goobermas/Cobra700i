# Latch site, RAM safety, and the code cave — findings before any patching

Continues `BAND_AWARE_ENGINE.md` from commit `329650aa`. **No firmware image was built,
modified or flashed.** Two of the three questions are answered decisively; the first is
narrowed but not closed, and that is stated plainly rather than papered over.

Tools: `tools/funcs.py`, `tools/flash_map.py`, `tools/test_band_period.py`,
`tools/test_scenarios.py`.

---

## Priority 2 first — the proposed RAM location is unsafe, proven

`0x3AFC4+128` is **not** inside the alert-state struct. The globals in that neighbourhood,
taken from every `mov.l #addr, rN` in the image, are:

```
0x3ADB4  0x3ADC4  0x3AFC4  0x3B034  0x3B05C  0x3B074  0x3B218  0x3B2A0 ...
```

so the object at `0x3AFC4` is bounded above by **`0x3B034`**:

| object | range | size |
|---|---|---|
| `0x3ADC4` | ..`0x3AFC3` | <= 512 B |
| **`0x3AFC4`** | **`0x3AFC4..0x3B033`** | **112 B (0x70)** |
| `0x3B034` | `0x3B034..0x3B217` | 484 B |

`0x3AFC4 + 128 = 0x3B044`, which is **0x10 bytes into the object starting at `0x3B034`**.
Writing there would corrupt a live object — precisely the failure mode the review warned
about, and the "unknown band falls back to stock" argument does not protect against it: the
corruption happens on the *write*, not the read.

Access census on `0x3AFC4` (offsets touched by code):
`1 3 4 5 6 7 8 12 16 24 28 36 40 44 45 46 48 52 56 60 62 66 68 72 74 76 78 80 84 88 89 90
92 94 96 100 101 104 108 109 110`. Untouched **inside** the true bounds: `0,2,9-11,13-15,
17-23,25-27,29-35,37-39,41-43,47,49-51,53-55,57-59,61,63-65,67,69-71,73,75,77,79,81-83,
85-87,91,93,95,97-99,102,103,105-107,111`.

Two corrections to earlier statements:

* `78[0x3AFC4]` is **not** a band. It is a counter, written with the increment idiom
  `mov.w 78[r14], r15; add #1, r15; mov.w r15, 78[r14]` at `0xFFF93F08`, `0xFFF940A7`,
  `0xFFF94286` and elsewhere, and zeroed at twelve other sites.
* "unreferenced" was never evidence of allocation. It is now replaced by the neighbour
  argument above, which *is* evidence — and it rejects `+128`.

**Safe options, in order of preference:**

1. **No new RAM at all** — read an existing band cache (see Priority 1). Nothing is written.
2. A byte inside the true bounds that code never touches, e.g. `+111` (`0x3B033`, the last
   byte before `0x3B034`) or the small holes at `+17..+23` / `+29..+35`. These are inside
   the linker's allocation for this object, so they cannot alias another object; the
   residual risk is a field accessed through a computed pointer, which the absolute-offset
   census cannot see.

---

## Priority 1 — the latch site: narrowed, and the answer may be "no insertion needed"

### What is established

* The band code is `record+0` (dword), proven by the compare chain at `0xFFF867F2`–`0xFFF86809`.
* **38 sites** in **23 functions** load it with the exact idiom
  `mov.l 4[r0], r1` / `mov.l [r1], r14`. Full list reproducible with `tools/funcs.py`.
* The arming function `0xFFFA606E(uint8 double_beep)` has 17 callers and receives **no band
  information**, so it cannot be the latch point.
* No function that reads `28[0x3BF88]` also calls the arming function, so the band cache and
  the arm are always in different frames — i.e. any latch has to go through memory, not a
  register that survives the call chain.

### New finding: the firmware already caches band codes in globals

`0x3BF88` is read **45 times** as `[0x3BF88]` or `28[0x3BF88]` and immediately compared
against band codes, e.g.

```
fff84301  mov.l #0x3bf88, r14
          mov.l [r14], r14
          cmp   #16, r14        ; X
fff84326  ...                   cmp #32  ; K
fff84357  ...                   cmp #48  ; Ka
```

Neighbouring globals `0x3BE80, 0x3BF04, 0x3BF88, 0x3C098` bound that object to
`0x3BF88..0x3C097` (272 B), so both `+0` and `+28` are in bounds. Similar caches exist at
`0x3BD94+12` (compared to 48 and 16) and `0x3ADC4+279` (compared to 5).

If one of these holds the *live current band*, the design needs **no latch and no new
RAM**: the hook reads the cache, and staleness is whatever the firmware's own bookkeeping
is — it cannot be staler than the alert itself.

### What is still open, and the one measurement that closes it

Which of these is the live band, and whether it is current at the moment of arming, cannot
be settled statically from a single image: the same offset is used for band, for
configuration and for history in different functions. The decisive test is a single
breakpoint:

> break on the writer of `0x3BF88+0` (candidates: `0xFFF79599`, `0xFFF7964C`, both
> `mov.l #0, [r14]` after loading `0x3BF88`), then on `0xFFFA606E`, and compare the cached
> value against the detected band on one X and one K alert.

Until that is done, **the exact latch instruction is not identified** and this document does
not claim one. The three candidate shapes are: (a) read `0x3BF88+0` in the hook — zero code
inserted in the detection path; (b) latch at a `mov.l 4[r0], r1` site where the record is in
`r1`; (c) latch inside the display dispatcher at `0xFFF863D6`, where `60[r0]` gives the item.

### Expiry, band switch, overlap — with the design as it stands

| case | behaviour |
|---|---|
| expiry | engine disarms via `bclr #5,[0xAEB6]`; no tone; cache is not consulted until the next arm |
| band switch | the next alert's record is processed before it arms, so the cache is rewritten first |
| overlapping alerts | last record wins; the tone follows the most recently processed band, which is also what the display does |
| menu sounds | they call `0xFFF93D9C` with their **own** period and never read the band cache, so they cannot inherit a radar pitch — asserted in `tools/test_scenarios.py` S4 |

---

## Priority 3 — the cave is not usable as proposed

`tools/test_scenarios.py` S7 checks alignment against the two block sizes RX parts use:

```
hook 0xFFFD0C0B offset in a 2 KB erase block: 0x40B  (NOT aligned)
hook 0xFFFD0C0B offset in a 4 KB erase block: 0xC0B  (NOT aligned)
```

The last non-erased byte is `0xFFFD0C0A`, so `0xFFFD0C0B` sits **0x40B into a 2 KB block that
also contains live code**. Programming it means erasing a block that holds real instructions
and rewriting them from a dump — an unnecessary risk when the same run contains aligned
blocks that hold nothing: **`0xFFFD1000`** is 4 KB-aligned and 0xFF-filled, as is
`0xFFFF0000..0xFFFFFFCF` (below the reserved tail).

Other checks:

| question | status |
|---|---|
| erase-block boundaries | block size not documented for this part; both candidate sizes show `0xFFFD0C0B` unaligned, so the conclusion holds either way |
| reserved / option-setting memory | last 256 B excluded (`0xFFFFFF00..0xFFFFFFFF`); the reset vector at `0xFFFFFFFC` is `0xFFFA8708` |
| does the updater program this range? | **unknown** — the image is a full 1 MiB flat file, so a whole-image write would touch it with `0xFF` (no-op on erased flash), but the DFU path was never captured |
| integrity checks over it | **unknown** — no `CRC` string and no digest in the containers (from `UPDATER_ANALYSIS.md`), which is weak evidence of *no* check, not proof |
| execution supported | the address is in the same flash bank as the rest of the code, so it is executable in principle; MPU/region settings are not analysable from the image |

**Verdict: do not place the hook at `0xFFFD0C0B`.** Use an aligned erased block, and treat
even that as provisional until a second image confirms the tail is identical.

---

## Additional verification (requested)

| item | result |
|---|---|
| instruction encoding | `bsr.a` = `05` + 24-bit PC-relative displacement; `05c0cf03` for `0xFFF93C47` → `0xFFFD0C0B`; decoder pinned to firmware bytes in `test_band_period.py` |
| branch displacement | target re-computed from the encoding at all five sites and asserted to resolve to the hook (S6) |
| register preservation | the hook writes only `r1`; at every patched site `r1` was about to be loaded, so no live value changes (S5) |
| stack behaviour | no `push`/`pop`, no frame — the hook is leaf code with a single `rts` per path |
| return address | the patched sites gain a call, not a jump: the following `bsr.a 0xFFFB2BA1` still sees `r1` from the hook and returns normally |
| no address shift | 4-byte → 4-byte replacement, so every downstream address is unchanged |
| sites hold the expected bytes | all five verified as `fb1a983a` in the real image (S6) |
| menu / voice / GPS | menu beeper excluded from the plan (S4); clip channel `0xC1228`/`0xC1280` absent from all patched windows (S5) |

Scenario results (`python3 tools/test_scenarios.py`, exit 0):

```
S1 unknown band -> period 15000 (1000.0 Hz)          OK
S2 0x10 -> 12000 = 1250.0 Hz  0x20 -> 10000 = 1500.0  0x30 -> 7500 = 2000.0   OK
S3 X burst starts at 12000; Ka takes effect after the switch   OK
S4 menu beeper 0xFFF93DA2 not patched; hook returns 15000      OK
S5 clip channel untouched; hook clobbers only r1               OK
S6 5/5 sites verified fb1a983a -> bsr.a 0xFFFD0C0B (05c0cf03)  OK
S7 0xFFFD0C0B unaligned in both block sizes; use 0xFFFD1000    OK
```

---

## Unresolved risks

1. **Latch site not pinned.** The band cache hypothesis is strong but unverified; until a
   breakpoint confirms which global is live at arming time, no patch plan is complete.
2. **RAM placement.** A new byte would go at `+111` or inside a hole; residual risk is a
   computed-pointer access the census cannot see. Preferred: no new byte.
3. **Cave.** Must be an aligned erased block; still provisional on a second image.
4. **Updater/validation.** Unchanged: no bootloader image, no updater binary, recovery
   unproven.
5. **Part number.** Still unknown, so block size, MPU regions and the clock tree are inferred
   rather than read from a datasheet.

## Next action

One hardware session, two breakpoints: the writer of `0x3BF88+0`, and `0xFFFA606E`. That
converts Priority 1 from "narrowed" to "closed" and, if the cache is live, removes the RAM
question entirely.
