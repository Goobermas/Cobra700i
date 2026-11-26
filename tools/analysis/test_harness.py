"""Pass-A controller regressions with no Ghidra or vendor firmware required."""

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import harness


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "out/ghidra"
        (self.out / "funcs").mkdir(parents=True)
        with (self.out / "functions.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["addr", "name", "size"])
            writer.writerow(["fffabc00", "FUN_fffabc00", 30])
            writer.writerow(["fffabc40", "FUN_fffabc40", 20])
        self.patchers = [
            patch.object(harness, "ROOT", self.root),
            patch.object(harness, "STATE", self.out / "analysis_state.json"),
            patch.object(harness, "LIMIT", 2),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def export(self, addr):
        (self.out / "funcs" / (addr + ".c")).write_text(
            "// " + addr + " FUN_" + addr + " size=32\nvoid function(void) { return; }\n")
        (self.out / "funcs" / (addr + ".asm")).write_text(addr + "  rtsd #0x4\n")

    def test_full_inventory_skips_twice_and_repairs_stale_state(self):
        self.export("fffabc00")
        self.export("fffabc40")
        harness.save({"phase": "A_EXPORT", "offset": 0, "pass": 12, "history": [], "stalled": 11})
        with patch.object(harness, "run_pass", side_effect=AssertionError("must skip")), \
                patch.object(harness, "worker_running", return_value=False):
            self.assertEqual(harness.main(), 0)
            self.assertEqual(harness.main(), 0)
        state = json.loads((self.out / "analysis_state.json").read_text())
        self.assertEqual((state["phase"], state["offset"], state["stalled"]),
                         ("A_COMPLETE", 2, 0))

    def test_missing_pair_resumes_at_first_hole(self):
        self.export("fffabc00")
        harness.save({"phase": "A_COMPLETE", "offset": 2, "pass": 6,
                      "history": [], "stalled": 0})

        def fake_run(state):
            self.assertEqual(state["offset"], 1)
            self.export("fffabc40")
            return 0, 2

        with patch.object(harness, "run_pass", side_effect=fake_run), \
                patch.object(harness, "worker_running", return_value=False):
            self.assertEqual(harness.main(), 0)
        state = json.loads((self.out / "analysis_state.json").read_text())
        self.assertEqual((state["phase"], state["offset"], state["pass"]),
                         ("A_COMPLETE", 2, 7))

    def test_partial_c_is_not_completion(self):
        self.export("fffabc00")
        (self.out / "funcs" / "fffabc40.c").write_text("// fffabc40 FUN_fffabc40 size=20\n")
        (self.out / "funcs" / "fffabc40.asm").write_text("fffabc40  rtsd #0x4\n")
        self.assertEqual(harness.first_missing(harness.inventory()), 1)


if __name__ == "__main__":
    unittest.main()
