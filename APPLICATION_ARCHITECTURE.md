# Application vs runtime — current reconstruction

The public branch intentionally excludes the proprietary firmware, the Ghidra
project, and the private CSV/export corpus. Accordingly these baseline numbers
are **reported measurements awaiting rerun**, not outputs reconstructed from
files in this repository:

- 1,273 discovered functions in the RXv3 Ghidra inventory.
- 2,644 direct caller→callee edges recovered using Ghidra's references.
- 90 `jsr Rn` register-indirect call sites and 16 computed branches.
- 256 relocated interrupt vectors at `0xFFF57750`, reducing to 36 unique
  targets (34 functional handlers, one RTE stub, one default handler).

Do not equate missing `ReferenceManager` indirect edges with absence of
indirect calls. A previous call-graph built from pseudocode comments included
1,273 fabricated self-edges; the corrected reference graph is the primary
source for direct calls. Retain the original graph without edits.

## Components supported by prior disassembly work

| Area | Evidence anchor | Status |
|---|---|---|
| Reset and vectors | `0xFFFA8708`, `0xFFF57750` | Control-register setup documented in `BOOT_SEQUENCE.md`. |
| PWM beep | `0xFFFB2BA1` | Period/half-duty register stores verified by RXv3 decompilation and disassembly. |
| Alert records | `0xFFF866B9` | Band-code comparisons and four-record traversal described in `ALERT_PATH.md`. |
| Sounder arm | `0xFFFA606E` | Sets a bit in a shared gate; no band record is passed to the wrapper. |
| Standard streams | `0xFFFC8B56` et al. | Strong runtime-library hypothesis; see `LIBC_IDENTIFICATION.md`. |

## Analysis workflow (requires the private workspace)

```bash
python3 -m unittest discover -s tools/analysis -p 'test_*.py' -v
python3 tools/analysis/classify.py
```

Input files (all gitignored):

- `out/ghidra/functions.csv`: `addr,name,size` (other columns permitted).
- `out/ghidra/call_graph.csv`: `caller,callee,kind` (direct graph only).
- `out/ghidra/funcs/<lowercase-8-digit-address>.asm`: instruction exports.

Outputs under `out/ghidra/`:

| File | What it contains |
|---|---|
| `function_classification.csv` | Exactly one row per inventory function; evidence and confidence. |
| `libc_functions.csv` | C-runtime/compiler-support candidates only. |
| `application_call_graph.csv` | **Every** original direct edge with a new scope column; it does not erase unknown/runtime-crossing edges. |
| `indirect_control_flow.csv` | `jsr Rn` / `bra.l Rn` sites; targets explicitly `UNRESOLVED` rather than invented. |
| `classification_summary.json` | Coverage, uncertainty and baseline count comparisons. |

The script deliberately does **not** claim to decompile all functions or
discover hidden dynamic edges. It fails on a missing `.asm` export, malformed
CSV, duplicate function address, or stale seed that does not appear in the
inventory. Baseline mismatches are reported for investigation; they are not
hidden by dropping rows.

## What remains unresolved

1. Actually run the classification tool in the original private workspace and
   inspect the results; no real 1,273-row classified CSV is published here.
2. Find the radar acquisition→record-producer chain. The alert-log routine is
   a **consumer**, not proof of acquisition.
3. Recover targets of register-indirect call sites with reaching-definition
   analysis; table-pointer-looking constants alone cannot establish an edge.
4. Confirm peripheral names against the exact MCU register map before naming
   ADC, DMA, or serial blocks.
