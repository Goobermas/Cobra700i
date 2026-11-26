# RAD 700i — update process, validation and recovery risk

Scope: what the four vendor files in this repository do and do not prove about firmware
update validation. **Nothing was flashed. No firmware-writing command was issued.**

---

## 1. What the vendor file set actually is

| File | Size | Format | Identity |
|---|---|---|---|
| `RAD_700i_M1.2.4.0.mot` | 2,565,910 | Motorola **S-records** | main RX firmware, `FFT PlatformM1.2.4.0` |
| `RAD_700i_V1.2.0.1.bin` | 4,844,792 | custom container | voice bank `RAD_700i_V1.2.0.1` |
| `RAD_700i_G1.2.0.1.bin` | 4,054,500 | custom container | GUI/image bank `RAD_700i_G1.2.0.1` |
| `RAD_700i_B1.1.0.0.bin` | 89,112 | raw binary | **BLE module firmware — not the RAD MCU** |

### The `.mot` file

Standard S-record text: `S0` header `FFT     mot`, 53,463 `S3` data records, one `S7` start
record with entry `0xFFFA8708`. Every record carries the usual one-byte **S-record
checksum**, and `tools/srec_tool.py verify` re-encodes and reproduces all 53,465 lines
byte-exactly. That is a *transport integrity* field per line, trivially recomputable by
anyone — it is not authentication.

### The `.bin` containers

Both start with a 16-byte ASCII name, zeros to `0x20`, then a big-endian offset table
(309 entries in the voice bank), then `[u32 BE length][payload]` blocks. Integrity is
implicit: each length is stored **twice** (offset table and per block), and the previous
analysis found `length == span − 4` for 308 of 308 blocks, with block 307 truncated by 704
bytes in the voice file. There is **no trailer digest, no magic signature block, and no
version-trust field** — the container is self-consistent, not authenticated.

### The `B1` image is a different CPU entirely

```
first bytes: 00 80 00 20  →  initial SP 0x20008000
             79 9c 00 08  →  reset vector 0x08009C79  (Thumb, bit0 set)
             a9 49 00 08, af 49 00 08, ...  → vector table at 0x0800xxxx
strings:     "Wireless Firmware version %d.%d.%d"
             "FUS version %d.%d.%d"
             "Update_Service"
             "Cobra Electronics"
```

SP at `0x2000_0000` and code at `0x0800_0000` with Thumb bit set = an **ARM Cortex-M**
image. "FUS" + "Wireless Firmware" is the BLE module's firmware-update service. This is the
**Bluetooth radio's** firmware, reached over its own update channel — it is not the radar
MCU's bootloader and not part of the main image.

**Consequence: the repository contains no bootloader image.** Everything below about
bootloader validation is therefore *not* answered by the files we have.

---

## 2. How images get onto the device

The main image is shipped as **S-records**, which means a bootloader on the device parses
S-records and programs flash from them. The firmware contains the corresponding service
strings:

```
0xFFF73208  "DFU REMAIN :"
0xFFF73215  "DFU PROCESS RESTART"
0xFFF73229  "DFU PROCESS END"
0xFFF73239  "DFU     PROCESS     START"
0xFFF73253  "DFU     PROCESS     END"
0xFFF7377C  "USB CONNECTING"
0xFFF74C58  "FLASH   ERASING..."
0xFFF73A5E  "Main FW Download"
0xFFF73A6F  "BLE FW Download"
0xFFF73A7F  "GUI Download"
0xFFF73A8C  "Voice Download"
0xFFF73A9B  "GPS DB Download"
0xFFF737EC  "VERSION INFO"
```

**[C]** There are **five independent download targets** — main firmware, BLE, GUI, voice and
GPS database — offered separately. That matters for risk: a bad voice or GUI image is not
the same class of accident as a bad main image, and each has its own transfer path.

