"""Retain source dependencies without claiming that their contents executed.

The traversal and whole-source survey supply captured headers. This layer only
resolves literal paths and retains needed text; it never searches raw TeX with a
second parser, copies original image assets, or changes activity decisions.
"""
from pathlib import Path

from ..reading.contracts import ReadingIssue
from ..source_io import SourceDecodingError
from .records import source_reference


def retain_candidate_input(session, command, owner, requirement):
    if command is None or command.action != "source_input":
        return
    try:
        name = command.value("target")
        path = session.resolve(name, [""] if Path(name).suffix else [".tex", ""],
                               command.span, provisional=True)
        retain_source(session, path, import_dir=session.frames[-1].import_dir)
    except (ReadingIssue, SourceDecodingError, OSError) as error:
        requirement["detail"] += f" Retention unresolved: {error}"
        return  # The existing dependency obligation still owns this unresolved request.
    requirement["materialization"] = "prepared"
    session.manifest.candidate_dependencies.append({
        **source_reference(session.units.records[command.unit_id]),
        "kind": "input", "context_span": [owner.start, owner.end],
        "context": "retained_argument", "basis": "entry_reading_and_search_state",
        "status": "prepared", "target": session.name(path), "payload": session.name(path)})


def retain_source(session, path, *, import_dir=None):
    if session.name(path) == "master.tex":
        raise ReadingIssue("payload_collision", "Retained source conflicts with the prepared master.tex")
    session.store.document(path)  # Decode now, through the shared cache.
    if path not in session.styles:
        session.code.add(path)
    session.candidate_sources.add(path)
    session.retained_search_dirs.setdefault(path, set()).add(import_dir or session.root.parent)


def retain_survey_inputs(session):
    """Close literal source-file references in retained files using survey facts.

    These remain candidate edges under the survey's explicit entry assumptions.
    Missing/computed paths stay obligations, not guessed dependencies. Retention
    uses a visited worklist so repeated inputs and source cycles add no copies.
    """
    reports = {report["source"]: report for report in session.manifest.source_survey}
    pending = [(path, 0, directory) for path in session.code | set(session.styles)
               for directory in session.retained_search_dirs.get(path, (session.root.parent,))]
    pending.extend((session.store.root / span["source"], span["start"], session.root.parent)
                   for span in session.manifest.preserved_source_spans)
    seen = set()
    while pending:
        path, start, search_dir = pending.pop()
        if (path, start, search_dir) in seen:
            continue
        seen.add((path, start, search_dir))
        report = reports.get(session.name(path), {})
        for command in report.get("commands", ()):
            if (command.get("action") != "source_input" or command["start"] < start
                    or command.get("context") == "excluded_tail"):
                continue
            name = command.get("arguments", {}).get("target", {}).get("literal")
            if not name or Path(name).is_absolute():
                continue
            matches = []
            for directory in dict.fromkeys((search_dir, session.store.root)):
                matches = [candidate.resolve() for suffix in ([""] if Path(name).suffix else [".tex", ""])
                           if session.store.contains(candidate := directory / (name + suffix))]
                if matches:
                    break
            if len(matches) != 1:
                continue
            target = matches[0]
            try:
                retain_source(session, target, import_dir=search_dir)
            except (ReadingIssue, SourceDecodingError, OSError):
                continue
            command["retained_payload"] = session.name(target)
            pending.append((target, 0, search_dir))
