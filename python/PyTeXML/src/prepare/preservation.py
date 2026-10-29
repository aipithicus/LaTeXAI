"""Retain source dependencies without claiming that their contents executed.

The traversal and whole-source survey supply captured headers. This layer only
resolves literal paths and retains needed text; it never searches raw TeX with a
second parser, copies original image assets, or changes activity decisions.
"""
from pathlib import Path

from ..reading.contracts import ReadingIssue
from ..source_io import SourceDecodingError
from .records import source_reference


def _literal_match(session, name, suffixes, directories):
    if not name or Path(name).is_absolute():
        return None
    for directory in dict.fromkeys(directories):
        matches = [candidate.resolve() for suffix in suffixes
                   if session.store.contains(candidate := directory / (name + suffix))]
        if matches:
            return matches[0] if len(matches) == 1 else None
    return None


# Captured operand grammars, not raw-text recognition. A bibliography style is
# also a resource when the original declaration survives for a later BibTeX run.
RESOURCE_ARGUMENTS = {
    "bibliography": ("names", ".bib", "bibliography", True),
    "biblatex_resource": ("name", ".bib", "bibliography", False),
    "bibliography_style": ("name", ".bst", "bibliography_style", False),
    "external_literal": ("target", "", "external_literal", False),
}


def _retain_resources(session, command):
    """Retain candidate resources at the names used by the residual program.

    Survey evidence remains in the survey, separate from reached dependency
    edges and canonical bibliography products. The BBL belongs to the selected
    root job, regardless of the child containing the bibliography declaration.
    """
    action = command.get("action")
    requests = []
    if action in RESOURCE_ARGUMENTS:
        argument, extension, kind, multiple = RESOURCE_ARGUMENTS[action]
        literal = command.get("arguments", {}).get(argument, {}).get("literal")
        if literal is None:
            requests.append((kind, None, None, None))
        else:
            for name in literal.split(",") if multiple else (literal,):
                name = name.strip()
                target = name if not extension or name.endswith(extension) else name + extension
                path = _literal_match(session, target, ("",), (session.root.parent, session.store.root))
                requests.append((kind, name, path, Path(target).as_posix()))
    if action in {"bibliography", "biblatex_print"}:
        bbl = session.root.with_suffix(".bbl")
        requests.append(("formatted_bibliography", session.name(bbl),
                         bbl if session.store.contains(bbl) else None, "master.bbl"))
    retained = []
    for kind, name, path, payload in requests:
        record = {"kind": kind, "requested": name, "activity": "unresolved",
                  "basis": "independent_entry_profile", "status": "unresolved"}
        command.setdefault("retained_resources", []).append(record)
        if path is None:
            record["reason"] = "computed_resource" if name is None else "resource_not_in_inventory"
            continue
        # Publication must remain inside the payload. No absolute or escaping
        # residual reference is silently assigned a different meaning.
        if Path(payload).is_absolute() or ".." in Path(payload).parts:
            record["reason"] = "resource_relocation"
            continue
        try:
            session.store.document(path)
        except (SourceDecodingError, OSError) as error:
            record.update(reason="resource_reading", detail=str(error))
            continue
        previous = session.retained_resources.get(payload)
        if previous is not None and previous != path:
            raise ValueError(f"Conflicting retained resources at {payload}: {previous} and {path}")
        session.retained_resources[payload] = path
        session.candidate_sources.add(path)
        record.update(status="prepared", target=session.name(path), payload=payload)
        retained.append(path)
    return retained


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
    """Close literal source and resource references using survey facts.

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
            if (command["start"] < start
                    or command.get("context") == "excluded_tail"):
                continue
            for resource in _retain_resources(session, command):
                pending.append((resource, 0, session.root.parent))
            if command.get("action") not in {"source_input", "optional_source_input"}:
                continue
            name = command.get("arguments", {}).get("target", {}).get("literal")
            if not name or Path(name).is_absolute():
                continue
            target = _literal_match(session, name, ("",) if Path(name).suffix else (".tex", ""),
                                    (search_dir, session.store.root))
            if target is None:
                continue
            try:
                retain_source(session, target, import_dir=search_dir)
            except (ReadingIssue, SourceDecodingError, OSError):
                continue
            command["retained_payload"] = session.name(target)
            pending.append((target, 0, search_dir))
