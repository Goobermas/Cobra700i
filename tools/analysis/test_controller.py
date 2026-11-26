#!/usr/bin/env python3
"""Synthetic tests for the KaLab controller. No Ghidra, no firmware required."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import controller

HARNESS = Path(__file__).with_name("controller.py")


def build_fixture(root: Path) -> Path:
    out = root / "out" / "ghidra"
    funcs = out / "funcs"
    funcs.mkdir(parents=True)

    # two fake functions: one libc-ish (errno), one hardware-ish (PWM register)
    (funcs / "fff00001.c").write_text(
        "// fff00001 FUN_fff00001 size=10\n"
        "void f(void){ DAT_0007e0ac = 0x16; }\n", encoding="utf-8")
    (funcs / "fff00001.asm").write_text(
        "fff00001  mov.l #0x7e0ac,R1\nfff00002  jsr R14\n", encoding="utf-8")
    (funcs / "fff00002.c").write_text(
        "// fff00002 FUN_fff00002 size=8\n"
        "void g(void){ _DAT_000c1218 = 0x10; }\n", encoding="utf-8")
    (funcs / "fff00002.asm").write_text(
        "fff00002  mov.w #0x10,[R1]\nfff00003  bra.l R1\n", encoding="utf-8")

    (out / "functions.csv").write_text(
        "addr,name,size,callers,callees\n"
        "fff00001,FUN_fff00001,10,1,1\n"
        "fff00002,FUN_fff00002,8,1,0\n", encoding="utf-8")

    (out / "call_graph.csv").write_text(
        "caller,callee,kind\n"
        "fff00001,fff00002,direct_call\n", encoding="utf-8")

    cfg = {
        "ghidra_home": "", "java_home": "",
        "project_dir": str(root / "project"),
        "firmware": str(root / "fw.bin"),
        "out_dir": str(out),
        "funcs_dir": str(funcs),
        "ghidra_scripts": str(root / "scripts"),
        "functions_csv": str(out / "functions.csv"),
        "classification_seeds": str(root / "unused-seeds.csv"),
        "max_attempts": 3,
    }
    cfg_path = root / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path


def run(cfg_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HARNESS), *args, "--config", str(cfg_path)],
                          capture_output=True, text=True, timeout=120)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="kalab test "))  # note the space
        self.cfg = build_fixture(self.root)
        self.out = self.root / "out" / "ghidra"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_stage_b_records_indirect_sites(self):
        proc = run(self.cfg, "run", "--stage", "B")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        csv_path = self.out / "INDIRECT_CONTROL_FLOW.csv"
        self.assertTrue(csv_path.exists())
        rows = csv_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(rows), 3)  # header + jsr R14 + bra.l R1
        self.assertIn("jsr R14", "\n".join(rows))

    def test_stage_c_classifies_and_keeps_unknown(self):
        proc = run(self.cfg, "run", "--stage", "C")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The verified classifier requires actual supporting seeds; an errno
        # address or peripheral-looking literal is not proof by itself.
        text = (self.out / "function_classification.csv").read_text(encoding="utf-8")
        self.assertIn("Unknown,UNKNOWN", text)
        self.assertIn("0xFFF00002", text)
        self.assertEqual(len(text.strip().splitlines()), 3)

    def test_stage_d_preserves_unclassified_edges(self):
        run(self.cfg, "run", "--stage", "C")
        proc = run(self.cfg, "run", "--stage", "D")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        app = (self.out / "application_call_graph.csv").read_text(encoding="utf-8")
        self.assertEqual(len(app.strip().splitlines()), 2)
        self.assertIn("unresolved_category", app)

    def test_stage_e_finds_alert_codes(self):
        proc = run(self.cfg, "run", "--stage", "E")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (self.out / "RADAR_ALERT_CANDIDATES.csv").read_text(encoding="utf-8")
        self.assertIn("0x10", text)

    def test_completed_stage_does_not_restart_work(self):
        run(self.cfg, "run", "--stage", "B")
        q1 = json.loads((self.out / "workqueue.json").read_text(encoding="utf-8"))
        run(self.cfg, "run", "--stage", "B")
        q2 = json.loads((self.out / "workqueue.json").read_text(encoding="utf-8"))
        self.assertEqual(len(q1["items"]), len(q2["items"]))
        self.assertTrue(all(i["status"] == "DONE" for i in q2["items"]))

    def test_missing_ghidra_is_reported_not_crashed(self):
        # delete one export so stage A genuinely has work to do
        (self.out / "funcs" / "fff00002.asm").unlink()
        proc = run(self.cfg, "run", "--stage", "A")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("BLOCKED", proc.stdout)
        self.assertIn("ghidra_home", proc.stdout)

    def test_stage_a_resumes_at_first_missing_index(self):
        (self.out / "funcs" / "fff00002.asm").unlink()
        cfg = controller.load_config(self.cfg)
        log = controller.Log(cfg)
        q = controller.Queue(cfg, log)
        def fake_ghidra(_cfg, script, env_extra, timeout_s):
            self.assertEqual(script, "Export.java")
            self.assertEqual(env_extra["PASS_OFFSET"], "1")
            self.assertEqual(env_extra["PASS_LIMIT"], "1")
            (self.out / "funcs" / "fff00002.asm").write_text(
                "fff00002  mov.w #0x10,[R1]\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(controller, "run_ghidra_script", side_effect=fake_ghidra):
            self.assertIn("PARTIAL", controller.stage_a(cfg, q, log, 1))
            self.assertIn("DONE", controller.stage_a(cfg, q, log, 1))

    def test_full_run_advances_multiple_export_windows(self):
        funcs = self.out / "funcs"
        for addr in ("fff00001", "fff00002"):
            (funcs / f"{addr}.c").unlink()
            (funcs / f"{addr}.asm").unlink()
        cfg = controller.load_config(self.cfg)
        cfg["stage_a_limit"] = 1
        log = controller.Log(cfg)
        q = controller.Queue(cfg, log)
        offsets = []
        def fake_ghidra(_cfg, script, env_extra, timeout_s):
            offset = int(env_extra["PASS_OFFSET"])
            offsets.append(offset)
            addr = ("fff00001", "fff00002")[offset]
            (funcs / f"{addr}.c").write_text(
                f"// {addr} FUN_{addr} size=8\nvoid f(void) {{ return; }}\n", encoding="utf-8")
            (funcs / f"{addr}.asm").write_text(f"{addr}  rts\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, "", "")
        args = SimpleNamespace(stage="A", once=False, max_hours=0)
        with mock.patch.object(controller, "run_ghidra_script", side_effect=fake_ghidra):
            self.assertEqual(controller.cmd_run(cfg, q, log, args), 0)
        self.assertEqual(offsets, [0, 1])
        self.assertEqual({i["status"] for i in q.by_stage("A")}, {"DONE"})
        self.assertEqual(controller.cmd_run(cfg, q, log, args), 0)
        self.assertEqual(offsets, [0, 1])  # no duplicate exports

    def test_stop_request_is_honored_and_consumed(self):
        (self.out / ".stop.request").write_text("", encoding="utf-8")
        proc = run(self.cfg, "run", "--stage", "B")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("stop requested", proc.stdout)
        self.assertFalse((self.out / ".stop.request").exists())
        self.assertFalse((self.out / "INDIRECT_CONTROL_FLOW.csv").exists())

    def test_all_exports_present_is_done_not_blocked(self):
        proc = run(self.cfg, "run", "--stage", "A")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("DONE", proc.stdout)

    def test_lock_blocks_second_worker(self):
        lock = self.out / ".analysis.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"pid": os.getpid(), "host": __import__("socket").gethostname()}),
                        encoding="utf-8")
        proc = run(self.cfg, "run", "--stage", "B")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("already running", proc.stderr)

    def test_stale_lock_from_dead_pid_is_reclaimed(self):
        lock = self.out / ".analysis.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"pid": 999999, "host": __import__("socket").gethostname()}),
                        encoding="utf-8")
        proc = run(self.cfg, "run", "--stage", "B")
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
