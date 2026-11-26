#!/usr/bin/env python3
"""Bounded, resumable analysis harness. Each pass is <5 min; state on disk."""
import json, os, subprocess, sys, csv, glob, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(ROOT, "out/ghidra/analysis_state.json")
LIMIT = int(os.environ.get("PASS_LIMIT", "200"))

def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"offset": 0, "pass": 0, "history": [], "stalled": 0}

def save(s):
    json.dump(s, open(STATE, "w"), indent=1)

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
    r = subprocess.run([os.path.join(ROOT,"tools/ghidra/support/analyzeHeadless"),
        "work/ghidra/ghv3","RAD700i_v3","-process","main_flat_fff00000.bin","-noanalysis",
        "-scriptPath","tools/ghidra_scripts","-postScript","Export.java"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=290)
    open(log,"w").write(r.stdout+r.stderr)
    nxt = None
    ctl = os.path.join(ROOT,"out/ghidra/passes/ctl.json")
    if os.path.exists(ctl):
        j = json.load(open(ctl))
        nxt = j.get("next")
        s["_total"] = j.get("total", 1273)
        if nxt is not None and nxt >= j.get("total", 1):
            nxt = j.get("total")
    return r.returncode, nxt

def count_exports():
    import glob as g
    return len(g.glob(os.path.join(ROOT,"out/ghidra/funcs/*.c")))

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
    if worker_running():
        print("ABORT: another analyzeHeadless is running (duplicate guard)"); return 2
    s = load()
    if s.get("phase") == "A_COMPLETE":
        print(json.dumps({"phase": "A_COMPLETE", "skipped": True, "next": s.get("offset")}))
        return 0
    s["pass"] += 1
    rc, nxt = run_pass(s)
    summ = {"exported_total": count_exports()}
    if summ["exported_total"] >= 1273:
        s["phase"] = "A_COMPLETE"
        s["offset"] = 1273
    prev = s["history"][-1]["summary"] if s["history"] else None
    cur = summ.get("exported_total", 0)
    improved = (prev is None) or (cur > prev.get("exported_total", 0))
    s["stalled"] = 0 if improved else s["stalled"]+1
    s["history"].append({"pass": s["pass"], "offset": s["offset"], "rc": rc,
                         "next": nxt, "summary": summ, "t": time.time()})
    s["offset"] = nxt if nxt is not None else 0
    if nxt is not None and s["offset"] >= s["history"][-1].get("total", 1273):
        s["phase"] = "A_COMPLETE"
    save(s)
    print(json.dumps({"pass": s["pass"], "offset_done": s["history"][-1]["offset"],
                      "next": s["offset"], "rc": rc, "summary": summ,
                      "stalled": s["stalled"]}, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
