# Band latch trampoline: design, byte-level verification, and why its placement is wrong

Continues `2bec70fb`. No firmware image was built, modified or flashed.

## 0. Summary

* The replacement of `mov.l 20[r1], 4[r0]` by a 4-byte `bsr.a` is **mechanically sound**: a
  15-byte trampoline reproduces the displaced store, latches the band, and is proven to leave
  every register, PSW, SP and every byte of memory identical except the latch byte and the
  call's own 4-byte stack slot.
* The displaced instruction decodes exactly as stated (4 bytes, `e5 10 05 01`), `r1` is the
  record, and `record+0` is the raw band code — all three now proven, not assumed.
* **But the four sites must not be used.** They sit inside a routine whose only caller sweeps
  *all four* slots of the `0x3BF88` array (`for i = 0..3`). A latch written there ends up
  holding the band of the **last slot processed**, not of the alert being sounded.
* Two earlier claims in `BAND_SOURCE_VERDICT.md` are **wrong** and are corrected here:
  `0x3BF88` *is* written (through computed pointers), and the `0x3AFC4` object was bounded by
  the wrong neighbour.

---

## 1. The full basic block at each site

The record-aging routine starts at `0xFFF866B9`:

```
fff866b9  sub   #8, r0            ; frame: [r0] = temp, 4[r0] = arg (record pointer)
fff866bb  mov.l r1, 4[r0]         ; save the record argument
fff866bd  mov.l [r1], r14         ; r14 = record dword 0 = BAND CODE
fff866bf  cmp   #0, r14
fff866c1  beq.b fff866e1
...
fff867e7  mov.l [r0], r1          ; temp flag
fff867e9  cmp   #0, r1
fff867eb  beq.w fff868cd          ; early out
fff867ee  mov.l 4[r0], r1         ; r1 = record   <- reloaded before every arm
fff867f0  mov.l [r1], r14         ; r14 = band
fff867f2  cmp   #5, r14
fff867f4  beq.b fff86867          ; arm shared by 0x05 and 0x30
fff867f6  cmp   #128, r14
fff867f9  beq.w fff86894          ; MRCD
fff867fc  cmp   #32, r14
fff867ff  beq.b fff8683a          ; K
fff86801  cmp   #48, r14
fff86804  beq.b fff86867          ; Ka
fff86806  cmp   #16, r14
fff86809  bne.w fff868bf          ; unknown band: no log, no arm
```

All four arms have the same shape; the X arm (`0xFFF8680C`) in full:

```
fff8680c  mov.l 4[r0], r1         ; r1 = record
fff8680e  movu.b 64[r1], r2       ; record+64
fff86811  movu.b 4[r1], r3        ; record+4
fff86813  movu.b 25[r1], r4       ; record+25
fff86815  add   #-20, r0, r0      ; SP -= 20  (outgoing argument block)
fff86818  mov.l r2, 16[r0]
fff8681a  mov.l r3, 12[r0]
fff8681c  mov.l r4,  8[r0]
fff8681e  mov.l 20[r1], 4[r0]     ; <-- SITE: arg1 = record+20
fff86822  mov.l #0xfff7395c, r14  ; format string
fff86828  mov.l r14, [r0]         ; arg0
fff8682a  mov.l #0x16b09, r1      ; log id
fff86830  bsr.a fffc6e00          ; log_printf
fff86834  add   #20, r0, r0
fff86837  bra.w fff868bf
```

| arm | site | following `mov.l #fmt, r14` | log call |
|---|---|---|---|
| X (0x10) | `0xFFF8681E` | `0xFFF86822` → `0xFFF7395C` | `0xFFF86830` |
| K (0x20) | `0xFFF8684C` | `0xFFF86850` → `0xFFF7398C` | `0xFFF8685E` |
| Ka (0x30/0x05) | `0xFFF86879` | `0xFFF8687D` → `0xFFF739BC` | `0xFFF8688B` |
| MRCD (0x80) | `0xFFF868A6` | `0xFFF868AA` → `0xFFF739EC` | `0xFFF868B8` |

All four sites hold `e5 10 05 01` (verified from the image, not from the listing).

---

## 2. Register and flag liveness

At every site: `r0` = SP (already decremented by 20; the arg block `[r0 .. r0+16]` is being
filled), `r1` = record, `r14` = band code, `r15` = SP.

