# Research state and resumability

## Verified environment facts

- Cloud shell commands have a **hard 5-minute cap**; the tool's `BACKGROUND` process type is documented as
  **unavailable** in this environment.
- Therefore **no autonomous overnight worker can be claimed**. A `nohup` process can be started and observed,
  but its survival past the end of the AI session is not guaranteed and cannot be verified from inside the
  session. This file records that honestly rather than asserting overnight execution is active.
- All analysis therefore runs as **short, resumable batches** (< 5 min each), each writing its results to
  `out/ghidra/` before exiting, so a later session resumes from artifacts, not from memory.

## Resume commands

```bash
cd /workspace/chats/cb4e7a1cf220c69df53d0858
export JAVA_HOME=$PWD/tools/jdk GHIDRA_INSTALL_DIR=$PWD/tools/ghidra
# interrupt vectors + register tables
tools/ghidra/support/analyzeHeadless work/ghidra/ghv3 RAD700i_v3 -process main_flat_fff00000.bin \
  -noanalysis -scriptPath tools/ghidra_scripts -postScript Irq2.java
# single function decompile (edit ADDRS in the script)
tools/ghidra/support/analyzeHeadless work/ghidra/ghv3 RAD700i_v3 -process main_flat_fff00000.bin \
  -noanalysis -scriptPath tools/ghidra_scripts -postScript Init.java
```

## Checkpoints (completed, on disk)

- `work/ghidra/ghv3` — project (1,273 functions)
- `out/ghidra/functions.csv`, `irq_vectors.csv`, `irq_registers.csv`, `vector_targets.csv`
- `out/ghidra/irq/*.c|*.asm` (36), `out/ghidra/init/*.c` (10), `reset.c/.asm/_calls.csv`
- `BOOT_SEQUENCE.md`, `INTERRUPT_MAP.md`

## Duplicate-worker guard

Start a batch only if no `analyzeHeadless` process is running:
`pgrep -f "analyzeHeadless work/ghidra/ghv3" || <run batch>`
