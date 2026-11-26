# RAD 700i firmware analysis — progress notes

Static/offline analysis only. **No firmware was flashed. Original firmware files
are never written to**; all output goes to `work/` (intermediate) and `out/`
(deliverables).

Full narrative report: the "Cobra RAD 700i — Firmware Reverse-Engineering Report"
document (saved alongside this chat).

## Environment setup (reproducible)

No RX-capable disassembler ships with the image, so binutils is built from source:

```bash
cd tools
curl -fsSL -o binutils.tar.xz https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz
tar xf binutils.tar.xz && cd binutils-2.42
./configure --target=rx-elf --disable-nls --disable-werror --disable-gdb \
            --disable-gprofng --disable-sim --disable-ld --disable-gas
make -j2 all-binutils
```

`objdump -b binary -m rx` is **not** supported (the binary target cannot select
the RX machine), so the flat image is wrapped in an ELF first:

```bash
B=tools/binutils-2.42/binutils
$B/objcopy -I binary -O elf32-rx-le -B rx --change-addresses=0xFFF00000 \
           work/main_flat_fff00000.bin work/main.elf
$B/objdump -D -j .data work/main.elf > work/main_full.dis
```

`numpy` is needed only for the spectral analysis (`pip install numpy`).

## Analysis order

| Step | Script | Output |
|---|---|---|
| 1 | `tools/srec_analyze.py` | validates all 53,465 records, flattens to `work/main_flat_fff00000.bin`, dumps the fixed vector table, `work/srec_report.json` |
| 2 | `tools/srec_tool.py verify` / `info` | proves the S-record layer is byte-exactly reproducible; segment map in `out/srec_info.json` |
| 3 | `tools/rx_analyze.py` | I/O-space usage histogram, per-function peripheral fingerprints (`work/io_histogram.txt`, `work/functions.txt`) |
| 4 | `tools/vectors.py` | decodes the relocated vector table at `0xFFF57750`; 36 handlers |
| 5 | `tools/voicebank.py` / `voice_decode.py` | parses the 308-block voice container, decodes ADPCM to `work/voice/voice.pcm` |
| 6 | `tools/voice_spectral.py` | tone-vs-speech classification, `work/voice/features.csv` |
| 7 | `tools/tonegen.py` | designed X/K/Ka/LASER tones + cadence previews in `out/tones/` |
| 8 | `tools/patch_voice.py <band>` | size-preserving patched voice image + manifest in `out/` |
| 9 | `tools/verify_patch.py` | end-to-end verification (codec round-trip + patch integrity), exit 0 = pass |

## Findings that changed the plan

- The reset routine executes `mvtc r14,intb` with `INTB = 0xFFF57750`, so the
  256-entry interrupt vector table is **relocated**, not at the default address.
  All handler discovery must start there.
- `0xFFF00000` is not code — it is an ASCII glyph table. Code starts near
  `0xFFF00556`.
- The image is littered with unsripped debug trace strings ("FFT Platform
  M1.2.4.0"). Those strings are the fastest route to any subsystem: find the
  string, find the `mov.l #<addr>` that loads it, and you are inside the routine.
- `DAC` in the logs always means the **DRO (oscillator) tuning DAC**
  (`[DRO]Passed DRO(%5.1f)Khz DAC(%d)`), never audio. Do not follow DAC
  references expecting a speaker.
- The 89-entry IMA ADPCM step table is **absent** from the main image, so the RX
  cannot decode the voice bank. That single negative result redirected the whole
  audio investigation: the tones are stored samples played by a companion
  device, not synthesised in the MCU.
- The voice container stores each payload length both in the offset table and
  per block, which is what makes a zero-risk, size-identical patch possible.

## Bugs found and fixed during the work

- `ima_encode()` tested `nib & 8` for the sign while the sign was actually held
  in a separate variable, so the encoder's predictor only ever increased and
  every encoded stream diverged to the negative rail (decoded carrier 0.2 Hz).
  Fixed to test `sign`; all four bands now decode to their exact intended
  carrier.
- The first tone design used square waves, which are harmonic-rich and near
  Nyquist at 8 kHz; these do not survive 4-bit ADPCM cleanly. Switched to
  band-limited sines (measured 96–100 % energy concentration at 400–3200 Hz).
- Concentration was first measured with a 32768-point zero-padded FFT, which
  spreads a tone over thousands of bins and made good tones look bad (0.05).
  Without zero-padding the same tones measure 0.95–1.00.
- A deliberately warbling tone cannot be scored by single-bin concentration; it
  is scored by in-band energy (1400–1700 Hz) instead.

## Re-running everything

```bash
python3 tools/srec_analyze.py
python3 tools/srec_tool.py verify
python3 tools/voice_decode.py
python3 tools/voice_spectral.py
python3 tools/tonegen.py
for b in X K Ka LASER; do python3 tools/patch_voice.py $b; done
python3 tools/verify_patch.py      # must exit 0
```

## Open questions (do not treat as solved)

1. Exact RX part number (no `R5F…` string in any image).
2. Which sound ID maps to X / K / Ka / laser; whether block 16 is used for a
   system sound as well as radar alerts.
3. The physical transport and command format to the audio companion device — the
   detection→playback call path is located at the alert state machine but not
   traced to the output device.
4. Whether the updater or bootloader adds validation beyond the in-firmware
   `Valid_VOICE_IMAGE` marker compare.
5. The real ADPCM playback rate (8 kHz assumed; frequencies scale linearly).
