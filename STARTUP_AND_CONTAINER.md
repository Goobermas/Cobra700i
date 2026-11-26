# Startup audio and the vendor update container

Continues `4ce171fb`. Offline only: nothing flashed, no proprietary image published.

## 1. Priority 2 first — the container finding contradicts my earlier claim

I previously wrote that the vendor `.mot` lives in a different address space (`0xFE7F5D00`).
**That was wrong.** Parsing every S1/S2/S3 record (checksums verified record by record) gives:

| property | value |
|---|---|
| data bytes | 855,226 |
| lowest address | `0xFE7F5D00` |
| highest address | `0xFFFFFFFF` |

and the contiguous runs show exactly what the low block is:

```
0xFE7F5D00-0xFE7F5D0B  12   0xFE7F5D10-0xFE7F5D13   4
0xFE7F5D20-0xFE7F5D23   4   0xFE7F5D40-0xFE7F5D43   4
0xFE7F5D48-0xFE7F5D4B   4   0xFE7F5D50-0xFE7F5D5F  16
0xFE7F5D64-0xFE7F5D67   4   0xFE7F5D70-0xFE7F5D73   4
0xFFF00000-0xFFF00554 1365
0xFFF00556-0xFFF27555 159744
0xFFF27558-0xFFF7184E 303863
0xFFF71850-0xFFF718E2   147   (more runs follow)
```

So the `.mot` is: **eight tiny records of option/header bytes at `0xFE7F5D00`**, then the
executable image at **`0xFFF00000`**, the same space as the flat file we patch. The 1 MiB flat
image is 1,048,576 bytes while the file holds 855,226 — the difference is the erased gaps
(`0xFFF00555`, `0xFFF27556-7`, `0xFFF7184F`, …) that S-records legitimately omit.

**Consequence for the patch:** the five patched lines (`0xFFF93C40`, `0xFFF93CD0`, `0xFFF863F0`,
`0xFFF86400`, `0xFFF86430`) lie inside the code runs, so v0.1 **can be expressed in the vendor's
own format** by rewriting those records and leaving every other record untouched — the record
count and the option block stay byte-identical. What is still missing is not a format problem but
an installation-evidence problem (`INSTALL_EVIDENCE.md` items 1, 2, 4: updater framing, any
device-side check, block-erase/partial-write behaviour, recovery path).

## 2. Priority 1 — startup audio: what is established

**Established**

* The startup chirps are described by the owner as ~1 kHz. The PWM beep's stock period is 15000,
  and 15 MHz / 15000 = 1000.0 Hz — the same value the radar alerts use.
* They are therefore almost certainly produced by the **shared `tone()` routine** (`0xFFFB2BA1`),
  not by the sample channel: the sample channel (`0xC1228`) is fed from a buffer descriptor and
  can play any waveform, but the three-chirp pattern matches the burst driver's structure.
* Two wrappers can emit repeated bursts: `0xFFF93D2B` (triple burst, **5 callers**, one at
  `0xFFFA3F4D`) and `0xFFF93D9C(period)` (UI beeper, **42 callers**). The 5-caller one is the
  plausible startup candidate; the 42-caller one is the menu/UI beeper and would be the wrong
  target for a startup-only change.
* No startup-specific strings exist in the image (no "welcome", "booting", "power on"), so the
  startup sequence is not identified by a log string — it must be found through the call path.

**Not established (needs one boot-time breakpoint)**

1. Which wrapper the three chirps use. Break on `0xFFFB2BA1` during boot and read the return
   address: `0xFFF93D2B`-chain vs `0xFFF93D9C`-chain settles it in one boot.
2. Where the startup voice playback starts — the descriptor at `0x712F4` (see §3) is the only
   sample player, so the startup voice must go through it; the trigger is not yet located.
3. The trigger conditions (power-on only? also after settings reset / firmware update?).

## 3. Laser/sample descriptor

Measured today: the descriptor at `0x712F4` has exactly **two** writers of `+84` (the current
sample pointer) — `0xFFFB2EBD mov.l r2, 84[r1]` (advance by one sample) and `0xFFFB2ED4`
(reload) — and **no writer of `+80`** (the end pointer) inside a 16-instruction window of any
`#0x712F4` base load. So the end pointer is either written by a different addressing pattern
(e.g. computed base) or the descriptor is filled as a block.

That is the open item: whether a laser alert reaches this channel. The next step is mechanical —
scan stores through the *computed* descriptor base (as was needed for `0x3BF88`), then break on
`0xFFFB2EAC` during a laser alert and read `84[0x712F4]` to see which buffer is playing.

## 4. Two offline modification designs for startup audio

Both depend on §2.1; neither touches the shared radar-tone patch.

**Silent startup.** If the chirps come from the 5-caller burst wrapper, the minimal edit is at its
*startup call site* (e.g. `0xFFFA3F4D`), replacing the 4-byte `bsr.a` with a `bra` over the call —
startup audio disappears, radar/laser/GPS/menu paths are untouched because they use other
callers. The shared radar sites are not involved, so `SHARED_TONE_PATCH.md` stays as verified.

**Custom startup.** Same site, but the trampoline pattern already proven in
`LATCH_TRAMPOLINE.md` applies: displace the 4-byte call, reproduce it, and pass a different
period to `tone()` (or start the sample channel with a different buffer). A startup-only period
change needs no RAM and no band logic — it is the simplest possible use of that mechanism.

**Do not** silence startup by editing the 26 non-radar `fb1a983a` uses: that is exactly the
overlap the task warns about, and it would hit menu beeps.

## 5. Status

* v0.1 shared-tone patch: unchanged, still verified (`4ce171fb`).
* Container: corrected — same address space; patch representable; installation still blocked on
  updater evidence.
* Startup: identified as PWM-family with two candidate wrappers; one breakpoint decides.
* Laser: descriptor partially traced; trigger not found.
