# KaLab — Windows 11 research runner

Reverse-engineering support tooling for the Cobra RAD 700i firmware (Renesas RX).
This package contains **no firmware and no vendor binaries**.

## 1. Prerequisites

| component | version | notes |
|---|---|---|
| Python | 3.9+ (3.11+ preferred) | `python --version` |
| JDK | **21** | Ghidra 11.4.2 requires 21; Ghidra 12.2 requires 25 |
| Ghidra | **11.4.2** | `analyzeHeadless.bat` must exist under `support\` |
| Ghidra-Rare RX module | RXv1/v2/v3 | installed at `Ghidra\Extensions\RX` |
| Firmware image | 1,048,576 bytes | supplied by you, never redistributed |

### Installing the RX module

```powershell
git clone https://github.com/aleph-void/Ghidra-Rare C:\Tools\Ghidra-Rare
cd C:\Tools\Ghidra-Rare
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-21"
$env:GHIDRA_INSTALL_DIR = "C:\Tools\ghidra_11.4.2_PUBLIC"
.\..\ghidra_11.4.2_PUBLIC\support\gradle\gradlew -p RX buildExtension
```

The produced ZIP ships **without** `data\languages`, so after copying the module to
`Ghidra\Extensions\RX` you must also copy `data\` and compile the SLEIGH specs:

```powershell
Copy-Item -Recurse C:\Tools\Ghidra-Rare\RX\data C:\Tools\ghidra_11.4.2_PUBLIC\Ghidra\Extensions\RX\
& C:\Tools\ghidra_11.4.2_PUBLIC\support\sleigh.bat -a `
  C:\Tools\ghidra_11.4.2_PUBLIC\Ghidra\Extensions\RX\data\languages
```

`rx_v1.sla`, `rx_v2.sla` and `rx_v3.sla` must exist afterwards. The language ID used by
the project is `RX:LE:32:RXv3`.

## 2. Configure

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

Set `java_home`, `ghidra_home`, and the firmware / project paths. Relative paths resolve
against the package root; absolute paths (for example `D:\KaLab\work\ghidra\ghv3`) are used
as-is, so the workspace may live on your HDD while Ghidra lives on the SSD.

## 3. Verify before running

```powershell
.\run_analysis.ps1 -DryRun
```

Every prerequisite is checked (Python, JDK 21, Ghidra 11.4.2, RXv3 `.sla` files, firmware
size, project directory, `functions.csv`). Nothing is launched. A non-zero exit means
something must be installed or a path corrected.

## 4. Run

```powershell
.\run_analysis.ps1 -RunOnce            # one bounded unit of work
.\run_analysis.ps1 -MaxHours 8         # stop at a checkpoint after 8 hours
.\run_analysis.ps1 -Resume             # continue from the last checkpoint
.\run_analysis.ps1                     # run all stages until converged
```

Stop gracefully with `.\stop_analysis.ps1` (writes a stop request and lets the current
batch finish). `-Force` terminates the recorded controller PID only after checking
its command line belongs to KaLab; it never kills arbitrary `java.exe` processes.
`-MaxHours` is an **upper bound**, not a promise to run for that long. The job exits
as soon as these finite extraction stages finish or a prerequisite blocks progress.

## 5. What the stages actually do

| stage | work | unattended? |
|---|---|---|
| A | ensure every function in `functions.csv` has `.c` **and** `.asm` | yes |
| B | inventory `jsr Rn` / `bra.l Rn` sites with their containing function | yes |
| C | run the repository's evidence-based classifier and preserve `Unknown` | yes |
| D | verify application-scoped graph labels, retaining all direct-call edges | yes |
| E | locate alert-code sites (X `0x10`, K `0x20`, Ka `0x30`/`0x05`, MRCD `0x80`) | yes |

**Limitation, stated plainly:** stages B–E are *evidence extractors*, not solvers. They
produce inventories and candidate lists; they do **not** recover indirect call targets,
reconstruct data structures, or prove the radar dataflow. An overnight run stops when
every work item is `DONE`, `BLOCKED` or `FAILED` — it will not keep producing new insight
after that, and it will not re-process completed items.

## 6. Work queue and recovery

State lives in `<out_dir>\workqueue.json`. Each item records id, stage, target, status
(`PENDING`/`RUNNING`/`DONE`/`BLOCKED`/`FAILED`), attempt count, outputs and last error.
Writes are atomic (`os.replace`), so a power cut cannot half-write the queue.

- An export is complete only when its `.c` and `.asm` pass validation. The exporter resumes
  from the first missing address and checkpoints after each function.
- Three failed attempts block that export. A prerequisite failure stops downstream stages
  instead of labeling incomplete results as complete.
- A lock file (`<out_dir>\.analysis.lock`) is created exclusively to prevent duplicate workers.
  A confirmed-dead local PID may be reclaimed; foreign-host locks require manual review.

## 7. Logs

```
logs\analysis.log            append-only controller log
logs\errors.log              errors only
logs\sessions\session_*.log  one file per launch
```

## 8. Tests

```powershell
python -m unittest discover -s tools\analysis -p "test_*.py" -v
```

The synthetic suites cover resumable export, conservative classification, graph preservation,
stop requests, checkpoint idempotence, missing dependencies and worker locking. They need
no Ghidra and no firmware. A real Ghidra/RXv3 run still requires your private inputs.
