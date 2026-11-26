#!/usr/bin/env python3
"""Produce evidence-labelled views of private Ghidra exports, without firmware.

This script deliberately does not infer semantics from addresses, function size,
fan-in, or neighbouring functions. Unclassified entries remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = {
    "C standard runtime",
    "Compiler-generated support",
    "Hardware/peripheral driver",
    "Radar acquisition/DSP",
    "Alert processing",
    "Audio",
    "Display/UI",
    "Communications/BLE/GPS",
    "Initialization/interrupt handling",
    "Unknown",
}
CONFIDENCE = {"VERIFIED", "PROBABLE", "UNKNOWN"}
INSTRUCTION = re.compile(r"^\s*([0-9a-fA-F]{8})\s+(.+?)\s*$")
INDIRECT = re.compile(r"^(jsr\s+R\d+|bra\.l\s+R\d+)\b", re.IGNORECASE)


def address(value: str) -> str:
    value = value.strip().lower().removeprefix("0x")
    if not re.fullmatch(r"[0-9a-f]{1,8}", value):
        raise ValueError(f"invalid 32-bit address: {value!r}")
    return f"0x{int(value, 16):08X}"


def read_rows(path: Path, columns: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not columns.issubset(reader.fieldnames):
            raise ValueError(f"{path}: expected columns {sorted(columns)}")
        return list(reader)


def atomic_write(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def scan_indirect(exports: Path, addr: str) -> list[dict[str, str]]:
    source = exports / (addr[2:].lower() + ".asm")
    if not source.is_file():
        raise FileNotFoundError(f"Missing assembly export: {source}")
    results = []
    for raw in source.read_text(encoding="utf-8").splitlines():
        match = INSTRUCTION.match(raw)
        if not match:
            continue
        opcode = match.group(2).strip()
        if not INDIRECT.match(opcode):
            continue
        results.append({
            "function": addr,
            "site": address(match.group(1)),
            "kind": "indirect_call" if opcode.lower().startswith("jsr ") else "computed_jump",
            "instruction": opcode,
            "target": "UNRESOLVED",
        })
    return results


def load_seeds(path: Path) -> dict[str, dict[str, str]]:
    result = {}
    if not path.is_file():
        return result
    for row in read_rows(path, {"addr", "category", "confidence", "evidence"}):
        addr = address(row["addr"])
        if addr in result:
            raise ValueError(f"duplicate seed: {addr}")
        if row["category"] not in CATEGORIES or row["confidence"] not in CONFIDENCE:
            raise ValueError(f"unsupported category/confidence for {addr}: {row}")
        if row["category"] != "Unknown" and not row["evidence"].strip():
            raise ValueError(f"missing evidence for {addr}")
        result[addr] = row
    return result


def classify(inventory: Path, graph: Path, exports: Path, seeds: Path, out: Path) -> dict:
    functions = read_rows(inventory, {"addr", "name", "size"})
    known = {}
    for row in functions:
        addr = address(row["addr"])
        if addr in known:
            raise ValueError(f"duplicate function address in inventory: {addr}")
        known[addr] = row
    if not known:
        raise ValueError("empty function inventory")

    seed_map = load_seeds(seeds)
    absent = sorted(set(seed_map) - set(known))
    if absent:
        raise ValueError(f"seed addresses absent from inventory: {', '.join(absent)}")

    indirect = []
    counts = Counter()
    for addr in sorted(known):
        sites = scan_indirect(exports, addr)
        counts[addr] = len(sites)
        indirect.extend(sites)

    classifications = []
    for addr, f in sorted(known.items()):
        seed = seed_map.get(addr, {})
        classifications.append({
            "addr": addr,
            "name": f["name"],
            "semantic_name": seed.get("semantic_name", ""),
            "size": f["size"],
            "primary_category": seed.get("category", "Unknown"),
            "confidence": seed.get("confidence", "UNKNOWN"),
            "evidence": seed.get("evidence", "No verified classification evidence"),
            "indirect_sites": counts[addr],
        })

    categories = {r["addr"]: r["primary_category"] for r in classifications}
    runtime = {"C standard runtime", "Compiler-generated support"}
    graph_rows = []
    for row in read_rows(graph, {"caller", "callee", "kind"}):
        caller, callee = address(row["caller"]), address(row["callee"])
        source, target = categories.get(caller), categories.get(callee)
        if source is None or target is None:
            scope = "unknown_endpoint"
        elif source == "Unknown" or target == "Unknown":
            scope = "unresolved_category"
        elif source in runtime or target in runtime:
            scope = "runtime_involved"
        else:
            scope = "application_to_application"
        graph_rows.append({"caller": caller, "callee": callee, "kind": row["kind"],
                           "scope": scope, "caller_category": source or "NOT_IN_INVENTORY",
                           "callee_category": target or "NOT_IN_INVENTORY"})

    libc = [{"addr": r["addr"], "candidate_name": r["semantic_name"],
             "confidence": r["confidence"], "evidence": r["evidence"]}
            for r in classifications if r["primary_category"] in runtime]

    atomic_write(out / "function_classification.csv", ["addr", "name", "semantic_name", "size", "primary_category",
                 "confidence", "evidence", "indirect_sites"], classifications)
    atomic_write(out / "libc_functions.csv", ["addr", "candidate_name", "confidence", "evidence"], libc)
    atomic_write(out / "application_call_graph.csv", ["caller", "callee", "kind", "scope",
                 "caller_category", "callee_category"], graph_rows)
    atomic_write(out / "indirect_control_flow.csv", ["function", "site", "kind", "instruction", "target"], indirect)

    summary = {
        "inventory_functions": len(classifications),
        "direct_graph_edges_preserved": len(graph_rows),
        "indirect_calls": sum(r["kind"] == "indirect_call" for r in indirect),
        "computed_jumps": sum(r["kind"] == "computed_jump" for r in indirect),
        "confidence": dict(Counter(r["confidence"] for r in classifications)),
        "primary_categories": dict(Counter(r["primary_category"] for r in classifications)),
        "edge_scopes": dict(Counter(r["scope"] for r in graph_rows)),
        "baseline_note": "Previous private report: 1273 functions, 2644 direct edges, 90 jsr and 16 computed jumps; discrepancies require review, not padding.",
    }
    path = out / "classification_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=ROOT / "out/ghidra/functions.csv")
    parser.add_argument("--graph", type=Path, default=ROOT / "out/ghidra/call_graph.csv")
    parser.add_argument("--exports", type=Path, default=ROOT / "out/ghidra/funcs")
    parser.add_argument("--seeds", type=Path, default=ROOT / "tools/analysis/classification_seeds.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "out/ghidra")
    args = parser.parse_args()
    print(json.dumps(classify(args.inventory, args.graph, args.exports, args.seeds, args.out), indent=2))


if __name__ == "__main__":
    main()
