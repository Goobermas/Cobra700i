# KaLab v0.1 — shared-tone patch (offline prototype)

Status: **prototype only, nothing flashed.** Tool: `tools/patch_shared_tone.py`.
Install questions are deliberately *not* covered here — see `INSTALL_EVIDENCE.md`.

## 1. What v0.1 changes

Every radar alert reaches the PWM beep through five call sites that load the same 16-bit
period:

```
fb 1a 98 3a      mov.l #0x3a98, r1        ; 0x3a98 = 15000
```

| site | role |
|---|---|
| `0xFFF93C47` | sounder state machine, state 1 → single beep |
| `0xFFF93CD9` | sounder state machine, state 4 → beep variant |
| `0xFFF863F9` | triple-burst driver, burst 1 |
| `0xFFF8640C` | triple-burst driver, burst 2 |
| `0xFFF86430` | triple-burst driver, burst 3 |

`tone()` computes the PWM period as `period-1` and the duty as `(period-1)>>1`, so **duty stays
50 % at any period**: changing the immediate changes pitch and leaves the effective volume
alone. The audible frequency is `15 MHz / period` (timer clock measured from the owner's
recording: 999.98 Hz at period 15000).

v0.1 therefore patches **only the 2-byte immediate at each of the five sites**. No code cave,
no RAM variable, no trampoline, no added instructions.

## 2. Why five immediates are sufficient

| behaviour | where it lives | touched? |
|---|---|---|
| cadence (50 / 30 / 80 ms) | `84[0x3AFC4]` counters compared against 50 and 30, plus the 30 ms external re-arm | no |
| signal-strength decay | `36[r1]` scaled by ×4/5 per sweep | no |
| volume | derived as `period>>1` inside `tone()` | no — duty stays 50 % |
| band decision | the same five sites, band-agnostic | no |
| voice / sample announcements | separate streamed channel at `0xC1228` (see §5) | no |
| menu / UI beeps | 26 other `fb1a983a` uses in the image, untouched | no |

The last row is measured, not assumed: the image contains **31** copies of `fb1a983a`; v0.1
rewrites exactly 5 and leaves 26 at 15000, so unrelated sounds keep their pitch by construction.

## 3. Tool contract

```
patch_shared_tone.py apply  --period 12000 -o out/v0_1/img.bin --srec out/v0_1/patch.s3
patch_shared_tone.py verify --patch out/v0_1/img.bin
patch_shared_tone.py revert --patch out/v0_1/img.bin -o out/v0_1/reverted.bin
```

Guarantees enforced by the tool, each aborting on failure:

1. **original-byte verification** — all five sites must hold `fb1a983a` before anything is written;
2. **reversibility** — only bytes 2–3 of each instruction are written, so revert is the inverse
   operation and is proven byte-identical by SHA-256;
3. **byte-difference report** — the changed set must equal exactly
   `{site+2, site+3}` for the five sites (10 bytes), verified against the input image, plus a
   JSON manifest with both hashes;
4. **S-record output** — one S3 record per touched 16-byte line, S0 header and S5 count, each
   checksum recomputed and re-verified after writing;
5. **static verification** — size unchanged, every site still decodes as `fb1a`, all five periods
   equal and within `[64, 65535]`, stock-instruction count dropped by exactly 5;
6. **range guard** — periods outside `[64, 65535]` are refused (tone() needs period > 2).

## 4. Recorded result (period 12000 = 1250 Hz)

```
stock 15000 -> 1000.0 Hz, new 12000 -> 1250.0 Hz
0xFFF93C47  fb1a983a -> fb1ae02e
0xFFF93CD9  fb1a983a -> fb1ae02e
0xFFF863F9  fb1a983a -> fb1ae02e
0xFFF8640C  fb1a983a -> fb1ae02e
0xFFF86430  fb1a983a -> fb1ae02e
bytes changed: 10 (expected 10)
out/v0_1/img.bin  sha256 428ed89eb21296fd38f8cbbd201b7dc0926d821cbe7b52151d3e42718c2a41ef
out/v0_1/patch.s3  (5 data records, checksums verified)
revert -> sha256 13545b5838bab5aa44b7a3acbdb4cab93ea299160b97a4c7362613c3e0fc5789  identical: True
```

Generated images live under `out/` (git-ignored) and are never committed.

## 5. Priority 2 — the other audio channel (`0xC1228`)

**The laser/voice channel is streamed 16-bit samples, not PWM.** Evidence:

* `0xC1228` has exactly **one** writer in the whole image, at `0xFFFB2EAC`:

```
fffb2ea4  mov.l #0x712f4, r1
fffb2eaa  mov.l 84[r1], r1        ; current sample pointer
fffb2eac  mov.l #0xc1228, r14
fffb2eb1  mov.w [r1], [r14]       ; <-- 16-bit SAMPLE to the output register
fffb2eb3  mov.l #0x712f4, r1
fffb2eb9  mov.l 84[r1], r2
fffb2ebb  add   #2, r2
fffb2ebd  mov.l r2, 84[r1]        ; advance by one sample
fffb2ebf  mov.l #0x712f4, r14
fffb2ec5  add   #80, r14, r15
fffb2ec8  cmp   84[r14].l, r15    ; compare against +80 (end pointer)
fffb2ecc  bgtu.b fffb2ed6         ; buffer exhausted -> reload/stop
```

* The buffer descriptor at `0x712F4` holds `+80` = end pointer and `+84` = current pointer; the
  routine walks it two bytes at a time and handles exhaustion by setting a state byte
  (`mov.b #2, 3[r0]`) or bumping a counter at `0x71364`.
* The peripheral is configured nearby (`0xC1300` block: `mov.b #40`, `40[r14]=2`, `4[r1]=0`;
  `0xC1280` bit 0 cleared as enable/disable), and the block ends with `rte`/`popm` — it is an
  interrupt handler, i.e. an ISR-driven sample player.
* By contrast `0xC1218` (PWM period) has only four writers, all inside `tone()`, and the laser
  record builder `0xFFF78F32` contains no `tone()` call and no `0xC1218` write.

**Conclusion:** laser (and voice) audio is a separate sample-streaming subsystem fed through the
descriptor at `0x712F4`, and its absence from the record builder means only that the builder is
not the player. This confirms the warning that "no `tone()` call" does not imply "no dedicated
sound" — there is a dedicated channel.

**Not yet traced** (the honest gap): the path from a laser detection to starting that stream.
The next step is mechanical — list writers of `80[0x712F4]` and `84[0x712F4]` (the descriptor is
populated per sound), then xref the caller that fills it during a laser alert. A breakpoint on
`0xFFFB2EAC` during a laser alert would confirm within one alert which buffer is playing.

## 6. Limits of v0.1

* Pitch only: all radar alerts move together. Per-band pitch still needs an active-band source,
  which `ALERT_PATH.md` shows the arm path does not provide.
* The timer clock (15 MHz) is a measurement, not a register decode we could fully confirm; if it
  were 30 MHz every number doubles and 1250 Hz would actually be 2500 Hz. The *ratio* between
  stock and patched is correct regardless.
* The prototype targets the flat image at base `0xFFF00000`. The vendor `.mot` uses a different
  address space (`0xFE7F5D00`), so this output is **not** a file the updater can consume as-is;
  see `INSTALL_EVIDENCE.md`.
