"""Selected state observations at identical, explicitly named execution cuts.

Numeric fields are exact integers (dimensions in scaled points). Meanings,
token lists and glue are printed diagnostic projections, not token identity.
The generated observer is shared by native TeX and ContentBuilder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from .tex_trace import differences

NAME = re.compile(r"[A-Za-z][A-Za-z0-9@_:.-]*\Z")
LABEL = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
INDEXED = {"count", "dimen", "skip", "muskip", "toks", "catcode", "mathcode",
           "lccode", "uccode", "sfcode", "delcode"}
TEXTUAL = {"meaning", "toks", "skip", "muskip"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_plan(plan):
    if (not isinstance(plan.get("fields"), list) or not isinstance(plan.get("checkpoints"), list)
            or not plan["fields"] or not plan["checkpoints"]):
        raise ValueError("A checkpoint plan needs fields and an ordered checkpoint schedule")
    ids = []
    for field in plan["fields"]:
        name, kind = field["id"], field["kind"]
        if not LABEL.fullmatch(name):
            raise ValueError("Invalid field identifier")
        ids.append(name)
        if kind in INDEXED:
            index = field.get("index")
            limit = 255 if kind.endswith("code") else 32767
            if type(index) is not int or not 0 <= index <= limit:
                raise ValueError(f"Invalid index for {kind}")
        elif kind in {"meaning", "fontdimen"}:
            if not NAME.fullmatch(field.get("target", "")):
                raise ValueError("Invalid control sequence name")
            if kind == "fontdimen" and (type(field.get("index")) is not int or not 1 <= field["index"] <= 7):
                raise ValueError("Font observations are restricted to the seven standard parameters")
        else:
            raise ValueError(f"Unsupported checkpoint field kind: {kind}")
    if len(ids) != len(set(ids)):
        raise ValueError("Checkpoint field identifiers must be unique")
    if any(not isinstance(x, str) or not LABEL.fullmatch(x) for x in plan["checkpoints"]):
        raise ValueError("Invalid checkpoint label")
    return plan


def validate_basis(basis):
    files = basis.get("files")
    if (not isinstance(files, dict) or not files or basis.get("entry") not in files
            or not isinstance(basis.get("initial_state"), str) or not basis["initial_state"]
            or type(basis.get("pass")) is not int or basis["pass"] < 1
            or any(not isinstance(name, str) or not isinstance(value, str)
                   or not re.fullmatch(r"[a-f0-9]{64}", value) for name, value in files.items())):
        raise ValueError("Missing or malformed checkpoint comparison basis")


def observer_source(plan, nonce):
    """Requires ordinary braces/parameter/superscript catcodes, newlinechar=10,
    and e-TeX primitives. INITEX callers establish these in the common source.
    """
    validate_plan(plan)
    if not re.fullmatch(r"[a-f0-9]{16}", nonce):
        raise ValueError("Observer nonce must be sixteen hexadecimal characters")
    prefix = "PX" + nonce
    def message(text):
        return r"\message{^^J" + prefix + ":" + text + "^^J}"
    result = [r"\def\PyTeXMLCheckpoint#1{\csname PyTeXMLCheckpoint:#1\endcsname}"]
    for label in dict.fromkeys(plan["checkpoints"]):
        body = [message("BEGIN:" + label)]
        for field in plan["fields"]:
            kind = field["kind"]
            if kind == "meaning":
                target = field["target"]
                value = (r"\ifcsname " + target + r"\endcsname\expandafter\meaning\csname "
                         + target + r"\endcsname\else undefined\fi")
            elif kind == "fontdimen":
                value = r"\number\fontdimen" + str(field["index"]) + r"\csname " + field["target"] + r"\endcsname"
            else:
                value = (r"\the" if kind in TEXTUAL else r"\number") + "\\" + kind + str(field["index"])
            body.append(message("FIELD:" + field["id"] + ":" + value))
        body.append(message("END:" + label))
        result.append(r"\expandafter\def\csname PyTeXMLCheckpoint:" + label + r"\endcsname{" + "".join(body) + "}")
    return "\n".join(result) + "\n"


def basis_for(files, entry, *, initial_state, pass_number=1):
    """The caller names the common format/start-state contract explicitly.

    Files include authored inputs, initial auxiliaries and selected metric bytes.
    Producer/executable identities belong in receipts, not this common basis.
    """
    if not initial_state or entry not in files or pass_number < 1:
        raise ValueError("A comparison basis needs an entry, initial-state contract and positive pass")
    return {"entry": entry, "initial_state": initial_state, "pass": pass_number,
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}


def observations(lines, plan, nonce, basis, *, producer, completed=True, wrap_column=None):
    validate_plan(plan)
    validate_basis(basis)
    prefix, active, snapshots, issues, occurrences = "PX" + nonce + ":", None, [], [], {}
    fields = {f["id"]: f for f in plan["fields"]}
    for number, raw in enumerate(lines, 1):
        line = raw.rstrip("\r\n")
        if not line.startswith(prefix):
            # Tracing itself may occur between message records. Other content
            # is retained as ambiguous rather than silently joining wrapped text.
            if active is not None and line and not (line.startswith(("{", "\\", "#"))):
                issues.append({"line": number, "kind": "unframed_checkpoint_text", "raw": line})
            continue
        if wrap_column and len(line) >= wrap_column:
            issues.append({"line": number, "kind": "possibly_wrapped_value", "raw": line})
        record = line[len(prefix):]
        if record.startswith("BEGIN:"):
            label = record[6:]
            if active is not None:
                issues.append({"line": number, "kind": "nested_checkpoint"})
            occurrences[label] = occurrences.get(label, 0) + 1
            active = {"label": label, "occurrence": occurrences[label], "line": number, "fields": {}}
        elif record.startswith("FIELD:") and active is not None:
            parts = record.split(":", 2)
            if len(parts) != 3 or parts[1] not in fields or parts[1] in active["fields"]:
                issues.append({"line": number, "kind": "unexpected_or_duplicate_field", "raw": line})
                continue
            _, name, value = parts
            kind = fields[name]["kind"]
            exact = kind not in TEXTUAL
            if exact and not re.fullmatch(r"-?\d+", value):
                issues.append({"line": number, "kind": "invalid_numeric_field", "raw": line})
                continue
            active["fields"][name] = {"kind": kind, "comparison": "exact_integer" if exact else "printed_diagnostic",
                                      "value": int(value) if exact else value}
        elif record.startswith("END:") and active is not None:
            if record[4:] != active["label"] or active["fields"].keys() != fields.keys():
                issues.append({"line": number, "kind": "incomplete_checkpoint"})
            snapshots.append(active)
            active = None
        else:
            issues.append({"line": number, "kind": "unexpected_checkpoint_record", "raw": line})
    if active is not None:
        issues.append({"kind": "unterminated_checkpoint"})
    if [s["label"] for s in snapshots] != plan["checkpoints"]:
        issues.append({"kind": "checkpoint_schedule_mismatch", "expected": plan["checkpoints"]})
    if not completed:
        issues.append({"kind": "producer_incomplete"})
    return {"schema": "pytexml-checkpoints/1", "status": "complete" if not issues else "incomplete",
            "basis": basis, "selection": plan, "producer": producer, "snapshots": snapshots, "issues": issues}


def compare(left, right):
    reasons = []
    for key in ("schema", "basis", "selection"):
        if left.get(key) != right.get(key):
            reasons.append(key + "_mismatch")
    if left.get("schema") != "pytexml-checkpoints/1":
        reasons.append("unknown_schema")
    if any(r.get("status") != "complete" or not r.get("snapshots") for r in (left, right)):
        reasons.append("incomplete_observation")
    for receipt in (left, right):
        try:
            plan = validate_plan(receipt["selection"])
            selected = {f["id"]: f["kind"] for f in plan["fields"]}
            seen = {}
            if [s["label"] for s in receipt["snapshots"]] != plan["checkpoints"]:
                raise ValueError("schedule")
            validate_basis(receipt["basis"])
            if receipt.get("issues"):
                raise ValueError("unresolved issues")
            for snapshot in receipt["snapshots"]:
                label = snapshot["label"]
                seen[label] = seen.get(label, 0) + 1
                if snapshot["occurrence"] != seen[label] or snapshot["fields"].keys() != selected.keys():
                    raise ValueError("missing fields or occurrence")
                for name, field in snapshot["fields"].items():
                    exact = selected[name] not in TEXTUAL
                    if (field["kind"] != selected[name] or
                            field["comparison"] != ("exact_integer" if exact else "printed_diagnostic") or
                            type(field["value"]) is not (int if exact else str)):
                        raise ValueError("field type")
        except (KeyError, TypeError, ValueError, AttributeError):
            reasons.append("invalid_observation")
    cuts = lambda r: [(s.get("label"), s.get("occurrence")) for s in r.get("snapshots", [])]
    if not reasons and cuts(left) != cuts(right):
        reasons.append("checkpoint_identity_mismatch")
    diff = [] if reasons else differences([s["fields"] for s in left["snapshots"]],
                                          [s["fields"] for s in right["snapshots"]])
    return {"schema": "pytexml-checkpoint-comparison/1",
            "status": "not_comparable" if reasons else "mismatch" if diff else "matched",
            "reasons": reasons, "differences": diff,
            "scope": "Selected values at matched execution cuts; printed diagnostics do not establish token identity or whole-engine equivalence."}


def python_observations(sources, entry, plan, nonce, basis, *, metrics=None):
    """Source must input pytexml-observe.tex and execute the planned checkpoints."""
    from ..engine.content_builder import ContentBuilder
    if "pytexml-observe.tex" in sources:
        raise ValueError("Reserved observer filename already exists")
    for name, data in {**{k: v.encode("utf-8") for k, v in sources.items()}, **(metrics or {})}.items():
        if basis["files"].get(name, basis["files"].get("@aux/" + name)) != hashlib.sha256(data).hexdigest():
            raise ValueError(f"Python input does not match the comparison basis: {name}")
    build = ContentBuilder({**sources, "pytexml-observe.tex": observer_source(plan, nonce)},
                           **({"metrics": metrics} if metrics is not None else {})).build(entry)
    source_root = Path(__file__).resolve().parents[1]
    identity = fingerprint({p.relative_to(source_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(source_root.rglob("*.py"))})
    receipt = observations("\n".join(build.messages).splitlines(), plan, nonce, basis,
                           producer={"engine": "PyTeXML", "boundary": build.boundary,
                                     "python_version": sys.version, "source_tree_sha256": identity},
                           completed=build.status == "completed")
    return receipt


def capture_run(run):
    """Capture the first pass of a completed INITEX run in the bounded builder."""
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if manifest["mode"] != "initex" or manifest["status"] != "complete":
        raise ValueError("Python capture requires a completed explicit-source INITEX run")
    reference = json.loads((run / "probed/pass-1/checkpoints.json").read_text(encoding="utf-8"))
    sources, metrics = {}, {}
    for name in reference["basis"]["files"]:
        auxiliary = name.startswith("@aux/")
        key = name.removeprefix("@aux/")
        path = run / ("probed/pass-1/initial-aux" if auxiliary else "probed/project") / key
        if path.suffix == ".tfm":
            metrics[key] = path.read_bytes()
        elif path.suffix in {".tex", ".sty", ".cls", ".ltx", ".def", ".aux", ".bbl"}:
            sources[key] = path.read_bytes().decode("utf-8")
    return python_observations(sources, manifest["entry"], manifest["plan"], manifest["nonce"],
                               reference["basis"], metrics=metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    comparison = commands.add_parser("compare")
    comparison.add_argument("left", type=Path)
    comparison.add_argument("right", type=Path)
    comparison.add_argument("--output", type=Path, required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("run", type=Path)
    capture.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = capture_run(args.run) if args.command == "capture" else compare(
        json.loads(args.left.read_text(encoding="utf-8")), json.loads(args.right.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(receipt["status"])
    return 0 if receipt["status"] in {"matched", "complete"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
