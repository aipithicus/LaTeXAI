"""Distinguish dump reconstruction losses from candidate display discrepancies."""
import argparse
from collections import Counter
import difflib
import json
from pathlib import Path
import time

from .__main__ import jsonl, validate_inputs, verify_basis
from .model import Candidates, macro_parts
from .native import Native, sha, validate, write_json
from ..measured_prepare import peak_memory
from ..specimens import code_identity
from ...engine.token_text import meaning_text


def differences(expected, actual):
    return [{"operation": tag, "expected_start": a, "actual_start": x,
             "expected": expected[a:b], "actual": actual[x:y]}
            for tag, a, b, x, y in difflib.SequenceMatcher(
                a=expected, b=actual, autojunk=False).get_opcodes() if tag != "equal"]


def pattern(edits):
    changed = "".join(e[side] for e in edits for side in ("expected", "actual"))
    if not changed:
        return "no_difference"
    if set(changed) <= {" "}:
        return "spaces_only"
    if set(changed) <= {"#"}:
        return "parameter_markers_only"
    return "other_text"


def conclusion(attempts):
    if not attempts:
        return "incomplete_native_comparison"
    compared = [a for a in attempts if "native_display" in a]
    if any(not a["python_matches_native_candidate"] for a in compared):
        return "candidate_display_discrepancy"
    if len(compared) != len(attempts):
        return "incomplete_native_comparison"
    return "candidate_displays_agree_reconstruction_loss"


def spacing_direction(edits):
    if pattern(edits) != "spaces_only":
        return "not_spaces_only"
    directions = {"added" if len(e["actual"]) > len(e["expected"]) else "removed" for e in edits}
    return "spaces_" + "_and_".join(sorted(directions))


def run(args):
    started, cpu = time.perf_counter(), time.process_time()
    assay, output, oracle = args.assay.resolve(), args.output.resolve(), args.oracle.resolve()
    receipt = json.loads((assay / "summary.json").read_text())
    if receipt["status"] != "complete":
        raise ValueError("Triage requires a completed assay")
    if sha(assay / "meanings.jsonl") != receipt["artifacts"]["meanings.jsonl"]:
        raise ValueError("Assay meanings changed")
    basis, inventory = verify_basis(oracle, args.inventory.resolve())
    if basis != receipt["basis"]:
        raise ValueError("Triage and original assay bases differ")
    if output.is_relative_to(oracle) or oracle.is_relative_to(output):
        raise ValueError("Triage output and oracle must be separate")
    summary = {"schema": "pytexml-meaning-display-triage/1", "status": "running",
        "source_receipt_sha256": sha(assay / "summary.json"), "basis": basis,
        "code": code_identity(), "workload_note": args.workload_note,
        "display_catcodes": {"_": 8, ":": 12, "@": 12}}
    write_json(output / "summary.json", summary)
    original = [json.loads(line) for line in (assay / "meanings.jsonl").read_text().splitlines()]
    selected = {r["name"]: r for r in original if r.get("reason") == "python_meaning_display_differs"}
    candidates = Candidates()
    if any(candidates.display_context.catcodes[ch] != cat for ch, cat in summary["display_catcodes"].items()):
        raise ValueError("Python display context differs from native probe")
    native = Native(oracle, output, args.timeout)
    records = {name: {"name": name, "layer": row["layer"], "target_meaning": row["meaning"], "attempts": []}
               for name, row in selected.items()}
    for regime in ("l3", "latex"):
        pending, attempts = [], {}
        for name, row in selected.items():
            if "python_meaning_display_differs" not in row["attempts"].get(regime, ""):
                continue
            source, definition = candidates.parse(row["meaning"], regime, "triage:" + name)
            actual = meaning_text(definition, candidates.display_context)
            edits = differences(row["meaning"], actual)
            attempt = {"regime": regime, "python_display": actual,
                       "diff_pattern": pattern(edits), "diffs": edits}
            records[name]["attempts"].append(attempt)
            attempts[name] = attempt
            flags = macro_parts(row["meaning"])[0]
            pending.append((name, "".join("\\" + flag + " " for flag in flags) + source))
        for offset in range(0, len(pending), 500):
            displays = {}
            outcomes = validate(native, pending[offset:offset + 500], regime, offset // 500,
                                candidate_displays=displays)
            for name, outcome in outcomes.items():
                attempt = attempts[name]
                attempt["native_target_ifx"] = outcome
                if name in displays:
                    attempt["native_display"] = displays[name]
                    attempt["python_matches_native_candidate"] = attempt["python_display"] == displays[name]
                    attempt["candidate_diffs"] = differences(displays[name], attempt["python_display"])
            print(f"{regime}: {min(offset + 500, len(pending))}/{len(pending)} candidate displays checked", flush=True)
    for record in records.values():
        record["conclusion"] = conclusion(record["attempts"])
        record["first_attempt_pattern"] = record["attempts"][0]["diff_pattern"]
        record["first_attempt_spacing"] = spacing_direction(record["attempts"][0]["diffs"])
    values = list(records.values())
    attempts = [a for r in values for a in r["attempts"]]
    jsonl(output / "records.jsonl", values)
    summary.update(status="complete", names=len(values), candidate_attempts=len(attempts),
        name_conclusions=dict(Counter(r["conclusion"] for r in values)),
        first_attempt_patterns=dict(Counter(r["first_attempt_pattern"] for r in values)),
        first_attempt_spacing=dict(Counter(r["first_attempt_spacing"] for r in values)),
        native_candidate_outcomes=dict(Counter(a["native_target_ifx"] for a in attempts)),
        python_native_candidate_matches=sum(a.get("python_matches_native_candidate") is True for a in attempts),
        native_inputs=validate_inputs(output, oracle, inventory),
        artifacts={"records.jsonl": sha(output / "records.jsonl")},
        measurements={"wall_seconds": time.perf_counter() - started,
            "python_cpu_seconds": time.process_time() - cpu, "native_processes": native.receipts,
            "native_cpu_seconds": sum(r["cpu_seconds"] for r in native.receipts)
                if all(r["cpu_seconds"] is not None for r in native.receipts) else None,
            **peak_memory()})
    summary["measurements"]["memory_scope"] = "triage_python_process"
    write_json(output / "summary.json", summary)
    lines = ["# Native meaning display triage", "", f"Names: {len(values)}; candidate attempts: {len(attempts)}.", "",
        "Compare Python's display with native TeX's display of the same candidate, separately from the original target meaning.",
        "A discrepancy in the latter alone does not identify a formatter bug. Native equality remains an independent gate.", "",
        "```json", json.dumps({k: summary[k] for k in ("name_conclusions", "first_attempt_patterns", "first_attempt_spacing", "native_candidate_outcomes", "python_native_candidate_matches")}, indent=2), "```", "",
        "[Every case and diff](records.jsonl) · [Basis, inputs and cost receipt](summary.json)", "",
        f"Workload: {args.workload_note}", ""]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({k: summary[k] for k in ("names", "candidate_attempts", "name_conclusions", "first_attempt_patterns")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assay", "oracle", "inventory", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--workload-note", required=True)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if not 0 < args.timeout < float("inf"):
        parser.error("timeout must be finite and positive")
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        run(args)
    except Exception as error:
        path = args.output / "summary.json"
        failed = json.loads(path.read_text()) if path.exists() else {"schema": "pytexml-meaning-display-triage/1"}
        failed.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(path, failed)
        raise


if __name__ == "__main__":
    main()