| register | state across the site | evidence |
|---|---|---|
| `r0` | **live** (arg block base, used by `mov.l r14, [r0]` and by the call) | must not be written |
| `r15` | live, must not change | — |
| `r1` | **written at `+12` before any read** | `mov.l #0x16b09, r1` at `0xFFF8682A` (K: `0xFFF86858`, Ka: `0xFFF86885`, MRCD: `0xFFF868B2`) |
| `r14` | **written at `+4` before any read** | `mov.l #0xfff7395c, r14` at `0xFFF86822` (K/Ka/MRCD: `0xFFF86850`/`7D`/`AA`) |
| `r2`,`r3`,`r4` | dead: stored into the arg block at `+8..+16`, never re-read in the window; also caller-saved at the `log_printf` call | checked instruction by instruction |
| `r5`..`r13` | untouched by the design (callee-saved, and never named) | — |

**Flags.** The compare chain before the arm sets PSW, and the next flag consumer is *after*
the log call, so flags are dead across the site too. The trampoline does not rely on that: it
contains no flag-writing instruction (RX `MOV`, `BSR`, `RTS` leave PSW alone), so PSW is
preserved unconditionally. The tests seed a non-trivial PSW (`C=1,Z=0,S=1,O=1,I=0`) and assert
it survives.

`tools/test_latch.py` re-derives the table above from the disassembly, so a wrong claim fails
the suite rather than surviving in prose.

---

## 3. The trampoline

One shared 15-byte routine at `0xFFFD1040` (the period hook occupies
`0xFFFD1000..0xFFFD1038`; both live inside the erased run `0xFFFD0C0B..0xFFFFFFCF`).

```
hook  0xFFFD1040  e5 10 05 01        mov.l 20[r1], 4[r0]     ; displaced instruction, verbatim
                  ec 1e              mov.l [r1], r14         ; band = record dword 0
                  fb 12 33 b0 03 00  mov.l #0x3b033, r1       ; latch address
                  c3 1e              mov.b r14, [r1]         ; latch
                  02                 rts
```

Bytes: `e5 10 05 01 ec 1e fb 12 33 b0 03 00 c3 1e 02`
(`0xFFFD1040`–`0xFFFD104E`).

Every encoding is attested elsewhere in the image:

| form | attested instance |
|---|---|
| `e5 q s d` = `mov.l s*4[Rs], d*4[Rd]` | `e5 11 0a 02` = `mov.l 40[r1], 8[r1]` at `0xFFF8667A`; `e5 fe 05 05` = `mov.l 20[r15], 20[r14]` at `0xFFF7936A` |
| `ec q` = `mov.l [Rs], Rd` | `ec 1e` at `0xFFF867F0` |
| `fb 12 imm32` = `mov.l #imm32, r1` | `fb 12 09 6b 01 00` at `0xFFF8682A` |
| `c3 q` = `mov.b Rs, [Rd]`, `q = Rd<<4 \| Rs` | `c3 0e` = `mov.b r14, [r0]`, `c3 13` = `mov.b r3, [r1]` |
| `02` = `rts` | `0xFFF93C46` |

The `.L` displacement scaling (×4) is confirmed by the same family: `e5 11 0a 02` decodes to
40 and 8 only under `byte × 4`, and `c5 11 04 24` (`mov.b 4[r1], 36[r1]`) uses unscaled bytes
for `.B`.

### Site encodings (`bsr.a` = `05 disp24`, little-endian, relative to `site+4`)

| arm | site | bytes | resolves to |
|---|---|---|---|
| X | `0xFFF8681E` | `05 1e a8 04` | `0xFFFD1040` |
| K | `0xFFF8684C` | `05 f0 a7 04` | `0xFFFD1040` |
| Ka | `0xFFF86879` | `05 c3 a7 04` | `0xFFFD1040` |
| MRCD | `0xFFF868A6` | `05 96 a7 04` | `0xFFFD1040` |

No displacement is 0 and none crosses a 24-bit boundary; each is re-decoded back to the target
by the test rather than trusted.

---

## 4. `r1` is the record, and `record+0` is the band

1. **`4[r0]` is the saved argument.** The routine's prologue is `sub #8, r0` / `mov.l r1, 4[r0]`
   at `0xFFF866B9`, i.e. `r0` is SP and `4[r0]` holds the incoming `r1`.
2. **The caller passes a record pointer.** Its only caller is
   `0xFFF939EE  bsr.a 0xFFF866B9`, reached from
   `0xFFF939E1  mov.l [r0], r2 / mul #68, r2 / mov.l #0x3bf88, r1 / add r2, r1`
   — i.e. `r1 = 0x3BF88 + 68*i`, a record pointer into the array.
