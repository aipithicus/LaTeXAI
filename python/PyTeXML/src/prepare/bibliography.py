"""Native bibliography formatting driven by established traversal commands."""
from __future__ import annotations
from pathlib import Path
from dataclasses import replace
import re
from ..bibtex import Database, BibTeXError, BibTeXConflictError
from ..reading.edit_map import EditMap
from ..reading.tex_reader import TexReader, ReadEvent, TokenKind
from ..reading.dispatcher import StructuralDispatcher
from ..reading.contracts import SourceCommand, SourceEnd, ReadingBoundary, DeferredRegion, ReadingIssue
from .emission import SourcePiece
from .citations import discover_citations


class BibliographyPreparationError(ValueError):
    pass


def _preserve_declarations(pieces, session, command, reason, detail):
    session.diagnose(command.span, reason, detail)
    # A traversed BBL must not remain alongside the original declaration if
    # formatting is deferred. Undo that insertion, retaining the request.
    inserted = {p.key for p in session.bibliography_pieces or ()}
    session.bibliography_pieces = None
    return [p for p in pieces if p.key not in inserted]


def prepare_bibliography(pieces, session, output_dir: Path):
    manifest, store = session.manifest, session.store
    declarations = [p for p in pieces if p.command and p.command.action == "bibliography"]
    if manifest.bibliography.kind == "BIBLATEX":
        command = next(c for c in session.commands if c.action in {"biblatex_resource", "biblatex_print"})
        return _preserve_declarations(pieces, session, command, "bibliography_formatter",
            "Biblatex formatting is not implemented; bibliography source declarations are preserved")
    if not declarations:
        return pieces
    if len(declarations) != 1:
        # The traversal inserts at the first site only. Later requests remain
        # located and intact without retracting the already assembled first BBL.
        declarations = declarations[:1]
    declaration = declarations[0]
    command = declaration.command
    existing = Path(manifest.bibliography.bbl_path) if manifest.bibliography.bbl_path else None
    origin = store.root / command.span.basis.source_id
    resources = []
    try:
        names = command.value("names").split(",")
    except ReadingIssue as error:
        return _preserve_declarations(pieces, session, command, error.reason, error.detail)
    for name in names:
        target = name.strip()
        if not target.endswith(".bib"):
            target += ".bib"
        path = next((p for d in dict.fromkeys([session.root.parent, store.root, origin.parent])
                     if store.contains(p := (d / target).resolve())), None)
        if path is None:
            manifest.bibliography.missing_bib_files.append(target)
            if existing:
                continue
            raise BibliographyPreparationError(f"Bibliography resource not found: {target} (from {origin})")
        if path not in resources:
            resources.append(path)
            session.edge(command, path, "bibliography")
    manifest.bibliography.bib_files = [session.name(p) for p in resources]
    texts = [store.document(path).text for path in resources]
    canonical = "\n".join(text.rstrip() + "\n" for text in texts)
    selection = discover_citations(pieces, session)
    keys = selection.keys
    if existing:
        bbl = ''.join(p.text for p in session.bibliography_pieces or ())
        commands = [p.command for p in session.bibliography_pieces or () if p.command]
        backend = "existing-bbl"
    else:
        database = Database()
        try:
            for resource, text in zip(resources, texts):
                database.read(text, str(resource))
            # An inactive provider supplies only a candidate meaning. A missing
            # candidate record is a diagnostic, not a proven missing citation.
            absent_candidates = {key for key in keys if key != "*" and key not in database.entries
                                 and key not in selection.established_keys}
            for key in sorted(absent_candidates):
                database.diagnostics.append(f"Unconfirmed citation key {key!r} has no bibliography record; binding activation remains pending")
            keys = [key for key in keys if key not in absent_candidates]
            # Only explicit wildcard citations select all entries. Uncertain
            # discovery retains the whole database for later enrichment instead.
            bbl = extraction_bbl(database, keys)
        except BibTeXConflictError as error:
            # Preserve every variant in one payload resource. Choosing a winner
            # is semantic resolution, not a reason to discard the prepared master.
            (output_dir / "bibliography.bib").write_text(canonical, encoding="utf-8", newline="\n")
            info = manifest.bibliography
            info.canonical_bib = "bibliography.bib"
            info.preparation_backend = "deferred-conflict"
            info.preparation_warnings = database.diagnostics
            retained = _preserve_declarations(pieces, session, command, "bibliography_conflict", str(error))
            arg = command.argument("names")
            return [piece.edit_source(arg.span, "bibliography", "REBASE_BIBLIOGRAPHY") if piece is declaration else piece
                    for piece in retained]
        except BibTeXError as error:
            raise BibliographyPreparationError(str(error)) from error
        backend = "native-bibtex"
        manifest.bibliography.preparation_warnings = database.diagnostics
        # The formatter knows the emitted envelope and selected keys. Missing
        # reading knowledge about field values cannot veto that serialization.
        entry_keys = {entry.key for entry in database.selected(keys)}
        basis = _audit_generated(bbl, session)
    if existing:
        environments = {c.action for c in commands if c.metadata.get("bibliography")}
        if not {"environment_begin", "environment_end"} <= environments:
            raise BibliographyPreparationError("Prepared .bbl does not contain a complete thebibliography environment")
        entry_keys = {c.value(c.metadata["bibliography_key"]) for c in commands if c.metadata.get("bibliography_key")}
    missing = [key for key in keys if key != "*" and key not in entry_keys
               and key in selection.established_keys]
    if missing:
        raise BibliographyPreparationError("Bibliography entries missing for citation keys: " + ", ".join(missing))
    if existing:
        for key in keys:
            if key != "*" and key not in entry_keys and key not in selection.established_keys:
                manifest.bibliography.preparation_warnings.append(
                    f"Unconfirmed citation key {key!r} has no formatted bibliography entry; binding activation remains pending")
    if canonical:
        (output_dir / "bibliography.bib").write_text(canonical, encoding="utf-8", newline="\n")
    (output_dir / "bibliography.bbl").write_text(bbl, encoding="utf-8", newline="\n")
    info = manifest.bibliography
    info.prepared_bbl = "bibliography.bbl"
    info.canonical_bib = "bibliography.bib" if canonical else None
    info.preparation_backend = backend
    info.bbl_needed = False
    info.citations_count = len(entry_keys)
    inserted = {p.key for p in session.bibliography_pieces or ()}
    result = []
    for piece in pieces:
        if piece is declaration:
            if not existing:
                result.append(SourcePiece(bbl, basis.whole, 1, "SPLICE_BIB",
                    source_end_line=1 + len(re.findall(r"\r\n|\r|\n", bbl.rstrip("\r\n"))),
                    mapping=EditMap.copied(basis.whole), replaces=declaration.replaces + (command.span,)))
        elif piece.command and piece.command.action == "bibliography_style":
            session._omit(piece.span, "Bibliography style superseded by prepared bibliography")
        else:
            result.append(replace(piece, replaces=piece.replaces + (command.span,)) if piece.key in inserted else piece)
    return result


