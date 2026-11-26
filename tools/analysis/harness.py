#!/usr/bin/env python3
"""Bounded, resumable analysis harness. Each pass is <5 min; state on disk."""
import json, os, subprocess, sys, csv, glob, time, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, "out/ghidra/analysis_state.json")
LIMIT = int(os.environ.get("PASS_LIMIT", "200"))

def load():
    if os.path.exists(STATE):
        with open(STATE) as source:
            return json.load(source)
    return {"offset": 0, "pass": 0, "history": [], "stalled": 0}

def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(STATE), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(s, output, indent=1)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, STATE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def inventory():
    """Inventory order matches Ghidra's getFunctions(true) iteration."""
    path = os.path.join(ROOT, "out/ghidra/functions.csv")
    with open(path, newline="") as source:
        rows = list(csv.DictReader(source))
    addresses = [row["addr"].lower().removeprefix("0x") for row in rows]
    if not addresses or len(addresses) != len(set(addresses)) or any(
            len(a) != 8 or any(c not in "0123456789abcdef" for c in a) for a in addresses):
        raise ValueError("Invalid or duplicate addresses in functions.csv")
    # The exporter walks functions in ascending address order.
    return sorted(addresses)

def valid_export(addr):
    prefix = os.path.join(ROOT, "out/ghidra/funcs", addr)
    try:
        with open(prefix + ".c", encoding="utf-8") as source:
            c = source.read()
        with open(prefix + ".asm", encoding="utf-8") as source:
            asm = source.read()
        return (len(c) > 40 and len(asm) > 10 and addr in c.splitlines()[0]
                and "// no decompilation" not in c and bool(asm.strip()))
    except (FileNotFoundError, UnicodeError):
        return False

def first_missing(addresses):
    return next((idx for idx, addr in enumerate(addresses) if not valid_export(addr)), len(addresses))

def worker_running():
    """Self-match safe: only a real java AnalyzeHeadless process counts."""
    out = subprocess.run(["ps","-eo","comm,args"],capture_output=True,text=True).stdout
    for line in out.splitlines():
        parts = line.split(None,1)
        if len(parts)==2 and parts[0].endswith("java") and "analyzeHeadless" in parts[1]:
            return True
    return False

def run_pass(s):
    off = s["offset"]
    env = dict(os.environ, PASS_LIMIT=str(LIMIT), PASS_OFFSET=str(off),
               JAVA_HOME=os.path.join(ROOT,"tools/jdk"),
               GHIDRA_INSTALL_DIR=os.path.join(ROOT,"tools/ghidra"))
    log = os.path.join(ROOT, f"out/ghidra/passes/pass_{off}.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    ctl = os.path.join(ROOT,"out/ghidra/passes/ctl.json")
    old_timestamp = os.stat(ctl).st_mtime_ns if os.path.exists(ctl) else None
    try:
        r = subprocess.run([os.path.join(ROOT,"tools/ghidra/support/analyzeHeadless"),
            "work/ghidra/ghv3","RAD700i_v3","-process","main_flat_fff00000.bin","-noanalysis",
            "-scriptPath","tools/ghidra_scripts","-postScript","Export.java"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=290)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Ghidra pass timed out at offset {off}; inspect {log}") from error
    with open(log,"w") as output:
        output.write(r.stdout+r.stderr)
    if r.returncode != 0:
        raise RuntimeError(f"Ghidra failed (rc={r.returncode}); see {log}")
    nxt = None
    if os.path.exists(ctl) and (old_timestamp is None or os.stat(ctl).st_mtime_ns != old_timestamp):
        with open(ctl) as source:
            j = json.load(source)
        nxt = j.get("next")
        s["_total"] = j.get("total", 1273)
        if nxt is not None and nxt >= j.get("total", 1):
            nxt = j.get("total")
    if nxt is None or nxt <= off:
        raise RuntimeError(f"No fresh, progressing checkpoint from offset {off}; see {log}")
    return r.returncode, nxt

def count_exports():
    return sum(valid_export(a) for a in inventory())

def summarise(path):
    rows = list(csv.DictReader(open(path)))
    rows = [r for r in rows if r["addr"].startswith("0x") or r["addr"][0].isdigit()]
    if not rows: return {}
    sc = [int(r["score"]) for r in rows]
    return {"n": len(rows), "avg_score": round(sum(sc)/len(sc),1),
            "low_conf": sum(1 for x in sc if x < 60),
            "with_indirect": sum(1 for r in rows if int(r["indirect"])>0),
            "decomp_fail": sum(1 for r in rows if r["decompiled"] not in ("true","True"))}

def main():
    s = load()
    addresses = inventory()
    missing = first_missing(addresses)
    # Completion is checked BEFORE launching Ghidra, including for migrated/stale states.
    if missing == len(addresses):
        s.update(phase="A_COMPLETE", offset=len(addresses), stalled=0)
        save(s)
        print(json.dumps({"phase": "A_COMPLETE", "skipped": True, "next": len(addresses)}))
        return 0
    if worker_running():
        print("ABORT: another analyzeHeadless is running (duplicate guard)"); return 2
    if LIMIT <= 0:
        raise ValueError("PASS_LIMIT must be positive")
    s["offset"] = missing
    s["pass"] += 1
    rc, nxt = run_pass(s)
    after = first_missing(addresses)
    if after <= missing:
        raise RuntimeError(f"No valid exports from offset {missing}; checkpoint claims {nxt}")
    if nxt > len(addresses):
        raise RuntimeError(f"Checkpoint {nxt} exceeds inventory count {len(addresses)}")
    summ = {"exported_total": count_exports(), "total": len(addresses)}
    s["stalled"] = 0  # Validated forward progress, not a capped export count.
    s["history"].append({"pass": s["pass"], "offset": missing, "rc": rc,
                         "next": after, "reported_next": nxt, "summary": summ, "t": time.time()})
    s["offset"] = after
    s["phase"] = "A_COMPLETE" if after == len(addresses) else "A_EXPORT"
    save(s)
    print(json.dumps({"pass": s["pass"], "offset_done": s["history"][-1]["offset"],
                      "next": s["offset"], "rc": rc, "summary": summ,
                      "stalled": s["stalled"]}, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