`DFU REMAIN :` implies a progress/remaining counter, and `DFU PROCESS RESTART` implies the
bootloader can be told to restart the transfer, i.e. the *update session* is restartable.
Whether that survives a **rejected or partially written main image** depends entirely on the
bootloader, which we do not have.

---

## 3. Validation — what can and cannot be shown

### Evidence found

* **[verified] No cryptographic digest string.** A byte search of the whole 1 MiB main image
  for `CRC` returns **0 hits**. A keyword survey of all printable strings for
  `checksum`/`signature`/`verify` found no validation routine name; every `Check*` string is
  radar signal processing (`[CheckIF]`, `[CheckLockBand]`, `[CheckPrevSignal]`, …).
* **[verified] The `.bin` containers carry no digest** (see §1) — only duplicated lengths.
* **[verified] The S-record layer's only check is the per-line checksum**, which our own tool
  reproduces exactly.
* **[verified] The main image has no signature block** at a fixed offset: it begins with the
  S0 record, and the `S7` entry is the last record.

### What that does *not* prove

Absence of a *string* is weak evidence. A bootloader can validate silently — comparing a
stored digest, or checking an image header version/length — without any printable text, and
the validating code would live in the bootloader, which is **not among our files**. Therefore:

* **[O] Whether a cryptographic signature is verified: unknown.** No evidence for one, no
  proof against one.
* **[O] Whether a CRC/checksum is verified at flash time: unknown.** The S-record checksums
  exist in the *file*, but nothing proves the bootloader checks them.
* **[O] Whether the bootloader independently validates modified firmware: unknown**, and
  this is the single most important unknown for recovery.

### The updater executable

The official installer (`Cobra_RAD_Series_Update_Installer`) is **not present in this
repository**, and no download was attempted during this analysis — so its USB transport,
its own pre-flight checks, and whether it transmits a signature are **not analysed here**
and are not guessed at. When the binary is available, the specific things to extract are:

1. the USB VID/PID and the endpoint/protocol it opens (HID report vs DFU class vs a custom
   vendor request);
2. whether it computes a hash of the payload before sending, and what it does with the
   device's response;
3. any `WriteFile`/`SET_REPORT` payload that is not a plain S-record line — that would be a
   signature or licence blob, and its presence would change the whole risk picture;
4. whether it can re-flash an already-updated unit (a "force"/"recovery" path is the only
   software route back from a bad main image).

---

## 4. Recovery risk

| Scenario | Confidence of software-only recovery | Why |
|---|---|---|
| Voice / GUI / GPS DB image rejected | **Plausible** | separate download target, not the boot code; the device still runs |
| BLE image bad | **Plausible** | separate `BLE FW Download` path; radio only |
| Main firmware image rejected **before erase** | **Likely recoverable** | `DFU PROCESS RESTART` exists; bootloader still running |
| Main firmware half-written / bootloader decides image is invalid | **Unknown** | depends on whether the bootloader keeps a valid fallback bank; no bootloader image to check |
| Bootloader itself erased | **Not recoverable in software** | no bootloader in any vendor file; would need hardware programming (E1/E2 or serial boot mode) |

Two facts that push the risk *down*: the main flash is 1 MiB and the image occupies 855,174
bytes, leaving real gaps, and the device exposes an on-board `FLASH ERASING...` /
`DFU PROCESS` flow rather than a blind write. Two that push it *up*: we cannot see the
bootloader, and the S-record path implies the bootloader rewrites flash in place.

**Recommendation, unchanged and firm:** do not write to the device until either (a) the
bootloader image or its protocol is obtained and its validation path is read, or (b) a
hardware recovery route is confirmed for this exact board. A tone patch is reversible *at
the file level* (three 4-byte instructions), but not necessarily at the device level.

---

## 5. Explicit non-actions

* No firmware image was built, patched or packaged.
* No USB command, DFU session, erase or write was issued to any device.
* The four vendor files are byte-identical to how they arrived; `git diff` shows no change.