3. **Dword 0 is the band code.** The dispatch at `0xFFF867F0` compares `[r1]` against
   `5, 16, 32, 48, 128` — the codes proven earlier from the per-branch log strings — and the
   array copy at `0xFFF7934E` moves dword 0 wholesale (`mov.l [r14], [r2]`).

So both the site's `r1` and the band offset are established by two independent routes.

---

## 5. Indirect writes, bulk initialisation and aliases — correction

**My earlier "83 reads, 0 writes, therefore not a live value" conclusion was wrong.** The
array *is* written, through computed pointers, which a literal-lookup scan cannot see:

```
fff777b2  movu.b 11[r0], r14      ; slot index from a caller-supplied context
fff777b5  mul    #68, r14
fff777b8  mov.l  #0x3bf88, r1
fff777be  add    r14, r1          ; r1 = 0x3BF88 + 68*slot
fff777c0  movu.b 36[r1], r14
fff777cb  mov.b  r14, 4[r1]       ; write through the computed pointer
```

and the wholesale field copy:

```
fff7932d  mov.l 104[r0], r1   / mul #68 / add to 0x3BF88      ; destination slot
fff79341  mov.l 100[r0], r1   / mul #68 / add to 0x397A8      ; source slot
fff7934e  mov.l [r14], [r2]                                   ; dword 0 copied (band included)
```

`0x3BF88` is therefore a **4-entry × 68-byte array** (`0x3BF88..0x3C097`), indexed by a
context field (`11[r0]`), fed from a parallel array at `0x397A8`. Two readings remain, and
neither is proven:

* **(a) detection history** — the four most recent detections, rotated on each save;
* **(b) per-channel table** — four fixed channels, each holding its own band.

The decisive experiment is two detections of different bands while watching whether a slot's
dword 0 changes (history) or stays fixed (channel table). This turn does not settle it.

What *is* settled: there is no single global holding "the current band". The only pointer to
the active slot is `11[r0]` of a caller context, so a fixed-address read cannot reproduce it.

---

## 6. Is the RAM byte safe?

The latch uses `0x3B033`, the **last byte of the object at `0x3AFC4`**.

The earlier justification ("the next global is `0x3B034`, so the object is 112 bytes") was
right by luck and wrong in method: `0x3B034` is an *inner* structure addressed by its own
literal. The measured argument is:

| check | result |
|---|---|
| accesses reachable from a `mov.l #0x3AFC4` base, following the register and its static offsets until it is overwritten | 169 accesses, **max offset 110** |
| wide fields near the top | `mov.l` at 96 (96–99) and 104 (104–107); everything at 100, 101, 108, 109, **110 is a single byte** |
| direct references to `0x3B033` (and `0x3B030`–`0x3B032`) | **0** |
| negative displacements anywhere in the image | **0**, so an access based on `0x3B034` cannot reach down |
| computed index into the object | **0** unresolved-index accesses; the only chain-breaking arithmetic (`add #-4, r1, r14` at `0xFFF90B35`) produces no memory operand in the tracked window |
| `0x3B034` object's own extent | offsets 0,4,8,12,20,32,36 — its low bound is `0x3B034` |

So byte 111 is genuine padding inside a 112-byte object, written by nothing.

Residual risks, not resolved:

* A bulk clear/memset of the object would zero our byte → the tone falls back to 15000. Harmless.
* A bulk *copy in* (settings restore) could place an arbitrary byte there. Only
  `0x10/0x20/0x30/0x05/0x80` change behaviour; any other value falls back to 15000. Harmless
  unless a copied value coincides.
* If a checksum covers the struct's padding bytes, writing a band code could invalidate it.
  Unproven; the object looks like runtime state, but "looks like" is not evidence.

---

## 7. Does the latch run before the sounder? — and why it does not matter

Statically the answer is **no ordering exists to prove**, and now for a more fundamental
reason than scheduling:

```
0xFFF939DC  mov.l #0, [r0]              ; i = 0
0xFFF939E1  mov.l [r0], r2
0xFFF939E3  mul   #68, r2
0xFFF939E6  mov.l #0x3bf88, r1
0xFFF939EC  add   r2, r1
0xFFF939EE  bsr.a fff866b9              ; <-- the routine holding all four sites
0xFFF939F4  add   #1, r1
0xFFF939F8  mov.l [r0], r1
0xFFF939FA  cmp   #4, r1
0xFFF939FC  blt.b fff939e1              ; loop while i < 4
```

The routine is invoked **four times per sweep**, once per slot, so a latch written at any of the
four band arms ends up holding the band of **slot 3** no matter which alert is sounding. It also
only runs when that aging sweep runs, which is unrelated to the alert.

