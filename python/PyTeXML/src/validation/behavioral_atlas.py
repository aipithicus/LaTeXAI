"""Verify a source-backed research atlas and optionally exercise its bounded checks.

Catalog integrity, supporting Python checks and original-fixture qualification
are separate observations. No LaTeXML golden is installed as engine behavior.
"""
import argparse
import ast
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest

from .measured_prepare import peak_memory

PROJECT = Path(__file__).resolve().parents[2]
REPOSITORY = PROJECT.parents[1]
CATALOG = PROJECT / "recipes/behavioral-atlas/catalog.json"
FAMILIES = {"spacing", "meaning", "parameters"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def owned_path(root, name):
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Reference outside repository: {name}")
    return path


def verify(data, root=REPOSITORY):
    if data.get("schema") != "pytexml-behavioral-atlas/1":
        raise ValueError("Unknown behavioral atlas schema")
    sources, fragments = data["sources"], data["fragments"]
    raw = {}
    for key, row in sources.items():
        raw[key] = owned_path(root, row["path"]).read_bytes()
        if digest(raw[key]) != row["sha256"]:
            raise ValueError(f"Source drift: {key}")
    for key, row in fragments.items():
        content = raw[row["source"]]
        start, end = row["byte_start"], row["byte_end"]
        if not 0 <= start < end <= len(content):
            raise ValueError(f"Invalid byte range: {key}")
        if digest(content[start:end]) != row["sha256"]:
            raise ValueError(f"Fragment drift: {key}")
    checks = data["checks"]
    for key, row in checks.items():
        path = owned_path(root, row["path"])
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls, method = row["test"].split(".")
        if not any(isinstance(node, ast.ClassDef) and node.name == cls and
                   any(isinstance(child, ast.FunctionDef) and child.name == method for child in node.body)
                   for node in tree.body):
            raise ValueError(f"Missing Python check: {key}")
    seen = set()
    for row in data["cases"]:
        key = row["id"]
        if key in seen:
            raise ValueError(f"Duplicate case: {key}")
        seen.add(key)
        if row["family"] not in FAMILIES:
            raise ValueError(f"Unknown family: {key}")
        for field in ("title", "mechanisms", "prerequisites", "observations", "limits", "staged_experiment"):
            if not row.get(field):
                raise ValueError(f"Missing {field}: {key}")
        if row["qualification"] != {"original_fixture": "not_run", "native": "not_run", "staged_resolver": "proposed"}:
            raise ValueError(f"Qualification needs a separate run receipt: {key}")
        if not row["fragments"]:
            raise ValueError(f"Unlocated case: {key}")
        for reference in row["fragments"]:
            if reference not in fragments:
                raise ValueError(f"Unknown fragment: {reference}")
        for check in row["checks"]:
            if check not in checks:
                raise ValueError(f"Unknown check: {check}")
        for observation in row["observations"]:
            if observation["authority"] not in {"fixture_intent", "latexml_golden", "proposed_assertion"}:
                raise ValueError(f"Unsupported observation authority: {key}")
            if not observation["claim"] or not observation["evidence"]:
                raise ValueError(f"Unlocated observation: {key}")
            if any(reference not in fragments for reference in observation["evidence"]):
                raise ValueError(f"Unknown observation evidence: {key}")
    if not seen:
        raise ValueError("Empty behavioral atlas")
    return raw


def load(path=CATALOG, root=REPOSITORY):
    data = json.loads(path.read_text(encoding="utf-8"))
    verify(data, root)
    return data


def excerpt(data, name, root=REPOSITORY):
    row = data["fragments"][name]
    source = data["sources"][row["source"]]
    raw = owned_path(root, source["path"]).read_bytes()
    if digest(raw) != source["sha256"]:
        raise ValueError(f"Source drift: {name}")
    part = raw[row["byte_start"]:row["byte_end"]]
    if digest(part) != row["sha256"]:
        raise ValueError(f"Fragment drift: {name}")
    return part


def exercise(data, cases):
    """Run only explicitly mapped supporting checks; never arbitrary case text."""
    records = []
    for key in sorted({key for case in cases for key in case["checks"]}):
        check = data["checks"][key]
        path = owned_path(REPOSITORY, check["path"])
        name = "_atlas_" + path.stem
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls, method = check["test"].split(".")
        suite = unittest.TestSuite([getattr(module, cls)(method)])
        result = unittest.TestResult()
        started, cpu = time.perf_counter(), time.process_time()
        suite.run(result)
        record = {"check": key, "test_source_sha256": digest(path.read_bytes()),
                  "status": "failed" if result.errors or result.failures or result.unexpectedSuccesses else
                            "not_qualified" if result.skipped or result.expectedFailures else "passed",
                  "tests_run": result.testsRun, "wall_seconds": time.perf_counter() - started,
                  "cpu_seconds": time.process_time() - cpu,
                  "errors": [message for _, message in result.errors + result.failures],
                  "skips": [message for _, message in result.skipped],
                  "expected_failures": [message for _, message in result.expectedFailures],
                  **peak_memory()}
        record["memory_scope"] = "atlas_process_lifetime_high_water_after_check_not_check_allocation"
        records.append(record)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(FAMILIES))
    parser.add_argument("--mechanism")
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument("--output", required=True, type=Path, help="New JSON receipt; never overwrite")
    parser.add_argument("--workload-note", required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the receipt before starting work. Failed verification retains evidence.
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        started, cpu = time.perf_counter(), time.process_time()
        report = {"schema": "pytexml-behavioral-atlas-run/1", "workload_note": args.workload_note,
                  "catalog_sha256": digest(CATALOG.read_bytes()), "python": sys.version,
                  "status": "failed", "checks": [], "instrumentation": "clock_and_process_counters_only"}
        try:
            data = load()
            cases = [row for row in data["cases"] if
                     (not args.family or row["family"] == args.family) and
                     (not args.mechanism or args.mechanism in row["mechanisms"])]
            if not cases:
                raise ValueError("Selection matches no cases")
            report.update(source_snapshot=data["source_snapshot"], sources=data["sources"],
                          cases=[row["id"] for row in cases],
                          families=dict(Counter(row["family"] for row in cases)),
                          original_fixtures="not_run", native="not_run", staged_resolver="not_run")
            if args.exercise:
                report["checks"] = exercise(data, cases)
            from .specimens import code_identity
            report["code"] = code_identity()
            report["status"] = "catalog_verified" if all(
                row["status"] == "passed" for row in report["checks"]) else "checks_not_qualified"
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
        report.update(wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                      **peak_memory())
        report["memory_scope"] = "atlas_process_lifetime_not_sum_of_check_peaks"
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: report.get(key) for key in
                     ("status", "cases", "families", "checks", "wall_seconds", "cpu_seconds", "peak_rss_bytes")}))
    if "error" in report:
        print(report["error"], file=sys.stderr)
    return 0 if report["status"] == "catalog_verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
