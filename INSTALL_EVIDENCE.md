# Installation evidence — what must be true before a modified image can be installed

Separate from the offline patch prototype (`SHARED_TONE_PATCH.md`, `tools/patch_shared_tone.py`).
Extends `UPDATER_ANALYSIS.md` with one new measured fact. Nothing here is a flash procedure.

## 1. New measured fact: the container is not a dump of the analysed flash

The analysed image is a flat 1 MiB blob at base `0xFFF00000` (sha256 `13545b58…c5789`).
The vendor S-record file on disk starts differently:

```
S00E000046465420202020206D6F7421        ; header "DFB      mot!"
S311FE7F5D008FFFFFFFFFFFFFFFFFFFFFFF90  ; data at 0xFE7F5D00
S309FE7F5D10FFFFFFFF10
```

Data addresses begin at **`0xFE7F5D00`**, not `0xFFF00000`. So the `.mot` is not a
straight transcript of the flash we reverse-engineered: the updater's address space differs
from the CPU's runtime address space (an offset/relocation, or a different device in the file
set — `UPDATER_ANALYSIS.md` §1 notes the `B1` image is a different CPU entirely).

**Consequence:** a patched flat image cannot be handed to the updater as-is, even if every byte
is correct. Whoever builds a release must establish the mapping between flat `0xFFF00000` and
updater `0xFE7F5D00` first.

## 2. What is already established

From `UPDATER_ANALYSIS.md` (unchanged this turn):

* the vendor file set is four containers plus one `.mot`; the `B1` file is a different CPU;
* the updater **executable is not in the repository**, so its protocol, framing and validation
  cannot be read from anything we hold;
* no digest, signature or `CRC` string was found in the main image, which is weak evidence of
  *no on-user-image check*, not proof;
* the bootloader/DFU path was never captured.

## 3. Evidence needed (each item closes one specific risk)

| # | risk | evidence required |
|---|---|---|
| 1 | image refuses to install | the PC updater binary; extract its framing (USB/HID or serial), the command sequence, and any pre-transfer handshake |
| 2 | image installs but is rejected | any checksum/signature computed by the updater **or** by the device before committing; where the expected value comes from (header, server, none) |
| 3 | address space mismatch (§1) | the flat↔`.mot` mapping: compare a known-identical region byte-for-byte and derive the offset; or capture a transfer and diff it against the vendor `.mot` |
| 4 | partial write bricks the device | whether the updater erases-then-writes whole blocks and whether the device can re-enter update mode when the application does not run (bootloader in a protected region / B1) |
| 5 | recovery | a vendor-documented recovery (e.g. holding a key sequence to enter DFU) plus a verified success by someone who has done it |
| 6 | which file is the analysed CPU | identify which of the four containers corresponds to the flat image (hash the extracted segments), so a release targets the right file |

Until items 1, 2 and 4 are answered, **no statement about safe installation is possible** — not
"it will work", and not "it will brick". Both would be guesses.

## 4. What would make a minimal patch attractive

If item 2 shows no image-level validation, a 10-byte change confined to two bytes per
instruction is the smallest possible modification surface: no new code, no relocation, no size
change, nothing outside the five radar call sites. That is the best case for a first hardware
test — but it is still a hardware test with a non-zero recovery risk, and the decision belongs
to the device owner, with item 5 (recovery) resolved first.
