"""Assay a pinned LuaLaTeX census against pdfLaTeX, without installing meanings."""
import argparse
from collections import Counter, defaultdict
import gc
import json
from pathlib import Path
import re
import shutil
import sys
import time
import tracemalloc

from .model import (Candidates, active_references, descriptor, exception_reason, kind,
                    layer, lexical_references, macro_parts, references)
from .native import Native, probe, sha, validate, write_json
from ..measured_prepare import peak_memory
from ..specimens import code_identity
from ...reading.contracts import ReadingIssue
from ...engine.token_text import meaning_text
from .model import check_fixtures

HERE = Path(__file__).resolve().parent


def verify_basis(oracle, inventory):
    data = json.loads(inventory.read_text(encoding="utf-8"))
    records = {row["path"]: row for row in data["files"]}
    selected = ("bin/windows/lualatex.exe", "bin/windows/pdflatex.exe",
        "texmf-var/web2c/luahbtex/lualatex.fmt", "texmf-var/web2c/pdftex/pdflatex.fmt",
        "texmf-dist/tex/latex/base/latex.ltx", "texmf-dist/tex/latex/l3kernel/expl3-code.tex")
    result = []
    for relative in selected:
        actual = sha(oracle / relative)
        if records[relative]["sha256"] != actual:
            raise ValueError(f"Pinned oracle file changed: {relative}")
        result.append({"path": relative, "sha256": actual})
    return {"inventory_sha256": sha(inventory), "selected_files": result}, records


def census(native):
    folder = native.output / "lua"
    folder.mkdir()
    for name in ("census.tex", "census.lua"):
        shutil.copyfile(HERE / name, folder / name)
    native.run("lualatex", folder, "census.tex")
    result = {}
    for line in (folder / "lua-census.tsv").read_text(encoding="ascii").splitlines():
        name, command, meaning = line.split("\t")
        name = bytes.fromhex(name).decode("utf-8")
        if name in result:
            raise ValueError("Duplicate Lua hash name")
        result[name] = {"lua_kind": command, "lua_meaning": bytes.fromhex(meaning).decode("utf-8")}
    meta = dict(line.split("\t", 1) for line in (folder / "lua-meta.tsv").read_text().splitlines())
    for key in ("format", "expl3"):
        meta[key] = bytes.fromhex(meta[key]).decode()
    # Guard against APIs returning only a macro's body, or an unexpanded query.
    for name in ("relax", "fi", "long"):
        if result[name]["lua_meaning"] != "\\" + name:
            raise ValueError(f"Lua full-meaning witness failed: {name}")
    if kind(result["seq_new:N"]["lua_meaning"]) != "macro":
        raise ValueError("Lua macro full-meaning witness failed")
    return result, meta


def source_census(oracle):
    evidence = defaultdict(set)
    for relative in ("texmf-dist/tex/latex/base/latex.ltx", "texmf-dist/tex/latex/l3kernel/expl3-code.tex"):
        # A broad supplementary vocabulary, including comments/uses. This is
        # deliberately not described as a declaration or installed-name census.
        text = (oracle / relative).read_text(encoding="utf-8")
        for name in re.findall(r"\\([A-Za-z_:@]+|[^A-Za-z_:@\s])", text):
            evidence[name].add(relative)
    return evidence