def _audit_generated(text, session):
    """Audit generated TeX values for unresolved reading, without vetoing output.

    Existing BBLs run at their input position in the document traversal. Native
    formatting happens later, so new effects/dependencies cannot be executed here
    and retroactively applied to the already-read manuscript.
    """
    context = session.bibliography_context.copy()
    reader = TexReader(text, source_id="bibliography.bbl", catcodes=context.catcodes,
                       endline_char=context.endlinechar, occurrence_id=len(session.manifest.input_occurrences))
    session.generated_sources[reader.basis] = text
    session.manifest.input_occurrences.append({"id": reader.basis.occurrence_id, "source": "bibliography.bbl",
                                              "parent": None, "generated": True})
    dispatcher = StructuralDispatcher(reader, context, session.bibliography_knowledge,
        source_commands=True, preparation=True, units=session.units)
    def report(span, reason, detail, *, preparation=False, unit_id=None, parent_id=None):
        if preparation:
            location = session.diagnose(span, "bibliography_reading", detail, unit_id=unit_id)
            session.manifest.bibliography.preparation_warnings.append(
                f"bibliography.bbl:{location['line']} ({span.start}:{span.end}): {detail}")
        else:
            session.require(span, reason, detail, unit_id=unit_id, parent_id=parent_id)

    def inspect_tokens(tokens, *, reported_start=None, parent_id=None):
        for token in tokens:
            if token.kind != TokenKind.CONTROL_SEQUENCE:
                continue
            profile = session.bibliography_knowledge.resolve_command(token.value)
            action = getattr(profile, "action", None)
            if action not in (None, "opaque"):
                report(token.span, "deferred_dependency", f"Generated field contains {token.value!r} ({action}) requiring resolution",
                       preparation=True, parent_id=parent_id)
            elif not getattr(profile, "family", None) and token.span.start != reported_start:
                report(token.span, "unknown_construct", f"Generated field retains unexpanded {token.value!r}", parent_id=parent_id)

    for item in dispatcher:
        if isinstance(item, ReadingBoundary):
            report(item.span, item.reason, item.detail, preparation=True, unit_id=item.unit_id)
        if isinstance(item, DeferredRegion):
            report(item.span, item.reason, item.detail, preparation=item.reason == "package_not_loaded", unit_id=item.unit_id)
            inspect_tokens(item.tokens, reported_start=item.span.start, parent_id=item.unit_id)
            continue
        if isinstance(item, SourceCommand):
            if item.action not in {"opaque", "environment_begin", "environment_end"}:
                report(item.span, item.action, f"Generated bibliography contains {item.action} requiring resolution", preparation=True, unit_id=item.unit_id)
            inspect_tokens((t for arg in item.arguments for t in arg.tokens), parent_id=item.unit_id)
        elif not isinstance(item, (ReadEvent, SourceEnd, ReadingBoundary)):
            report(item.span, "generated_structure", "Generated bibliography contains a definition or literal requiring earlier resolution", preparation=True, unit_id=item.unit_id)
        elif isinstance(item, ReadEvent) and item.token and item.token.kind == TokenKind.CONTROL_SEQUENCE:
            # Explicit control sequences are routed as SourceCommands above;
            # an implicit paragraph token is safe. Effects/conditionals are not.
            if item.token.value != "par":
                report(item.span, "reading_effect", "Generated bibliography changes reading state", preparation=True)
    return reader.basis


