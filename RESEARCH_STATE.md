# Research state and resumability

## Verified environment facts

- Cloud shell commands have a **hard 5-minute cap**; the tool's `BACKGROUND` process type is documented as
  **unavailable** in this environment.
- Therefore **no autonomous overnight worker can be claimed**. A `nohup` process can be started and observed,
  but its survival past the end of the AI session is not guaranteed and cannot be verified from inside the
  session. This file records that honestly rather than asserting overnight execution is active.
- All analysis therefore runs as **short, resumable batches** (< 5 min each), each writing its results to
  `out/ghidra/` before exiting, so a later session resumes from artifacts, not from memory.

## Resume commands (in the private research workspace)

```bash
cd /path/to/your/Cobra700i
export JAVA_HOME=$PWD/tools/jdk GHIDRA_INSTALL_DIR=$PWD/tools/ghidra
# Synthetic-tooling tests; does not require firmware:
python3 -m unittest discover -s tools/analysis -p 'test_*.py' -v
# Export only missing functions (uses out/ghidra/functions.csv):
PASS_LIMIT=120 python3 tools/analysis/harness.py
# Classify every function from the private exports and corrected graph:
python3 tools/analysis/classify.py
# Targeted Ghidra interrupt rerun:
tools/ghidra/support/analyzeHeadless work/ghidra/ghv3 RAD700i_v3 -process main_flat_fff00000.bin \
  -noanalysis -scriptPath tools/ghidra_scripts -postScript Irq2.java
```

## Checkpoints (reported from the original private research session)

- `work/ghidra/ghv3` — project (reported 1,273 functions)
- `out/ghidra/functions.csv`, `irq_vectors.csv`, `irq_registers.csv`, `vector_targets.csv`
- `out/ghidra/irq/*.c|*.asm` (36), `out/ghidra/init/*.c` (10), `reset.c/.asm/_calls.csv`
- `BOOT_SEQUENCE.md`, `INTERRUPT_MAP.md`

## Duplicate-worker guard

The old `pgrep -f` pattern could match the invoking shell and incorrectly abort.
The checked-in controller uses a self-match-safe `ps` check. Do not run two
Ghidra jobs on the same project concurrently; this guard is best-effort.

The controller checks for completed `.c` **and** `.asm` export pairs before
launching Ghidra and resumes at the first missing/invalid pair. It never uses
`next=0` to mean completion, and the exporter stages temporary files before
atomically renaming them and advancing its checkpoint.

The private Ghidra database and exports above are **not in this Git branch**.
A fresh clone needs them restored privately before any real analysis can run;
the synthetic tests alone do not validate actual firmware semantics.
