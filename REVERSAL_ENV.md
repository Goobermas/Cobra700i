# Phase 1 environment: Ghidra for RX — probe results and setup plan

Status: **milestone not met this turn.** No Ghidra project exists yet. This file records the
environment probe, the module evaluation, and the exact reproducible steps, so the next session
starts executing rather than deciding.

## 1. What the sandbox actually provides (measured)

| check | result |
|---|---|
| `java -version` | **`java: command not found`** — no JDK present |
| `curl -sI https://github.com/.../ghidra/releases/latest` | **302** — network reachable |
| disk `/workspace` | **7.0 GB free** (809 MB used) |
| `python3 -V` | 3.12.3 |

So nothing blocks Ghidra except the missing toolchain: a JDK (~200 MB) plus Ghidra
(~400 MB) must be installed before any import. I did not start that download, because a
600 MB install followed by import, auto-analysis and headless decompilation cannot be completed
and verified in the remaining turn — and an unverified Ghidra project is worth less than an
honest blocker.

## 2. Processor module evaluation

Firmware is Renesas RX, confirmed independently of any tool: RX-specific encodings
(`fb 1a` = `mov.l #imm16, r1`, `e5` mem-to-mem with `.L` displacements scaled ×4, `05` = `bsr.a`
with a 24-bit displacement from `site+4`, `rtsd`, `btst`, DSP forms `dpushm.d`/`dmul`/`ftod`).

| candidate | claim to check first |
|---|---|
| **rx-proc-ghidra** | purpose-built RX module; verify it declares an `rx` processor and handles `bfmovz`, DSP `dmul`/`mvtachi`, `rtsd` |
| **Ghidra-Rare** | Renesas family module; its name suggests the "Rare" cores (RL78/M16C/R8C). **Do not assume it covers RX** — check its manifest for an RX language definition before choosing it |
| stock Ghidra | has no RX language; the import would fall back to a raw processor, which produces garbage |

Selection rule: the module must decode the five instruction forms we can verify byte-exactly
against `work/main_full.dis` (GNU `rx-elf-objdump`, binutils 2.42 sources present under
`tools/binutils-2.42`). Validation set, all with known-correct disassembly:

```
0xFFFB2BA1  tone()        fb 12 c4 af 03 00  mov.l #0x3afc4, r14 ...
0xFFF93C47  beep site     fb 1a 98 3a        mov.l #0x3a98, r1
0xFFF8681E  record copy   e5 10 05 01        mov.l 20[r1], 4[r0]
0xFFF867E3  branch        beq.s / bra.s      short forms
0xFFFA7A??  DSP probe     dpushm.d / dmul    (expect partial support)
0xFFF868CB  epilogue      rtsd #8
```

Any instruction the module fails to decode is recorded as an unsupported-instruction row in the
coverage report, not silently skipped.

## 3. Memory map for the import (all facts already established)

| region | range | basis |
|---|---|---|
| ROM / code | `0xFFF00000`–`0xFFFFFFFF` (1 MiB) | image size and base, byte-verified |
| vectors | `0xFFFFFFD0`–`0xFFFFFFFF` | 12 vectors; reset at `0xFFFFFFFC` = `0xFFFA8708` |
| last erased run | `0xFFFD0C0B`–`0xFFFFFFCF` | byte scan; the cave region lives here |
| RAM globals seen | `0x00000`–`0x7E53C`+ | address literals (`0x3AFC4`, `0x3BF88`, `0x4C5D4`, `0x712F4`, `0x7E53C`) |
| initial SP | **unknown — read it** from vector[0] at `0xFFFFFFD0` before mapping RAM | do not invent a stack top |
| peripherals in use | `0xC1200`–`0xC1300` (PWM `0xC1218/0xC121A`, sample out `0xC1228`, `0xC1280`, `0xC1300`) | register writes in the disassembly |
| port/misc | `0x8C000`+, `0xAEB6`, `0x19DE3` | bit-set/clear idioms |

Import as raw binary at base `0xFFF00000`, then add the RAM and peripheral blocks as
*uninitialised* memory so cross-references to them resolve.

## 4. Headless command sequence (to run next session)

```bash
# 1. toolchain
sudo apt-get install -y openjdk-21-jdk-headless        # or unpack a JDK tarball
curl -L -o /tmp/ghidra.zip <ghidra 11.x release zip>   # verify the published sha256
unzip -q /tmp/ghidra.zip -d tools/ghidra
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

# 2. RX processor module (choose per §2, then drop the zip in)
tools/ghidra/support/analyzeHeadless.bat  # no: use support/analyzeHeadless
tools/ghidra/support/analyzeHeadless /tmp/ghproj RAD700i \
    -import work/main_flat_fff00000.bin -loader BinaryLoader \
    -loader-baseAddr 0xFFF00000 -processor RX:LE:32:default \
    -scriptPath tools/ghidra_scripts -postScript Probe.java -deleteProject

# 3. first milestone: decompile the PWM tone function
#    create function at 0xFFFB2BA1, then DecompileFunction -> out/ghidra/tone.c
```

`-processor RX:LE:32:default` is a placeholder to be replaced by the language ID the chosen
module actually registers — resolving that ID is step one after install.

## 5. First milestone, defined precisely

Target: Ghidra decompilation of `0xFFFB2BA1` (`tone`), which we already understand completely:

* takes the period in `r1`, writes `period-1` to `0xC1218` and `(period-1)>>1` to `0xC121A`
  (four accesses, all inside this function);
* all eight constant call sites pass `0x3A98`;
* reconstructed semantics are in `CLOCK_AND_PATCH.md` and `SHARED_TONE_PATCH.md` §1.

Acceptance: the pseudocode shows two 16-bit peripheral stores derived from the argument, no
phantom calls, and the parameter count matches `r1`. Anything else (wrong widths, a bogus return
type, a missing store) is a module/decoding defect to record before expanding scope.

Then expand in this order: reset handler `0xFFFA8708` → interrupt handlers (from the vector
table) → the already-modelled functions (`0xFFF866B9` record aging, `0xFFF93BCF` sounder,
`0xFFFA606E` arm, `0xFFF793??` ring copy, `0xFFFB2EA4` sample feeder).

## 6. What is already available to validate against

* `work/main_full.dis` — GNU objdump of the whole image (ground truth for decoding);
* `tools/dis_range.py`, `tools/funcs.py` — address/function queries used throughout;
* `tools/rxmini.py` — our own decoder for the attested forms, plus four passing test suites
  (`test_band_period`, `test_scenarios`, `test_latch`, `test_alert_path`);
* hand-reconstructed semantics for ~12 functions in the existing reports.

## 7. Distribution note

The Ghidra project, the raw image and any full disassembly dump stay out of the public repo
(already git-ignored). Committed material remains: scripts, maps, function databases keyed by
address, and pseudocode excerpts needed to explain a finding — reviewed before publication.