def extraction_bbl(database: Database, keys: list[str]) -> str:
    """Serialize keyed, field-labelled content; no publisher-style emulation."""
    entries = database.selected(keys)
    lines = [value.resolve() for value in database.preambles]
    lines.append(r"\begin{thebibliography}{" + str(max(1, len(entries))) + "}")
    for entry in entries:
        if re.search(r"[\\{}%#\s]", entry.key):
            raise BibTeXError(f"Cannot emit nonliteral bibliography key {entry.key!r}")
        lines.append(r"\bibitem{" + entry.key + "}")
        lines.append(r"\textbf{entrytype}: " + _label(entry.kind) + r"\par")
        for name, field_value in entry.fields:
            value = field_value.resolve()
            # Bibliographic data preserves raw URL/identifier characters.
            # Other values remain TeX source, including grouping and math.
            if name in ("url", "doi", "eprint") and "\\" not in value:
                value = r"\url{" + value + "}"
            lines.append(r"\textbf{" + _label(name) + "}: {" + value + r"}\par")
    lines.append(r"\end{thebibliography}")
    return "\n".join(lines) + "\n"


def _label(text: str) -> str:
    # Labels are data, never field-supplied TeX commands.
    return "".join("\\" + ch if ch in "_&#%${}" else
                   r"\textasciitilde{}" if ch == "~" else
                   r"\textasciicircum{}" if ch == "^" else ch for ch in text)