def jsonl(path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")


def validate_inputs(output, oracle, inventory):
    inputs = {}
    for fls in output.glob("*/*.fls"):
        for line in fls.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("INPUT "):
                continue
            path = Path(line[6:])
            if not path.is_absolute():
                path = fls.parent / path
            path = path.resolve()
            if path.is_relative_to(output):
                continue
            if not path.is_relative_to(oracle):
                raise ValueError(f"Native input outside oracle/assay: {path}")
            relative = path.relative_to(oracle).as_posix()
            if relative not in inputs:
                actual = sha(path)
                if relative not in inventory or actual != inventory[relative]["sha256"]:
                    raise ValueError(f"Native input does not match pin: {relative}")
                inputs[relative] = actual
    return inputs


def report(output, rows, summary, graph):
    def table(title, counts):
        return [f"## {title}", "", "| Category | Count |", "| --- | ---: |",
                *(f"| {key} | {value} |" for key, value in sorted(counts.items())), ""]
    lines = ["# Native meaning assay", "", f"Workload: {summary['workload_note']}", "",
        "[Receipt](summary.json) · [All records](meanings.jsonl) · [Exceptions](exceptions.jsonl) · "
        "[Generated fixtures](fixtures.jsonl) · [Reference graph](graph.json)", "",
        "Scope: format-start Lua hash census, supplemented by source vocabulary and pdfTeX reference discovery.",
        "Lua hash membership includes undefined entries. This does not prove an exhaustive pdfTeX hash census.",
        "Layer labels classify names, not proven source ownership. Public format names include primitives and plain-TeX names.", "",
        "Exact = first candidate reconstructed under native ifx; recovered = a later lexical regime passed.",
        "Exception = reconstruction unestablished. Non-macro meanings are inventoried separately, not macro fixtures.",
        "The graph records syntactic body references, not observed calls or sufficient intrinsic eligibility sets.",
        "Computed names, aliases used as data and state dependencies require additional evidence.", ""]
    for key, title in (("meaning_kinds", "pdfTeX meaning kinds"), ("layers", "Naming layers"),
                       ("reconstruction", "Reconstruction outcomes"), ("exception_reasons", "Exception reasons"),
                       ("engine_comparison", "Cross-engine census and display comparison")):
        lines += table(title, summary[key])
    lines += ["## Reconstruction by naming layer", "", "| Layer | Exact | Recovered | Exception | Non-macro |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, counts in sorted(summary["reconstruction_by_layer"].items()):
        lines.append(f"| {name} | {counts.get('exact', 0)} | {counts.get('recovered', 0)} | {counts.get('exception', 0)} | {counts.get('not_applicable', 0)} |")
    metrics = {k: v for k, v in summary["measurements"].items() if k != "native_processes"}
    lines += ["", "## Size and cost", "", "```json", json.dumps(metrics, indent=2), "```", "",
              "PyTeXML retained/peak allocation readings cover candidate SourceSpan/Token/StoredDefinition construction; input JSON and module imports precede tracing.",
              "Process resident peaks include the rest of the worker. Native process peaks exclude children. Profiled/traced and contended runs are not benchmarks.", "",
              "## Most referenced helpers", "", "Counts are distinct referring definitions, not execution frequency.", "",
              "| Name | Referring definitions |", "| --- | ---: |"]
    for item in graph["hubs"][:30]:
        name = item["name"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{name}` | {item['indegree']} |")
    lines += ["", "## Exceptions", "", "Every unresolved record, including its native meaning and reason, is listed individually in exceptions.jsonl.",
              "No unqualified entry is installed into the engine or exported as a successful reconstruction fixture.", ""]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def run(args):
    output, oracle = args.output.resolve(), args.oracle.resolve()
    if output.is_relative_to(oracle) or oracle.is_relative_to(output):
        raise ValueError("Assay output and oracle must be separate trees")
    started, cpu_started = time.perf_counter(), time.process_time()
    basis, inventory = verify_basis(oracle, args.inventory.resolve())
    summary = {"schema": "pytexml-meaning-assay/1", "status": "running", "basis": basis,
        "workload_note": args.workload_note, "code": code_identity(), "native_timeout_seconds": args.timeout,
        "probe_sources": {name: sha(HERE / name) for name in ("census.lua", "census.tex")}}
    write_json(output / "summary.json", summary)
    native = Native(oracle, output, args.timeout)
    rows, meta = census(native)
    summary["lua"] = {**meta, "kinds": dict(Counter(r["lua_kind"] for r in rows.values()))}
    print(f"Lua hash census: {len(rows)}", flush=True)
    sources = source_census(oracle)
    for name, origins in sources.items():
        rows.setdefault(name, {})["source_vocabulary"] = sorted(origins)
    for name, row in rows.items():
        row.update(name=name, layer=layer(name))
    targets = {}
    frontier = set(rows)
    number = 0
    while frontier:
        supported = []
        for name in sorted(frontier):
            try:
                name.encode("latin-1")
                supported.append(name)
            except UnicodeEncodeError:
                rows[name].update(kind="unrepresentable_name", reconstruction="exception", reason="outside_pdftex_name_domain")
        found = probe(native, supported, number) if supported else {}
        targets.update(found)
        new = set()
        for name, meaning in found.items():
            row = rows[name]
            row.update(meaning=meaning, kind=kind(meaning), meaning_bytes=len(meaning.encode("latin-1")))
            if "lua_meaning" in row:
                row["same_display_across_engines"] = row["lua_meaning"] == meaning
            if row["kind"] == "macro":
                new.update(lexical_references(meaning))
        frontier = new - rows.keys()
        for name in frontier:
            rows[name] = {"name": name, "layer": layer(name), "reference_discovered": True}
        print(f"pdfTeX probe {number}: {len(found)} names; {len(frontier)} new reference candidates", flush=True)
        number += 1
    summary["target_profile"] = {name: targets.get(name) for name in ("fmtversion", "ExplFileDate", "pdftexbanner")}
    for name, key in (("fmtversion", "format"), ("ExplFileDate", "expl3")):
        if macro_parts(targets[name])[2] != meta[key]:
            raise ValueError(f"Engine formats disagree on pinned {name}")
    # Export the inventory before potentially expensive reconstruction work.
    jsonl(output / "inventory.jsonl", (rows[name] for name in sorted(rows)))
    candidates = Candidates()
    outer = {name for name, meaning in targets.items() if kind(meaning) == "macro" and "outer" in macro_parts(meaning)[0]}
    accepted = {}
    macros = {name for name, row in rows.items() if row.get("kind") == "macro"}
    for regime in ("l3", "latex"):
        pending = []
        for name in sorted(macros - accepted.keys()):
            row = rows[name]
            try:
                source, definition = candidates.parse(row["meaning"], regime, f"native-assay:{name}")
                if meaning_text(definition, candidates.display_context) != row["meaning"]:
                    raise ValueError("python_meaning_display_differs")
                if outer.intersection(references(definition)):
                    raise ValueError("outer_reference_in_definition")
                flags = macro_parts(row["meaning"])[0]
                native_source = "".join("\\" + flag + " " for flag in flags) + source
                pending.append((name, native_source))
            except (ValueError, ReadingIssue) as error:
                row.setdefault("attempts", {})[regime] = f"{type(error).__name__}: {error}"
        # Bounded chunks retain useful evidence even if an individual candidate
        # violates a native constraint beyond the scanner's current vocabulary.
        for offset in range(0, len(pending), 500):
            chunk = pending[offset:offset + 500]
            outcomes = validate(native, chunk, regime, offset // 500)
            for name, outcome in outcomes.items():
                rows[name].setdefault("attempts", {})[regime] = outcome
                if outcome == "equal":
                    accepted[name] = regime
            print(f"{regime}: {min(offset + 500, len(pending))}/{len(pending)} checked; {len(accepted)} accepted", flush=True)
    gc.collect()
    tracemalloc.start()
    allocation_start, allocation_cpu = time.perf_counter(), time.process_time()
    definitions = {name: candidates.parse(rows[name]["meaning"], regime, f"native-assay:{name}")[1]
                   for name, regime in accepted.items()}
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    representation = {"definitions": len(definitions), "retained_traced_bytes": retained,
        "peak_traced_bytes": peak, "wall_seconds": time.perf_counter() - allocation_start,
        "cpu_seconds": time.process_time() - allocation_cpu, "instrumentation": "tracemalloc",
        "scope": "new PyTeXML SourceSpan/Token/StoredDefinition objects; preloaded input/module memory excluded"}
    edges, active_edges, incoming, fixtures = [], [], Counter(), []
    total_body_tokens = 0
    for name, row in rows.items():
        if name in accepted:
            definition = definitions[name]
            row.update(reconstruction="exact" if accepted[name] == "l3" else "recovered", regime=accepted[name])
            desc = descriptor(definition)
            row.update({k: v for k, v in desc.items() if k != "semantic_key"})
            total_body_tokens += desc["body_tokens"]
            refs = references(definition)
            row["computed_name_candidate"] = any(r in {"csname", "tex_csname:D", "cs:w"} or re.search(r":.*c", r) for r in refs)
            for target, count in sorted(refs.items()):
                edges.append({"source": name, "target": target, "token_occurrences": count})
                incoming[target] += 1
            for target, count in sorted(active_references(definition).items()):
                active_edges.append({"source": name, "active_character": target, "token_occurrences": count})
            fixtures.append({"schema": "pytexml-native-meaning-fixture/1", "name": name,
                "meaning": row["meaning"], "regime": accepted[name], "reconstruction": row["reconstruction"],
                "basis_inventory_sha256": basis["inventory_sha256"], **desc})
        elif row.get("kind") == "macro":
            row.update(reconstruction="exception", reason=exception_reason(row.get("attempts", {})))
        elif "reconstruction" not in row:
            row.update(reconstruction="not_applicable", reason="not_a_macro")
    graph = {"schema": "pytexml-meaning-reference-graph/1", "edge_kind": "syntactic_control_sequence_reference",
        "scope": "native-equal reconstructed macro bodies only", "edges": edges,
        "active_character_edges": active_edges,
        "limitations": "References are not calls. Parameter delimiters, computed targets, primitive state and unparsed bodies are not dependency-complete. Active-character edges are separate from control-sequence names.",
        "unparsed_macro_names": sorted(macros - accepted.keys()),
        "computed_name_candidates": sorted(name for name, r in rows.items() if r.get("computed_name_candidate")),
        "hubs": [{"name": name, "indegree": count} for name, count in incoming.most_common()]}
    by_layer = defaultdict(Counter)
    for row in rows.values():
        by_layer[row["layer"]][row["reconstruction"]] += 1
    sizes = sorted(len(d.replacement_tokens) for d in definitions.values())
    summary.update(status="complete", native_inputs=validate_inputs(output, oracle, inventory),
        total_candidates=len(rows), target_defined=sum(r.get("kind") not in {"undefined", "unrepresentable_name"} for r in rows.values()),
        meaning_kinds=dict(Counter(r.get("kind") for r in rows.values())),
        layers=dict(Counter(r["layer"] for r in rows.values())),
        reconstruction=dict(Counter(r["reconstruction"] for r in rows.values())),
        reconstruction_by_layer=dict(by_layer),
        engine_comparison={"same_display": sum(r.get("same_display_across_engines") is True for r in rows.values()),
            "different_display": sum(r.get("same_display_across_engines") is False for r in rows.values()),
            "pdf_defined_absent_from_lua_hash": sum("lua_kind" not in r and r.get("kind") not in {"undefined", "unrepresentable_name"} for r in rows.values())},
        exception_reasons=dict(Counter(r.get("reason") for r in rows.values() if r["reconstruction"] == "exception")),
        measurements={"wall_seconds": time.perf_counter() - started, "python_cpu_seconds": time.process_time() - cpu_started,
            "native_processes": native.receipts, "representation": representation,
            "native_cpu_seconds": sum(r["cpu_seconds"] for r in native.receipts) if all(r["cpu_seconds"] is not None for r in native.receipts) else None,
            "native_wall_seconds": sum(r["wall_seconds"] for r in native.receipts),
            "largest_native_peak_rss_bytes": max((r["peak_rss_bytes"] for r in native.receipts if r["peak_rss_bytes"] is not None), default=None),
            "qualified_body_size_tokens": {"min": min(sizes, default=0), "max": max(sizes, default=0),
                "median": sizes[len(sizes) // 2] if sizes else 0, "p95": sizes[int(len(sizes) * .95)] if sizes else 0},
            "qualified_body_tokens": total_body_tokens, "qualified_parameter_tokens": sum(len(d.parameter_tokens) for d in definitions.values()),
            "meaning_text_bytes": sum(r.get("meaning_bytes", 0) for r in rows.values()), **peak_memory()})
    jsonl(output / "meanings.jsonl", (rows[name] for name in sorted(rows)))
    jsonl(output / "exceptions.jsonl", (rows[name] for name in sorted(rows) if rows[name]["reconstruction"] == "exception"))
    jsonl(output / "fixtures.jsonl", fixtures)
    summary["fixture_replay_count"] = check_fixtures(output / "fixtures.jsonl")
    write_json(output / "graph.json", graph)
    summary["artifacts"] = {name: sha(output / name) for name in
        ("inventory.jsonl", "meanings.jsonl", "exceptions.jsonl", "fixtures.jsonl", "graph.json")}
    summary["measurements"].update(wall_seconds=time.perf_counter() - started,
        python_cpu_seconds=time.process_time() - cpu_started,
        wall_scope="assay_through_artifact_export_and_fixture_replay_before_final_report",
        **peak_memory())
    summary["measurements"]["memory_scope"] = "assay_python_process"
    write_json(output / "summary.json", summary)
    report(output, rows, summary, graph)
    print(json.dumps({"candidates": len(rows), "reconstruction": summary["reconstruction"], "output": str(output)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workload-note", required=True)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if not 0 < args.timeout < float("inf"):
        parser.error("timeout must be finite and positive")
    # Do this outside the failure handler: an existing receipt is immutable.
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        run(args)
    except Exception as error:
        receipt = args.output / "summary.json"
        if receipt.exists():
            failed = json.loads(receipt.read_text(encoding="utf-8"))
            failed.update(status="failed", error=f"{type(error).__name__}: {error}")
            write_json(receipt, failed)
        raise


if __name__ == "__main__":
    main()
