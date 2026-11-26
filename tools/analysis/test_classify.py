"""Synthetic fixtures only: never require or copy proprietary firmware."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from classify import address, classify


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        w = csv.writer(stream)
        w.writerow(columns)
        w.writerows(rows)


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exports = self.root / "funcs"
        self.exports.mkdir()
        self.out = self.root / "out"
        self.inv = self.root / "functions.csv"
        self.graph = self.root / "call_graph.csv"
        self.seeds = self.root / "seeds.csv"
        write_csv(self.inv, ["addr", "name", "size"], [
            ["fffabc00", "FUN_fffabc00", "40"],
            ["fffabc40", "FUN_fffabc40", "20"],
            ["fffabc80", "FUN_fffabc80", "30"],
        ])
        write_csv(self.graph, ["caller", "callee", "kind"], [
            ["fffabc00", "fffabc40", "direct_call"],
            ["fffabc80", "fffabc40", "direct_call"],
        ])
        write_csv(self.seeds, ["addr", "category", "confidence", "evidence", "semantic_name"], [
            ["fffabc40", "C standard runtime", "PROBABLE", "Synthetic standard parser", "fopen_like"],
            ["fffabc80", "Audio", "VERIFIED", "Synthetic timer evidence", "tone_pwm"],
        ])
        (self.exports / "fffabc00.asm").write_text("fffabc00  jsr R14\nfffabc02  bra.l R1\n")
        (self.exports / "fffabc40.asm").write_text("fffabc40  rts\n")
        (self.exports / "fffabc80.asm").write_text("fffabc80  jsr R5\n")

    def test_evidence_and_edge_preservation(self):
        data = classify(self.inv, self.graph, self.exports, self.seeds, self.out)
        self.assertEqual(data["inventory_functions"], 3)
        self.assertEqual(data["direct_graph_edges_preserved"], 2)
        self.assertEqual(data["indirect_calls"], 2)
        self.assertEqual(data["computed_jumps"], 1)
        with (self.out / "function_classification.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        unknown = next(r for r in rows if r["addr"] == "0xFFFABC00")
        self.assertEqual((unknown["primary_category"], unknown["confidence"]), ("Unknown", "UNKNOWN"))
        with (self.out / "application_call_graph.csv").open() as stream:
            edges = list(csv.DictReader(stream))
        self.assertEqual([e["scope"] for e in edges], ["unresolved_category", "runtime_involved"])
        with (self.out / "indirect_control_flow.csv").open() as stream:
            sites = list(csv.DictReader(stream))
        self.assertEqual(len(sites), 3)
        self.assertTrue(all(r["target"] == "UNRESOLVED" for r in sites))
        self.assertEqual(json.loads((self.out / "classification_summary.json").read_text())["indirect_calls"], 2)

    def test_missing_export_fails_without_fabricating_results(self):
        (self.exports / "fffabc80.asm").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "fffabc80"):
            classify(self.inv, self.graph, self.exports, self.seeds, self.out)
        self.assertFalse((self.out / "function_classification.csv").exists())

    def test_duplicate_inventory_rejected(self):
        with self.inv.open("a") as stream:
            stream.write("0xFFFABC00,duplicate,3\n")
        with self.assertRaisesRegex(ValueError, "duplicate function"):
            classify(self.inv, self.graph, self.exports, self.seeds, self.out)

    def test_nonzero_missing_seed_is_rejected(self):
        with self.seeds.open("a") as stream:
            stream.write("0xFFFABB00,Audio,PROBABLE,test,other\n")
        with self.assertRaisesRegex(ValueError, "absent from inventory"):
            classify(self.inv, self.graph, self.exports, self.seeds, self.out)

    def test_address_validation(self):
        self.assertEqual(address("ffabc"), "0x000FFABC")
        with self.assertRaises(ValueError):
            address("0x100000000")


if __name__ == "__main__":
    unittest.main()
