#!/usr/bin/env python3
"""KaLab analysis controller.

Cross-platform (Windows / Linux / macOS). Drives a bounded, resumable work
queue over the exported Ghidra artifacts. No shell-out to `ps`, `pgrep`,
`nohup` or `timeout`: locking and liveness use only the standard library.

Stages
  A  function export      - ensure every discovered function has .c and .asm
  B  indirect inventory   - jsr Rn / bra.l Rn sites with dependency notes
  C  classification       - evidence-based libc vs application labelling
  D  call graph           - direct graph, application-focused graph
  E  radar pipeline       - trace alert codes toward producers

Usage
  python controller.py status
  python controller.py run      [--once] [--max-hours N] [--stage A|B|C|D|E]
  python controller.py init-queue
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import subprocess
import sys
import time
import datetime as _dt
from pathlib import Path

from classify import classify as classify_firmware

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "python": sys.executable,
    "java_home": "",
    "ghidra_home": "",
    "project_dir": "work/ghidra/ghv3",
    "project_name": "RAD700i_v3",
    "program_name": "main_flat_fff00000.bin",
    "processor": "RX:LE:32:RXv3",
    "loader_base": "0xFFF00000",
    "firmware": "work/main_flat_fff00000.bin",
    "out_dir": "out/ghidra",
    "funcs_dir": "out/ghidra/funcs",
    "ghidra_scripts": "tools/ghidra_scripts",
    "functions_csv": "out/ghidra/functions.csv",
    "classification_seeds": "tools/analysis/classification_seeds.csv",
    "stage_a_limit": 200,
    "stage_b_limit": 400,
    "max_attempts": 3,
}

STAGES = ["A", "B", "C", "D", "E"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(path: Path | None = None) -> dict:
    root = repo_root()
    cfg = dict(DEFAULT_CONFIG)
    cfg_path = path or (root / "config.json")
    if cfg_path.exists():
        cfg.update(json.loads(cfg_path.read_text(encoding="utf-8")))
    # resolve relative paths against the repo root, absolute paths untouched
    for key in ("project_dir", "firmware", "out_dir", "funcs_dir",
                "ghidra_scripts", "functions_csv", "classification_seeds",
                "ghidra_home", "java_home"):
        val = cfg.get(key) or ""
        if val and not os.path.isabs(val):
            cfg[key] = str((root / val).resolve())
    cfg["_root"] = str(root)
    return cfg


def out_path(cfg: dict, *parts: str) -> Path:
    p = Path(cfg["out_dir"]).joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def relpath(cfg: dict, p: Path) -> str:
    """Path relative to the repo root when possible, else absolute.

    Configuration may legitimately point at another drive (e.g. D:\\KaLab),
    where relative_to() would raise; fall back to the absolute path.
    """
    try:
        return str(p.resolve().relative_to(Path(cfg["_root"]).resolve()))
    except ValueError:
        return str(p.resolve())


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------

class Log:
    def __init__(self, cfg: dict):
        logs = Path(cfg["_root"]) / "logs"
        (logs / "sessions").mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session = logs / "sessions" / f"session_{stamp}.log"
        self.main = logs / "analysis.log"
        self.errors = logs / "errors.log"

    def _write(self, path: Path, line: str) -> None:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def info(self, msg: str) -> None:
        line = f"[{_dt.datetime.now().isoformat(timespec='seconds')}] {msg}"
        print(line, flush=True)
        self._write(self.main, line)
        self._write(self.session, line)

    def error(self, msg: str) -> None:
        line = f"[{_dt.datetime.now().isoformat(timespec='seconds')}] ERROR {msg}"
        print(line, file=sys.stderr, flush=True)
        self._write(self.errors, line)
        self._write(self.session, line)


# --------------------------------------------------------------------------
# cross-platform worker lock
# --------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=15).stdout
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


class Lock:
    """Single-worker lock. Liveness is decided by PID, never by age alone."""

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def acquire(self) -> tuple[bool, str]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        for _ in range(3):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                existing = self.read()
                if not existing:
                    return False, "lock exists but cannot be read; inspect manually"
                pid = int(existing.get("pid", 0))
                if existing.get("host") != socket.gethostname():
                    return False, "lock belongs to another host; inspect manually"
                if pid and _pid_alive(pid):
                    return False, f"worker already running (pid {pid})"
                # Only reclaim a lock whose owner is confirmed dead on this host.
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
            return True, "acquired"
        return False, "could not acquire worker lock after retries"

    def release(self) -> None:
        cur = self.read()
        if cur and int(cur.get("pid", -1)) == os.getpid():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------
# work queue
# --------------------------------------------------------------------------

class Queue:
    def __init__(self, cfg: dict, log: Log):
        self.path = out_path(cfg, "workqueue.json")
        self.log = log
        self.items: dict[str, dict] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = {i["id"]: i for i in data.get("items", [])}

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"items": list(self.items.values())}, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self.path)  # atomic on Windows and POSIX

    def add(self, stage: str, target: str, **meta) -> dict:
        wid = f"{stage}:{target}"
        if wid in self.items:
            return self.items[wid]
        item = {
            "id": wid, "stage": stage, "target": target,
            "status": "PENDING", "attempts": 0, "outputs": [],
            "last_error": "",
        }
        item.update(meta)
        self.items[wid] = item
        return item

    def by_stage(self, stage: str, status: str | None = None) -> list[dict]:
        out = [i for i in self.items.values() if i["stage"] == stage]
        if status:
            out = [i for i in out if i["status"] == status]
        return out

    def mark(self, item: dict, status: str, error: str = "", outputs=None) -> None:
        item["status"] = status
        if status in ("RUNNING", "FAILED"):
            item["attempts"] = item.get("attempts", 0) + (1 if status == "FAILED" else 0)
        if error:
            item["last_error"] = error
        if outputs:
            item["outputs"] = sorted(set(item.get("outputs", [])) | set(outputs))
        self.save()

    def summary(self) -> dict:
        agg: dict[str, dict[str, int]] = {}
        for it in self.items.values():
            agg.setdefault(it["stage"], {}).setdefault(it["status"], 0)
            agg[it["stage"]][it["status"]] += 1
        return agg


# --------------------------------------------------------------------------
# Ghidra invocation (Windows .bat and POSIX shell)
# --------------------------------------------------------------------------

def headless_cmd(cfg: dict) -> list[str]:
    home = Path(cfg["ghidra_home"]) if cfg.get("ghidra_home") else None
    if not home or not home.exists():
        raise FileNotFoundError(
            "ghidra_home is not configured or does not exist; set it in config.json")
    if os.name == "nt":
        exe = home / "support" / "analyzeHeadless.bat"
    else:
        exe = home / "support" / "analyzeHeadless"
    if not exe.exists():
        raise FileNotFoundError(f"analyzeHeadless not found at {exe}")
    return [str(exe)]


def run_ghidra_script(cfg: dict, script: str, env_extra: dict | None = None,
                      timeout_s: int | None = None) -> subprocess.CompletedProcess:
    cmd = headless_cmd(cfg)
    cmd += [cfg["project_dir"], cfg["project_name"],
            "-process", cfg["program_name"], "-noanalysis",
            "-scriptPath", cfg["ghidra_scripts"], "-postScript", script]
    env = dict(os.environ)
    if cfg.get("java_home"):
        env["JAVA_HOME"] = cfg["java_home"]
    env["GHIDRA_INSTALL_DIR"] = cfg.get("ghidra_home", "")
    env["KALAB_OUT_DIR"] = cfg["out_dir"]
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, cwd=cfg["_root"], env=env, capture_output=True,
                          text=True, timeout=timeout_s)


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------

def valid_export(funcs_dir: Path, addr: str) -> bool:
    """A checkpoint is complete only if both outputs are plausible and closed."""
    try:
        c_text = (funcs_dir / f"{addr}.c").read_text(encoding="utf-8")
        asm_text = (funcs_dir / f"{addr}.asm").read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeError):
        return False
    return (c_text.startswith(f"// {addr} ") and len(c_text) > 40
            and bool(asm_text.strip()) and "// no decompilation" not in c_text)


def stage_a(cfg: dict, q: Queue, log: Log, limit: int) -> str:
    functions_csv = Path(cfg["functions_csv"])
    if not functions_csv.exists():
        return "BLOCKED functions.csv missing"
    funcs_dir = Path(cfg["funcs_dir"])
    funcs_dir.mkdir(parents=True, exist_ok=True)
    addresses = []
    with open(functions_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            addr = row["addr"].lower().replace("0x", "")
            addresses.append(addr)
    if len(set(addresses)) != len(addresses) or not addresses or addresses != sorted(addresses):
        return "BLOCKED functions.csv must contain unique ascending addresses"
    missing_indices = [i for i, addr in enumerate(addresses) if not valid_export(funcs_dir, addr)]
    if not missing_indices:
        for it in q.by_stage("A"):
            if valid_export(funcs_dir, it["target"]):
                q.mark(it, "DONE")
        return f"DONE all {len(addresses)} exports present"
    first = missing_indices[0]
    item = q.add("A", addresses[first])
    if item["attempts"] >= cfg["max_attempts"]:
        q.mark(item, "BLOCKED", error="retry limit reached")
        return f"BLOCKED {addresses[first]} failed {item['attempts']} times"
    if limit <= 0:
        q.save()
        return f"PENDING {len(missing_indices)} exports"
    # Export.java walks the Ghidra inventory in ascending address order. A
    # contiguous window from the first hole is the only valid offset/limit pair.
    window = addresses[first:first + limit]
    env = {"PASS_LIMIT": str(len(window)), "PASS_OFFSET": str(first)}
    try:
        proc = run_ghidra_script(cfg, "Export.java", env_extra=env, timeout_s=900)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return f"BLOCKED {exc}"
    if proc.returncode != 0:
        q.mark(item, "FAILED", error=f"Ghidra rc={proc.returncode}: {proc.stderr[-500:]}")
        return f"BLOCKED Ghidra export failed at {addresses[first]}"
    ok = 0
    for addr in window:
        entry = q.add("A", addr)
        if valid_export(funcs_dir, addr):
            q.mark(entry, "DONE", outputs=[f"funcs/{addr}.c", f"funcs/{addr}.asm"])
            ok += 1
        else:
            q.mark(entry, "FAILED", error=f"missing or invalid export after Ghidra rc={proc.returncode}")
    log.info(f"stage A: {ok}/{len(window)} window entries verified from offset {first}")
    return f"PARTIAL {ok}/{len(window)}" if ok else "BLOCKED no valid exports produced"


INDIRECT_RE = re.compile(r"^\s*([0-9a-f]{8})\s+((?:jsr|bra\.l)\s+R\d+)", re.M)


def stage_b(cfg: dict, q: Queue, log: Log, limit: int) -> str:
    funcs_dir = Path(cfg["funcs_dir"])
    if not funcs_dir.exists():
        return "BLOCKED no exports directory"
    rows = []
    for asm in sorted(funcs_dir.glob("*.asm")):
        func = asm.stem
        text = asm.read_text(encoding="utf-8", errors="ignore")
        for m in INDIRECT_RE.finditer(text):
            rows.append({"function": func, "instruction": m.group(1),
                         "asm": m.group(2), "dependency": "UNRESOLVED"})
    dest = out_path(cfg, "INDIRECT_CONTROL_FLOW.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["function", "instruction", "asm", "dependency"])
        w.writeheader()
        w.writerows(rows)
    q.add("B", "all")
    item = q.items["B:all"]
    if rows:
        q.mark(item, "DONE", outputs=[relpath(cfg, dest)])
        log.info(f"stage B: {len(rows)} indirect sites")
        return f"DONE {len(rows)} sites"
    q.mark(item, "FAILED", error="no indirect sites found")
    return "FAILED no sites"


def stage_c(cfg: dict, q: Queue, log: Log, limit: int) -> str:
    graph = Path(cfg["out_dir"]) / "call_graph.csv"
    if not graph.is_file():
        return "BLOCKED call_graph.csv missing (run the reference extraction first)"
    try:
        summary = classify_firmware(
            Path(cfg["functions_csv"]), graph, Path(cfg["funcs_dir"]),
            Path(cfg["classification_seeds"]), Path(cfg["out_dir"]),
        )
    except (FileNotFoundError, ValueError, KeyError) as exc:
        return f"BLOCKED classification input invalid: {exc}"
    dest = Path(cfg["out_dir"]) / "function_classification.csv"
    q.add("C", "all")
    q.mark(q.items["C:all"], "DONE", outputs=[relpath(cfg, dest)])
    log.info(f"stage C: {summary['inventory_functions']} inventoried; evidence levels {summary['confidence']}")
    return f"DONE {summary['inventory_functions']} classified (UNKNOWN preserved)"


def stage_d(cfg: dict, q: Queue, log: Log, limit: int) -> str:
    # The authoritative classifier preserves every direct edge and labels its
    # scope. Filtering away uncertain library nodes would erase evidence.
    dest = out_path(cfg, "application_call_graph.csv")
    summary = out_path(cfg, "classification_summary.json")
    if not dest.is_file() or not summary.is_file():
        return "BLOCKED stage C classification must finish first"
    evidence = json.loads(summary.read_text(encoding="utf-8"))
    with open(dest, newline="", encoding="utf-8") as fh:
        edges = list(csv.DictReader(fh))
    if len(edges) != evidence["direct_graph_edges_preserved"]:
        return "BLOCKED application graph row count does not match preserved direct graph"
    q.add("D", "all")
    q.mark(q.items["D:all"], "DONE", outputs=[relpath(cfg, dest)])
    log.info(f"stage D: {len(edges)} direct edges retained with scope labels")
    return f"DONE {len(edges)} labelled edges (none discarded)"


ALERT_CODES = {"0x10": "X", "0x20": "K", "0x30": "Ka", "0x05": "Ka-alt", "0x80": "MRCD"}


def stage_e(cfg: dict, q: Queue, log: Log, limit: int) -> str:
    funcs_dir = Path(cfg["funcs_dir"])
    if not funcs_dir.exists():
        return "BLOCKED no exports directory"
    hits = []
    for cfile in sorted(funcs_dir.glob("*.c")):
        text = cfile.read_text(encoding="utf-8", errors="ignore")
        for code, band in ALERT_CODES.items():
            if re.search(rf"\b{code}\b", text):
                hits.append({"function": cfile.stem, "code": code, "band": band})
    dest = out_path(cfg, "RADAR_ALERT_CANDIDATES.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["function", "code", "band"])
        w.writeheader()
        w.writerows(hits)
    q.add("E", "all")
    q.mark(q.items["E:all"], "DONE", outputs=[relpath(cfg, dest)])
    log.info(f"stage E: {len(hits)} candidate sites")
    return f"DONE {len(hits)} candidates"


STAGE_FUNCS = {"A": stage_a, "B": stage_b, "C": stage_c, "D": stage_d, "E": stage_e}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def cmd_status(cfg: dict, q: Queue) -> int:
    print(json.dumps({"config": {k: v for k, v in cfg.items() if not k.startswith("_")},
                      "queue": q.summary()}, indent=2))
    return 0


def cmd_run(cfg: dict, q: Queue, log: Log, args) -> int:
    lock = Lock(Path(cfg["out_dir"]) / ".analysis.lock")
    ok, msg = lock.acquire()
    if not ok:
        log.error(msg)
        return 3
    deadline = time.time() + args.max_hours * 3600 if args.max_hours > 0 else None
    stages = [args.stage] if args.stage else STAGES
    stop_request = Path(cfg["out_dir"]) / ".stop.request"
    try:
        for stage in stages:
            if stage != "A":
                marker = q.items.get(f"{stage}:all")
                if marker and marker["status"] == "DONE" and all(
                        (Path(cfg["_root"]) / path).exists() for path in marker["outputs"]):
                    log.info(f"stage {stage}: already DONE; skipped")
                    continue
            while True:
                if stop_request.exists():
                    stop_request.unlink()
                    log.info("stop requested; exiting at checkpoint")
                    return 0
                if deadline is not None and time.time() >= deadline:
                    log.info("max-hours reached; stopping at a checkpoint")
                    return 0
                result = STAGE_FUNCS[stage](cfg, q, log, cfg.get(f"stage_{stage.lower()}_limit", 200))
                log.info(f"stage {stage}: {result}")
                if result.startswith("BLOCKED") or result.startswith("FAILED"):
                    log.error(f"stage {stage} stopped: {result}")
                    return 2
                if args.once:
                    return 0
                if stage != "A" or result.startswith("DONE"):
                    break
        return 0
    except KeyboardInterrupt:
        log.info("interrupted; checkpoint saved")
        q.save()
        return 130
    finally:
        q.save()
        lock.release()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness")
    ap.add_argument("command", choices=["run", "status", "init-queue"])
    ap.add_argument("--config")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-hours", type=float, default=0)
    ap.add_argument("--stage", choices=STAGES)
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config) if args.config else None)
    log = Log(cfg)
    q = Queue(cfg, log)

    if args.command == "status":
        return cmd_status(cfg, q)
    if args.command == "init-queue":
        stage_a(cfg, q, log, 0)
        q.save()
        print(json.dumps(q.summary(), indent=2))
        return 0
    return cmd_run(cfg, q, log, args)


if __name__ == "__main__":
    sys.exit(main())
