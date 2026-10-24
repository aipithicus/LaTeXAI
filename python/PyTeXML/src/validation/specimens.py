"""Named specimen batches: source identities, prepared checkpoints and navigation.

This development harness calls the public preparation/rendering entry points.
It supplies no discovery or interpretation behavior of its own.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from ..source_io import SourceStore
from ..yaml_io import load_mapping

PROJECT = Path(__file__).resolve().parents[2]
SCHEMA = "pytexml-specimen-batch/1"
SHARED_SUFFIXES = {".svg", ".bib", ".bbl", ".sty", ".cls"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    devices = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
               *(f"LPT{i}" for i in range(1, 10))}
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value) \
            or value.endswith(".") or value.split(".")[0].upper() in devices:
        raise ValueError(f"Invalid specimen/run identifier: {value!r}")
    return value


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(root, files):
    records = [{"path": p.relative_to(root).as_posix(), "sha256": digest(p),
                "bytes": p.stat().st_size} for p in sorted(files)]
    identity = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    return {"sha256": identity, "files": records}


def source_fingerprint(source):
    store = SourceStore(source)
    return fingerprint(store.root, store.files)


def code_identity():
    files = list((PROJECT / "src").rglob("*.py")) + list((PROJECT / "resources").rglob("*.yaml"))
    files.append(PROJECT / "requirements.txt")
    result = fingerprint(PROJECT, files)
    result["python"] = sys.version
    result["dependencies"] = {name: importlib.metadata.version(name) for name in ("PyYAML", "Pillow", "PyMuPDF")}
    for key, args in (("commit", ["rev-parse", "HEAD"]),
                      ("working_changes", ["status", "--porcelain", "--", "src", "resources", "requirements.txt"])):
        try:
            proc = subprocess.run(["git", "-C", str(PROJECT), *args], capture_output=True,
                                  text=True, timeout=10, check=True)
            result[key] = proc.stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            result[key] = None
            result.setdefault("diagnostics", []).append(str(error))
    return result


def load_catalog(path):
    path = Path(path).resolve()
    data = load_mapping(path)
    if set(data) != {"schema", "specimens"} or data["schema"] != "pytexml-specimens/1":
        raise ValueError("Expected pytexml-specimens/1 with a specimens mapping")
    if not isinstance(data["specimens"], dict) or not data["specimens"]:
        raise ValueError("Catalog needs at least one specimen")
    result = {}
    for name, record in data["specimens"].items():
        identifier(name)
        if name.casefold() in {key.casefold() for key in result}:
            raise ValueError(f"Specimen identifiers must be distinct on case-insensitive filesystems: {name}")
        if not isinstance(record, dict) or set(record) != {"title", "source", "main"}:
            raise ValueError(f"{name}: expected title, source and main")
        if any(not isinstance(v, str) or not v.strip() for v in record.values()):
            raise ValueError(f"{name}: catalog fields must be nonempty strings")
        source = (path.parent / record["source"]).resolve()
        main = (source / record["main"]).resolve()
        if not source.is_relative_to(path.parent) or source == path.parent:
            raise ValueError(f"{name}: source must be beneath the catalog directory")
        if not source.is_dir() or not main.is_relative_to(source) or not main.is_file() or main.suffix != ".tex":
            raise ValueError(f"{name}: main must be an existing TeX file inside the source directory")
        result[name] = {**record, "source": str(source), "main": main.relative_to(source).as_posix()}
    return result


def batch_records(runs):
    records = []
    for path in runs.glob("*/run.json"):
        data = read_json(path)
        if data.get("schema") != SCHEMA or data.get("name") != path.parent.name:
            raise ValueError(f"Unrecognized batch record: {path}")
        records.append(data)
    return sorted(records, key=lambda r: (r["started"], r["name"]))


def md(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def refresh_index(runs):
    """Rebuild navigational views from receipts; preserve user NOTES.md files."""
    records = batch_records(runs)
    latest = {}
    for batch in records:
        name = batch["name"]
        lines = [f"# {name}", "", batch["note"], "",
                 f"Batch status: **{batch['status']}**. Started: {batch['started']}.", "",
                 f"Code commit: `{batch['code']['commit']}`. Code fingerprint: `{batch['code']['sha256']}`.", "",
                 "[Receipt](run.json) · [Investigation notes](NOTES.md)", "",
                 "| Specimen | Preparation | Master | SVGs | Bibliography items | Requirements: prep / binding / interpretation | Evidence |",
                 "| --- | --- | --- | ---: | ---: | --- | --- |"]
        renders = []
        for specimen, item in batch["results"].items():
            latest[specimen] = (name, item)
            summary = item.get("summary", {})
            req = summary.get("requirements", {})
            counts = " / ".join(str(req.get(k, 0)) for k in ("preparation", "binding", "interpretation"))
            master = f"[master.tex]({specimen}/prepared/master.tex)" if item.get("master") else "—"
            evidence = f"[result]({specimen}/result.json) · [log]({specimen}/console.log)"
            if item.get("changes"):
                evidence += f" · [changes]({specimen}/changes.json)"
            if (runs / name / specimen / "master.diff").is_file():
                evidence += f" · [master diff]({specimen}/master.diff)"
            lines.append(f"| {specimen} — {md(item['title'])} | {item['status']} | {master} | "
                         f"{summary.get('svg_assets', '—')} | {summary.get('bibitems', '—')} | {counts} | {evidence} |")
            for render in sorted((runs / name / specimen / "renders").glob("*/comparison.json")):
                receipt = read_json(render)
                relative = render.parent.relative_to(runs / name).as_posix()
                renders.append(f"Render `{specimen}/{render.parent.name}`: **{receipt['status']}** — "
                               f"[report]({relative}/comparison.json).")
        if renders:
            lines += ["", *renders]
        lines += ["", "Partial means a master was emitted with outstanding preparation requirements; it is not a failed run.",
                  "Requirement counts are occurrences, not independent bugs. Rendering is separate evidence.", ""]
        (runs / name / "README.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    lines = ["# Specimen iterations", "", "Latest attempt for each specimen (including failures):", "",
             "| Specimen | Latest batch | Preparation |", "| --- | --- | --- |"]
    for specimen, (name, item) in sorted(latest.items()):
        lines.append(f"| {specimen} — {md(item['title'])} | [{name}]({name}/README.md) | {item['status']} |")
    lines += ["", "## All batches", "", "| Batch | Status | Purpose |", "| --- | --- | --- |"]
    for batch in reversed(records):
        lines.append(f"| [{batch['name']}]({batch['name']}/README.md) | {batch['status']} | {md(batch['note'])} |")
    lines += ["", "Inputs stay in the specimen catalog's source directories. Each named batch is a retained checkpoint.",
              "Identical generated resource files share read-only hard links within this run collection. Do not edit them in place.",
              "Masters, manifests, provenance and logs are separate per iteration. NOTES.md is for investigation notes.", ""]
    (runs / "INDEX.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def share_resources(prepared, runs):
    """Deduplicate generated resources only; never hard-link original inputs."""
    pool = runs / "resources"
    pool.mkdir(exist_ok=True)
    shared = {"reused_files": 0, "reused_bytes": 0, "new_bytes": 0}
    for path in sorted(prepared.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SHARED_SUFFIXES:
            continue
        sha = digest(path)
        target = pool / (sha + path.suffix.lower())
        size = path.stat().st_size
        if target.exists():
            if digest(target) != sha:
                raise ValueError(f"Shared resource changed: {target.name}")
            temporary = path.with_name(path.name + ".link")
            try:
                os.link(target, temporary)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            shared["reused_files"] += 1
            shared["reused_bytes"] += size
        else:
            os.link(path, target)
            shared["new_bytes"] += size
        # On Windows this protects all links to the generated resource. Source
        # assets and master.tex are never linked into this pool.
        target.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    return shared


def summarize(prepared):
    manifest_path = prepared / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    master = prepared / "master.tex"
    text = master.read_text(encoding="utf-8") if master.is_file() else ""
    return {"preparation_status": manifest.get("preparation_status", "failed"),
            "master_characters": len(text), "svg_assets": len(list(prepared.rglob("*.svg"))),
            # The preparation reader owns bibliography syntax and validation;
            # a raw bibitem search misses package-specific entry commands.
            "bibitems": manifest.get("bibliography", {}).get("citations_count", 0),
            "requirements": dict(Counter(r["stage"] for r in manifest.get("requirements", []))),
            "unresolved": len(manifest.get("unresolved", [])),
            "source_reads": len(manifest.get("source_reads", [])),
            "source_dependency_closure": manifest.get("source_dependency_closure", "unresolved")}


def record_changes(runs, batch, specimen, item, previous):
    if not previous:
        return
    prior_name, prior = previous
    old = {r["path"]: r["sha256"] for r in prior.get("outputs", {}).get("files", [])}
    new = {r["path"]: r["sha256"] for r in item["outputs"]["files"]}
    item["changes"] = {"previous_batch": prior_name,
                       "same_source": prior.get("source_fingerprint", {}).get("sha256") == item["source_fingerprint"]["sha256"],
                       "added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
                       "changed": sorted(p for p in old.keys() & new.keys() if old[p] != new[p]),
                       "previous_summary": prior.get("summary"), "current_summary": item["summary"]}
    folder = runs / batch / specimen
    write_json(folder / "changes.json", item["changes"])
    old_master = runs / prior_name / specimen / "prepared/master.tex"
    new_master = folder / "prepared/master.tex"
    if old_master.is_file() and new_master.is_file():
        diff = difflib.unified_diff(old_master.read_text(encoding="utf-8").splitlines(keepends=True),
                                   new_master.read_text(encoding="utf-8").splitlines(keepends=True),
                                   fromfile=f"{prior_name}/master.tex", tofile=f"{batch}/master.tex")
        (folder / "master.diff").write_text("".join(diff), encoding="utf-8", newline="\n")


def run_batch(catalog, runs, name, note, selected=(), timeout=180):
    catalog, runs = Path(catalog).resolve(), Path(runs).resolve()
    identifier(name)
    if name.casefold() == "resources":
        raise ValueError("resources is reserved for shared generated assets")
    if not note.strip() or not 0 < timeout < float("inf"):
        raise ValueError("A purpose note and finite positive timeout are required")
    specimens = load_catalog(catalog)
    chosen = list(selected) or list(specimens)
    if len(set(chosen)) != len(chosen) or any(s not in specimens for s in chosen):
        raise ValueError("Select distinct specimen identifiers from the catalog")
    for record in specimens.values():
        source = Path(record["source"])
        if source.is_relative_to(runs) or runs.is_relative_to(source):
            raise ValueError("Run collection must be separate from source trees")
    previous = {}
    for old in batch_records(runs):
        for specimen, item in old["results"].items():
            previous[specimen] = (old["name"], item)
    batch_dir = runs / name
    batch_dir.mkdir(parents=True, exist_ok=False)
    batch = {"schema": SCHEMA, "name": name, "note": note, "started": utc_now(), "status": "running",
             "catalog": str(catalog), "catalog_sha256": digest(catalog), "code": code_identity(),
             "selected": chosen, "timeout_seconds": timeout, "results": {}}
    (batch_dir / "NOTES.md").write_text(f"# Investigation notes\n\nPurpose: {note}\n\n", encoding="utf-8", newline="\n")
    try:
        write_json(batch_dir / "run.json", batch)
        refresh_index(runs)
        for specimen in chosen:
            record = specimens[specimen]
            folder = batch_dir / specimen
            folder.mkdir()
            prepared = folder / "prepared"
            item = {**record, "status": "failed", "master": False, "started": utc_now()}
            batch["results"][specimen] = item
            try:
                item["source_fingerprint"] = source_fingerprint(Path(record["source"]))
                with (folder / "console.log").open("wb") as log:
                    proc = subprocess.run([sys.executable, "-B", "-m", "src.prepare.pipeline",
                        record["source"], str(prepared), record["main"]], cwd=PROJECT,
                        stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
                item["returncode"] = proc.returncode
                item["summary"] = summarize(prepared)
                item["master"] = (prepared / "master.tex").is_file()
                if proc.returncode == 0 and item["master"] and item["summary"]["preparation_status"] in {"partial", "complete"}:
                    item["status"] = item["summary"]["preparation_status"]
                else:
                    item["error"] = "Preparation did not publish a successful master; inspect console.log and preparation.log"
                item["storage"] = share_resources(prepared, runs)
                item["outputs"] = fingerprint(prepared, (p for p in prepared.rglob("*") if p.is_file()))
                record_changes(runs, name, specimen, item, previous.get(specimen))
            except subprocess.TimeoutExpired:
                item.update(status="timeout", error=f"Preparation exceeded {timeout:g} seconds")
            except Exception as error:
                item.update(status="failed", error=f"{type(error).__name__}: {error}")
            finally:
                item["finished"] = utc_now()
                write_json(folder / "result.json", item)
                write_json(batch_dir / "run.json", batch)
                refresh_index(runs)
            print(f"{name}/{specimen}: {item['status']}", flush=True)
        batch["status"] = "finished" if all(r["status"] in {"partial", "complete"} for r in batch["results"].values()) else "finished_with_failures"
    finally:
        if batch["status"] == "running":
            batch["status"] = "interrupted"
        batch["finished"] = utc_now()
        write_json(batch_dir / "run.json", batch)
        refresh_index(runs)
    return batch


def render_specimen(runs, batch_name, specimen, render_name, config):
    from .render import render_comparison

    runs = Path(runs).resolve()
    for value in (batch_name, specimen, render_name):
        identifier(value)
    batch = read_json(runs / batch_name / "run.json")
    item = batch["results"][specimen]
    if item["status"] not in {"partial", "complete"} or not item["master"]:
        raise ValueError("This attempt has no successfully prepared master")
    source = Path(item["source"])
    if source_fingerprint(source)["sha256"] != item["source_fingerprint"]["sha256"]:
        raise ValueError("Original source changed since this batch; create a new iteration before comparing")
    folder = runs / batch_name / specimen
    if fingerprint(folder / "prepared", (p for p in (folder / "prepared").rglob("*") if p.is_file()))["sha256"] != item["outputs"]["sha256"]:
        raise ValueError("Prepared checkpoint changed; create a new iteration before comparing")
    result = render_comparison(source, item["main"], folder / "prepared", folder / "renders" / render_name, config)
    refresh_index(runs)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True, help="Run collection outside all source trees")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--catalog", type=Path, required=True)
    run.add_argument("--name", required=True)
    run.add_argument("--note", required=True)
    run.add_argument("--specimen", action="append", default=[])
    run.add_argument("--timeout", type=float, default=180)
    commands.add_parser("index")
    render = commands.add_parser("render")
    render.add_argument("--batch", required=True)
    render.add_argument("--specimen", required=True)
    render.add_argument("--name", required=True)
    render.add_argument("--tectonic", type=Path, required=True)
    render.add_argument("--timeout", type=float, default=120)
    render.add_argument("--bundle")
    render.add_argument("--allow-downloads", action="store_true")
    fonts = render.add_mutually_exclusive_group()
    fonts.add_argument("--fontconfig", type=Path)
    fonts.add_argument("--font-dir", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.command == "run":
        result = run_batch(args.catalog, args.runs, args.name, args.note, args.specimen, args.timeout)
        return 0 if result["status"] == "finished" else 1
    if args.command == "render":
        from .render import RenderConfig
        result = render_specimen(args.runs, args.batch, args.specimen, args.name,
            RenderConfig(args.tectonic, args.timeout, args.bundle, not args.allow_downloads,
                         args.fontconfig, tuple(args.font_dir)))
        return 0 if result["status"] == "rendered" else 1
    refresh_index(args.runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
