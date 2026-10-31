"""Streaming phase counts of observed TeX command reports, not all execution."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

REPORT = re.compile(r"\{(?:([^{}]+ mode): )?(.+)\}\Z")
PRIMITIVE = re.compile(r"\\([A-Za-z]+)(.*)\Z")
BLIND_SPOTS = ["Token-list scanners can expand primitives without command reports (including the inside message).",
              "Loaded format construction is not replayed by a document run; profile it in a separate INITEX run.",
              "Observer setup and checkpoint boundary commands can contribute reports outside the excluded observer intervals.",
              "Counts describe this run and trace settings; absent reports do not prove absent execution."]


def profile(lines, *, nonce, checkpoints, completed=True, wrap_column=10000):
    prefix = "PX" + nonce + ":"
    phase, observer, cuts = "startup", None, []
    counts, operands, other = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    issues, excluded, line_count, issue_count = [], 0, 0, 0
    def issue(record):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < 30:
            issues.append(record)
    for line_count, raw in enumerate(lines, 1):
        line = raw.rstrip("\r\n")
        if line.startswith(prefix + "BEGIN:"):
            if observer is not None:
                issue({"line": line_count, "kind": "nested_phase_marker"})
            observer = line[len(prefix + "BEGIN:"):]
        elif line.startswith(prefix + "END:"):
            label = line[len(prefix + "END:"):]
            if observer != label:
                issue({"line": line_count, "kind": "unmatched_phase_marker"})
            cuts.append(label)
            phase, observer = label, None
        elif line.startswith(prefix):
            continue
        elif match := REPORT.fullmatch(line):
            if observer is not None:
                excluded += 1
                continue
            command = match[2]
            if command in {"true", "false"}:
                other[phase]["conditional_outcome:" + command] += 1
            elif primitive := PRIMITIVE.fullmatch(command):
                counts[phase][primitive[1]] += 1
                operands[phase][command] += 1
            else:
                other[phase][command] += 1
        elif line.startswith("{"):
            issue({"line": line_count, "kind": "unparsed_report", "raw": line})
        if wrap_column and len(line) >= wrap_column:
            issue({"line": line_count, "kind": "possibly_wrapped_record", "raw": line})
    if observer is not None or cuts != checkpoints:
        issue({"kind": "incomplete_phase_schedule", "expected": checkpoints, "observed": cuts})
    if not completed:
        issue({"kind": "producer_incomplete"})
    from ..engine.catalog import COMMON_PRIMITIVES, EXTENSIONS
    registry = {**COMMON_PRIMITIVES, **EXTENSIONS}
    seen = sorted({name for counter in counts.values() for name in counter})
    return {"schema": "pytexml-phase-profile/1", "status": "complete" if not issues else "incomplete",
            "counts": {p: dict(c) for p, c in counts.items()},
            "operand_reports": {p: dict(c) for p, c in operands.items()},
            "other_reports": {p: dict(c) for p, c in other.items()},
            "catalog": {name: {"registered": name in registry} for name in seen},
            "issues": issues, "issue_count": issue_count, "lines_read": line_count, "excluded_observer_reports": excluded,
            "blind_spots": BLIND_SPOTS, "scope": "Observed command/operand reports; catalog presence is not semantic qualification."}


def lexical_candidates(paths, names):
    """Raw lexical candidates include comments, definitions and dead branches."""
    counts, unavailable = Counter(), []
    selected = set(names)
    for path in sorted(set(map(Path, paths))):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            unavailable.append({"path": str(path), "error": str(error)})
            continue
        counts.update(name for name in re.findall(r"\\([A-Za-z]+)", text) if name in selected)
    return {"counts": dict(counts), "unavailable": unavailable,
            "scope": "Lexical candidate occurrences, including comments and unexecuted definitions; aliases, generated names and catcodes are unresolved."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    with args.log.open(encoding="utf-8", errors="replace") as lines:
        receipt = profile(lines, nonce=manifest["nonce"], checkpoints=manifest["plan"]["checkpoints"],
                          completed=manifest["status"] == "complete")
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(receipt["status"])
    return 0 if receipt["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
