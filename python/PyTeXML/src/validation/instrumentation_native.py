"""Qualify reusable probe tools against explicit native executables."""
import argparse
import json
from pathlib import Path

from .checkpoint_state import compare, python_observations
from .local_measurement import FIXTURES
from .probe_runner import run_probe, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "inputs"
    inputs.mkdir()
    fixture = FIXTURES / "instrumentation"
    for path in (fixture / "initex").iterdir():
        (inputs / path.name).write_bytes(path.read_bytes())
    metric = (FIXTURES / "cmr10.tfm").read_bytes()
    (inputs / "cmr10.tfm").write_bytes(metric)
    plan = json.loads((inputs / "plan.json").read_text())
    native = run_probe(inputs, "main.tex", args.bin / "pdftex.exe", output / "initex", plan,
                       mode="initex", initial_state="initex-explicit-cmr10-selected-state-v1", parse_trace=True)
    matched = {"status": "not_comparable", "reasons": ["native_incomplete"]}
    if native["status"] == "complete":
        reference = json.loads((output / "initex/probed/pass-1/checkpoints.json").read_text())
        python = python_observations({"main.tex": (inputs / "main.tex").read_text()}, "main.tex", plan,
                                     native["nonce"], reference["basis"], metrics={"cmr10.tfm": metric})
        write_json(output / "python-checkpoints.json", python)
        matched = compare(reference, python)
    write_json(output / "comparison.json", matched)
    latex = run_probe(fixture / "latex", "main.tex", args.bin / "pdflatex.exe", output / "latex",
                      json.loads((fixture / "latex/plan.json").read_text()), passes=2,
                      initial_state="native-pdflatex-format-selected-state-v1", parse_trace=True)
    lists = run_probe(fixture / "lists", "main.tex", args.bin / "pdftex.exe", output / "lists",
                      {"checkpoints": ["before", "after"], "fields": [{"id": "count", "kind": "count", "index": 20}]},
                      mode="initex", initial_state="native-initex-list-printer-v1", expected_ok=2, parse_trace=True)
    branches = set()
    if lists["status"] == "complete":
        trace = json.loads((output / "lists/probed/pass-1/trace.json").read_text())
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node["children"])
        branches = {n["path"] for dump in trace["lists"] + trace["boxes"] for n in walk(dump["nodes"])}
    list_paths_matched = {"D", "T", "S", "s", ".\\", "./", "^", "_", ".", ".|"} <= branches
    receipt = {"schema": "pytexml-instrumentation-qualification/1",
               "status": "matched" if native["status"] == latex["status"] == lists["status"] == "complete" and matched["status"] == "matched" and list_paths_matched else "incomplete",
               "native": native["status"], "checkpoints": matched, "latex": latex["status"],
               "native_lists": {"status": lists["status"], "paths": sorted(branches), "paths_matched": list_paths_matched},
               "latex_noninterference": latex.get("noninterference")}
    write_json(output / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