The sounder is a separate function with a separate caller (`0xFFF94AEA → 0xFFF93BCF`), and it is
a leaf that clobbers `r1` in its first instruction:

```
fff93bcf  mov.l #0x3c188, r1
fff93bd5  movu.b 22[r1], r1
```

so it never receives a record and cannot read the band from any argument.

**Conclusion: the trampoline is correct, the placement is wrong.** Delivering this as the latch
would produce a band-aware tone that reports the wrong band — the exact failure mode the whole
exercise is meant to avoid.

---

## 8. Return address and other implicit RX call state

| concern | finding |
|---|---|
| link register | **none.** RX has no LR/PR; `bsr` pushes the 4-byte return PC onto the stack and `rts` pops it. There is nothing for the trampoline to save or restore beyond SP balance. |
| stack pointer | the hook's single `bsr` push and `rts` pop cancel exactly; `r15` is bit-identical afterwards (asserted). |
| stack alignment | the RX ABI keeps SP 4-byte aligned at call boundaries; 4-byte push/pop preserves that. |
| collision with the outgoing argument block | **checked, and it does not collide.** At the site `r0` *is* SP and has already been decremented by 20, so the argument block is `[SP .. SP+16]` and the `bsr` push lands at `SP-4` — below it. (Had `r0` still been the old SP, the push would have overwritten arg4 at `r0+16`; that is precisely the trap this check rules out.) |
| status flags | untouched; the hook has no flag-writing instruction, and PSW is asserted unchanged with a seeded pattern. |
| delayed-branch/implicit PSW bits | none used; no `rte`, no DSP/USB state. |
| `rtsd` in the enclosing function | unaffected: the epilogue is at `0xFFF868CB`/`0xFFF868CD`, after the block, and the hook returns with the same SP. |

---

## 9. Tests

`tools/rxmini.py` — a minimal interpreter decoding only the attested forms
(`e5/e4/e1/e3/ec/c3/c5`, `fb 12`, `fb e2`, `05`, `02`, `67 nn`), big-endian, sparse memory.

`tools/test_latch.py` — exit 0:

```
[bytes]      all 4 sites hold e5100501, followed by the exact 12-byte block from the image
[encoding]   15-byte hook; store reproduced; latch = band; SP restored; rts to pushed PC;
             no compare instruction
[liveness]   r1/r14 first use is a write; r2/r3/r4 never referenced in the window  (4 arms)
[layout]     all four bsr.a encodings decode back to 0xFFFD1040
[equivalence]original vs patched, both run from the site to the log call:
             all 16 registers identical, PSW identical, SP identical,
             4[r0] == record+20 in both,
             diff set == {0x3B033} U {SP-4..SP-1},
             latch == band for 0x10 / 0x20 / 0x30 / 0x80
[mutation]   dropping the displaced store -> detected
             dropping the latch         -> detected
```

The diff set is the whole proof: **the only memory differences anywhere in the address space
are the latch byte and the four bytes below SP that any call would write.** Registers, flags,
SP and control flow are identical at the call boundary.

`tools/test_band_period.py` and `tools/test_scenarios.py` still pass (exit 0) — the period hook
and its five sites are unchanged.

The interpreter is a model, not silicon: it validates the encoding and the data flow, not RX
pipeline/timing behaviour, and it does not execute `divu`, `bitmov`, or the DSP instructions.

---

## 10. What remains unproven

1. **Which slot is current** — history vs per-channel table; needs the two-band experiment.
2. **A per-alert band source** — no site both knows the band and precedes the arm; the link from
   detection to `0xFFFA606E` (17 callers, no band argument) is still missing. Until it is found,
   no latch placement can be justified.
3. **Ordering at runtime** — even for a correct site, only a breakpoint on `0xFFFA606E` plus the
   latch can confirm it, because the call graphs are disjoint.
4. **Checksum coverage of the object's padding** — unproven.
5. **Executability of `0xFFFD1040`** — same bank as the code, but MPU configuration is not
   analysable from the image.

## 11. Recommendation

Keep the trampoline as the reference implementation of the *mechanism* (it is proven), but
**do not patch the four sites**. The next step is not code: it is finding where a detection
becomes an alert — breakpoint `0xFFFA606E`, record `r0`'s call chain, and read `0x3BF88+68*11[ctx]`
there. If that link turns out to pass the record pointer, the same 15-byte trampoline can be
reused at one site instead of four, with the same byte-level proof.
