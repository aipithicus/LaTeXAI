"""Pinned native comparisons for atlas programs; explicit gaps are not passes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from .behavioral_atlas import PROJECT, CATALOG, load, excerpt, digest
from .meaning_assay.native import Native, sha, write_json
from .meaning_assay.__main__ import verify_basis, validate_inputs
from .meaning_assay.model import Candidates, descriptor, macro_parts
from .measured_prepare import peak_memory
from .specimens import code_identity

FIXTURE = PROJECT / "tests/fixtures/engine/atlas-native"
PIN = PROJECT / "recipes/oracle-pins/root-a-pdftex-20261029.json"
REFERENCE = FIXTURE / "native-reference.json"


def inputs(case):
    atlas = load()
    settings = json.loads((FIXTURE / "cases.json").read_text())[case]
    if "fragment" in settings:
        source = excerpt(atlas, settings["fragment"])
        provenance = {"source_fragment": atlas["fragments"][settings["fragment"]],
                      "source_file": atlas["sources"][atlas["fragments"][settings["fragment"]]["source"]]}
    else:
        source = (FIXTURE / settings["source"]).read_bytes()
        provenance = {"derived_witness": settings["source"], "parent": settings["parent"]}
    probe = (FIXTURE / settings["probe"]).read_bytes()
    identity = {"catalog_sha256": sha(CATALOG), "cases_sha256": sha(FIXTURE / "cases.json"),
                **provenance,
                "definition_sha256": digest(source), "probe_sha256": digest(probe)}
    return settings, source.decode("ascii"), probe.decode("ascii"), identity


def python_case(case):
    from ..bindings.resolver import BindingResolver
    from ..engine.programs import evaluate, expand_call, SETUP, HOOK_BODY, ProgramBudget
    from ..engine.token_text import meaning_text
    from ..reading.context import ReaderContext
    from ..reading.contracts import ReadingBoundary, DeferredRegion, ReadingIssue, SourceCommand, SourceEnd
    from ..reading.dispatcher import StructuralDispatcher
    from ..reading.tex_reader import TexReader

    class StrictSourceDispatcher(StructuralDispatcher):
        # Preparation's setup_request deliberately turns an execution failure
        # into deferred source. A differential witness needs the original cause.
        # Use the same expansion/evaluation operations with no fallback binding.
        def _dispatch_event(self, event, reader, context, token, meaning, definition):
            if definition is not None:
                invocation = expand_call(self, event, definition)
                evaluate(self, invocation.argument("body").tokens, invocation.span, policy=SETUP)
                return SourceCommand(invocation.span, token.value, "reading_noop")
            return super()._dispatch_event(event, reader, context, token, meaning, definition)

    settings, source, probe, identity = inputs(case)
    resolver = BindingResolver(engine_profile="pdftex")
    baseline = resolver.new_context().baseline
    context = ReaderContext(baseline=baseline, primitive_initial_state=True)
    reader = TexReader(source, source_id=f"atlas:{case}:definitions", catcodes=context.catcodes,
                       endline_char=context.endlinechar)
    # program=True is reserved for frozen token streams: prefixed operations
    # may collect their remaining tokens there. Physical input must remain lazy.
    host = StrictSourceDispatcher(reader, context, resolver, preparation=True, source_commands=True)
    host.program_budget = ProgramBudget(100000)
    host.program_policy = SETUP
    result = {"case": case, "identity": identity, "status": "incomplete", "phase": "definitions", "trace": {}}
    try:
        # Pull physical characters incrementally: P03 changes the mouth's state.
        while (item := host.next_item()) is not None:
            host.program_budget.charge()
            if isinstance(item, SourceEnd):
                continue
            if isinstance(item, (ReadingBoundary, DeferredRegion)):
                result["boundary"] = {"source": item.span.basis.source_id,
                                      "start": item.span.start, "end": item.span.end}
                raise ReadingIssue(item.reason, item.detail)
            if isinstance(item, SourceCommand) and item.action == "program_expand":
                evaluate(host, item.argument("body").tokens, item.span, policy=SETUP)
            else:
                # Preserve paragraph events from blank source lines. Rendering
                # them is not part of the definition/trace comparison.
                HOOK_BODY.accept(item, host)
        if host._groups or host._conditionals:
            raise ReadingIssue("atlas_definition_boundary", "Definition fragment left open groups/conditionals")
        result["phase"] = "probe"
        probe_reader = TexReader(probe, source_id=f"atlas:{case}:probe", catcodes=context.catcodes,
                                endline_char=context.endlinechar)
        # Probes keep the entry character regime. Real rescanning still goes
        # through the engine's scantokens operation, never through this harness.
        evaluate(host, tuple(probe_reader), probe_reader.basis.whole, policy=SETUP)
        result["status"] = "completed"
    except ReadingIssue as error:
        result.update(status="blocked", reason=error.reason, detail=error.detail)
    for label in settings["trace_labels"]:
        definition = context.lookup_definition("AtlasTrace" + label)
        if definition is not None:
            result["trace"][label] = "".join(token.value for token in definition.replacement_tokens)
    definition = context.lookup_definition(settings["target"]) if settings.get("target") else None
    result["target"] = None if definition is None else {
        "meaning": meaning_text(definition, context), **descriptor(definition)}
    result["installed_definitions"] = sorted(name for name in context.meaning_names()
                                              if context.lookup_definition(name) is not None)
    result["remaining_budget"] = host.program_budget.remaining
    return result


def native_text(settings, source, probe, candidate=None):
    # Instrumentation is outside the original definitions; it never supplies a
    # missing program helper. Trace definitions are the same in both engines.
    head = (r"\newwrite\AtlasOut\immediate\openout\AtlasOut=trace.tsv" + "\n"
            + r"\escapechar=92\newlinechar=-1" + "\n"
            + r"\ifdefined\AtlasUndefined\errmessage{AtlasUndefined already defined}\fi" + "\n")
    tail = ""
    for label in settings["trace_labels"]:
        tail += r"\immediate\write\AtlasOut{" + label + r"|\pdfescapehex{\AtlasTrace" + label + "}}\n"
    if candidate is not None:
        tail += (r"\begingroup\catcode32=10\catcode58=12\catcode95=8\catcode64=11\endlinechar=-1\relax" + "\n"
                 + candidate + "\n" + r"\expandafter\ifx\csname " + settings["target"]
                 + r"\endcsname\AssayCandidate\immediate\write\AtlasOut{IFX|31}"
                 + r"\else\immediate\write\AtlasOut{IFX|30}\fi\endgroup" + "\n")
    tail += r"\immediate\closeout\AtlasOut\csname @@end\endcsname" + "\n"
    return head + source + "\n" + probe + "\n" + tail


def native_case(native, case):
    settings, source, probe, identity = inputs(case)
    records = []
    candidate = None
    reference = None
    for attempt in range(2):
        folder = native.output / f"{case}-native-{attempt}"
        folder.mkdir()
        text = native_text(settings, source, probe, candidate)
        (folder / "probe.tex").write_text(text, encoding="ascii", newline="\n")
        code = native.run("pdflatex", folder, "probe.tex", allow_failure=True)
        trace = {}
        if (folder / "trace.tsv").exists():
            for line in (folder / "trace.tsv").read_text(encoding="ascii").splitlines():
                key, value = line.split("|", 1)
                if key in trace:
                    raise ValueError(f"Duplicate native observation: {case}:{key}")
                trace[key] = bytes.fromhex(value).decode("latin-1")
        records.append({"folder": folder.name, "probe_sha256": sha(folder / "probe.tex"),
                        "returncode": code, "trace": trace})
        if code or set(trace) != set(settings["trace_labels"]) | ({"IFX"} if candidate else set()):
            return {"case": case, "identity": identity, "status": "native_failed", "runs": records}
        if attempt == 0 and settings.get("target"):
            try:
                candidate, parsed = Candidates().parse(trace["A"], "latex", f"native:{case}")
                flags, _, _ = macro_parts(trace["A"])
                candidate = "".join("\\" + flag for flag in flags) + candidate
                reference = descriptor(parsed)
            except Exception as error:
                return {"case": case, "identity": identity, "status": "trace_only", "runs": records,
                        "reconstruction_error": f"{type(error).__name__}: {error}"}
        elif attempt and {key: value for key, value in trace.items() if key != "IFX"} != records[0]["trace"]:
            raise ValueError(f"Native replay observations changed: {case}")
    qualified = not settings.get("target") or trace["IFX"] == "1"
    return {"case": case, "identity": identity, "status": "qualified" if qualified else "trace_only",
            "trace": records[0]["trace"], "target": reference if qualified else None, "runs": records}


def compare(native, python):
    if native["identity"] != python["identity"]:
        raise ValueError("Native/Python source identity mismatch")
    if native["status"] != "qualified":
        return {"status": "native_not_qualified"}
    trace = {label: "missing" if label not in python["trace"] else
             "match" if python["trace"][label] == value else "mismatch"
             for label, value in native["trace"].items()}
    target = "not_requested" if native["target"] is None else "missing" if python["target"] is None else (
        "match" if python["target"]["semantic_key"] == native["target"]["semantic_key"] else "mismatch")
    return {"status": "match" if python["status"] == "completed" and target in {"match", "not_requested"}
            and all(value == "match" for value in trace.values()) else "not_qualified",
            "target": target, "observations": trace}


def load_reference(path=REFERENCE):
    """Validate captured observations without installing them as engine state."""
    data = json.loads(path.read_text(encoding="utf-8"))
    pin = json.loads(PIN.read_text())
    if data["schema"] != "pytexml-atlas-native-reference/1":
        raise ValueError("Unknown atlas reference schema")
    if data["basis"]["inventory_sha256"] != pin["archive"]["inventory_sha256"]:
        raise ValueError("Reference basis differs from tracked pin")
    selected = {row["path"]: row["sha256"] for row in data["basis"]["selected_files"]}
    pinned = {row["path"]: row["sha256"] for row in pin["selected_files"]}
    for name in ("bin/windows/pdflatex.exe", "texmf-var/web2c/pdftex/pdflatex.fmt",
                 "texmf-dist/tex/latex/base/latex.ltx", "texmf-dist/tex/latex/l3kernel/expl3-code.tex"):
        if selected.get(name) != pinned[name]:
            raise ValueError(f"Reference basis file differs: {name}")
    cases = json.loads((FIXTURE / "cases.json").read_text())
    if set(data["cases"]) != set(cases):
        raise ValueError("Reference case set differs")
    for case, row in data["cases"].items():
        settings, source, probe, identity = inputs(case)
        if row["identity"] != identity:
            raise ValueError(f"Reference source identity differs: {case}")
        if row["status"] != "qualified" or len(row["runs"]) != 2:
            raise ValueError(f"Unqualified native reference: {case}")
        if set(row["trace"]) != set(settings["trace_labels"]):
            raise ValueError(f"Incomplete native trace: {case}")
        candidate = None
        if settings.get("target"):
            candidate, parsed = Candidates().parse(row["trace"]["A"], "latex", f"reference:{case}")
            flags, _, _ = macro_parts(row["trace"]["A"])
            candidate = "".join("\\" + flag for flag in flags) + candidate
            if descriptor(parsed) != row["target"]:
                raise ValueError(f"Reference typed descriptor differs: {case}")
        elif row["target"] is not None:
            raise ValueError(f"Unexpected typed reference: {case}")
        for attempt, run in enumerate(row["runs"]):
            expected = {**row["trace"], **({"IFX": "1"} if attempt and candidate else {})}
            text = native_text(settings, source, probe, candidate if attempt else None)
            if (run["returncode"] or run["trace"] != expected
                    or run["probe_sha256"] != digest(text.encode("ascii"))):
                raise ValueError(f"Unqualified native replay: {case}:{attempt}")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--workload-note", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    cases = json.loads((FIXTURE / "cases.json").read_text())
    parser.add_argument("--worker", choices=tuple(cases))
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    if args.worker:
        result = python_case(args.worker)
        result.update(wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                      workload_note=args.workload_note, **peak_memory())
        result["memory_scope"] = "fresh_python_case_process_including_imports"
        result["timing_scope"] = "case_execution_after_runner_imports"
        write_json(args.output, result)
        return 0
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "pytexml-atlas-native-run/1", "status": "failed", "cases": {},
              "workload_note": args.workload_note, "code": code_identity()}
    try:
        if not args.oracle or not args.inventory:
            raise ValueError("Native run requires --oracle and --inventory")
        if sha(args.inventory) != json.loads(PIN.read_text())["archive"]["inventory_sha256"]:
            raise ValueError("Oracle inventory differs from tracked pin")
        result["basis"], inventory = verify_basis(args.oracle, args.inventory)
        native = Native(args.oracle.resolve(), args.output, args.timeout)
        for case in cases:
            native_result = native_case(native, case)
            result["cases"][case] = {"native": native_result}
            path = args.output / f"{case}-python.json"
            command = [sys.executable, "-B", "-m", "src.validation.atlas_native", "--worker", case,
                       "--output", str(path), "--workload-note", args.workload_note]
            with (args.output / f"{case}-python.log").open("wb") as log:
                subprocess.run(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT,
                               timeout=args.timeout, check=True)
            python_result = json.loads(path.read_text())
            result["cases"][case] = {"native": native_result, "python": python_result,
                                    "comparison": compare(native_result, python_result)}
        result["native_inputs"] = validate_inputs(args.output, args.oracle.resolve(), inventory)
        if result["code"]["sha256"] != code_identity()["sha256"]:
            raise ValueError("Engine source changed during qualification")
        result["status"] = "completed"  # completion does not mean every comparison passed
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    result["native_processes"] = native.receipts if "native" in locals() else []
    result.update(wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                  **peak_memory())
    result["memory_scope"] = "orchestrator_process_excludes_case_workers"
    result["timing_scope"] = "orchestration_after_runner_imports_cpu_excludes_children"
    write_json(args.output / "summary.json", result)
    if result["status"] == "completed" and all(row["native"]["status"] == "qualified"
                                               for row in result["cases"].values()):
        write_json(args.output / "native-reference.json", {
            "schema": "pytexml-atlas-native-reference/1", "basis": result["basis"],
            "native_inputs": result["native_inputs"], "code": result["code"],
            "run_receipt_sha256": sha(args.output / "summary.json"),
            "cases": {case: row["native"] for case, row in result["cases"].items()}})
    print(json.dumps({"status": result["status"], "error": result.get("error"), "cases": {
        key: {"native": row["native"]["status"], "python": row.get("python", {}).get("status"),
              "reason": row.get("python", {}).get("reason"), "comparison": row.get("comparison")}
        for key, row in result["cases"].items()}}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
