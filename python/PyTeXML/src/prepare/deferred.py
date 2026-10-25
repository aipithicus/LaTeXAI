"""Materialize bounded dependency observations without executing their region."""
from dataclasses import replace
from pathlib import Path

from ..reading.contracts import ReadingIssue, ConditionalRegion, DeferredRegion, ReadingBoundary, SourceCommand
from ..bindings.resolver import BindingResolver
from ..reading.dispatcher import StructuralDispatcher
from ..reading.tex_reader import TexReader, InvalidCharacterError, CatCode
from ..source_io import SourceDecodingError
from .assets import observe_environment_assets


def emit_observed_region(session, region, *, chain=()):
    """Keep unresolved wrappers and exact source around admitted dependencies.

    Candidate files use the shared byte cache, independent reader contexts and
    occurrence identities. They are not active dependency edges. Unsupported
    candidates retain their input command; they do not stop the containing file.
    """
    references = observe_environment_assets(session, region)
    observed = [o.command for o in region.observations
                if o.command.action in {"asset_reference", "source_input", "bibliography", "bibliography_style"}]
    session._deferred_dependencies(region.tokens, observed=observed, parent_id=region.unit_id,
                                   observations=region.observations,
                                   role="branch" if isinstance(region, ConditionalRegion) else "unknown")
    cursor = region.span.start
    search_changed = False

    def emit_slice(end):
        nonlocal cursor
        span = region.span.basis.span(cursor, end)
        refs = tuple((c, p) for c, p in references if cursor <= c.span.start and c.span.end <= end)
        session._emit(span, operation="DEFER_INTERPRETATION", deferred=region, image_references=refs)
        cursor = end

    for observation in region.observations:
        command = observation.command
        if command.action in {"asset_search_paths", "asset_extensions"}:
            search_changed = True
        if command.action == "bibliography_style":
            emit_slice(command.span.start)
            session._emit(command.span, command=command, deferred=observation)
            cursor = command.span.end
            continue
        if command.action == "bibliography":
            emit_slice(command.span.start)
            emit_bibliography(session, observation, region)
            cursor = command.span.end
            continue
        if command.action != "source_input":
            continue
        record = {"source": command.span.basis.source_id, "occurrence": command.span.basis.occurrence_id,
            "start": command.span.start, "end": command.span.end, "kind": "input",
            "context_span": [region.span.start, region.span.end], "context": region.reason,
            "basis": "entry_reading_and_search_state", "binding": observation.binding_id,
            "unit_id": command.unit_id, "status": "unresolved"}
        session.manifest.candidate_dependencies.append(record)
        try:
            if search_changed:
                raise ReadingIssue("input_search_context", "An unexecuted search declaration precedes this candidate input")
            target = command.value("target")
            path = session.resolve(target, [""] if Path(target).suffix else [".tex", ""], command.span, provisional=True)
            record["target"] = session.name(path)
            if path.suffix.lower() in {".sty", ".cls"}:
                raise ReadingIssue("retained_code_input", "Local package/class code requires a retained payload contract")
            if path in chain or any(frame.path == path for frame in session.frames):
                raise ReadingIssue("input_cycle", "Conditional candidate input forms a source cycle")
            doc = session.store.document(path)
            context = session.context.copy()
            reader = TexReader(doc.text, source_id=doc.name, occurrence_id=len(session.manifest.input_occurrences),
                               catcodes=context.catcodes, endline_char=context.endlinechar)
            observer = StructuralDispatcher(reader, context, session.resolver,
                preparation=True, source_commands=True, units=session.units)
            captured, changed = observer.observe_conditional_input()
        except (ReadingIssue, SourceDecodingError, OSError, InvalidCharacterError) as error:
            reason = getattr(error, "reason", "conditional_input")
            record["reason"] = reason
            session.require(command.span, reason, str(error), stage="preparation", unit_id=command.unit_id,
                            dependency="possible", next_step="resource_resolution")
            continue
        session.register_reader(path, reader, candidate=True, parent=command.span.basis.occurrence_id)
        captured = observer.identify(captured, command.unit_id)
        session._observations[reader.basis].append(captured)
        session.require(captured.span, "conditional_input", captured.detail, unit_id=captured.unit_id)
        session.context.invalidate_meanings(changed, captured.span)
        emit_slice(command.span.start)
        start = len(session.pieces)
        emit_observed_region(session, captured, chain=(*chain, path))
        # Each input has its own final physical line. A synthetic newline keeps
        # a trailing comment/control word from swallowing/merging caller text.
        if doc.text and not doc.text.endswith(("\r", "\n")):
            session._emit(reader.basis.span(reader.basis.length, reader.basis.length), "\n", operation="INPUT_BOUNDARY")
        if len(session.pieces) == start:
            session._omit(command.span, "Empty conditional input")
        for i in range(start, len(session.pieces)):
            piece = session.pieces[i]
            session.pieces[i] = replace(piece, replaces=piece.replaces + (command.span,))
        record.update(status="prepared", payload="master.tex")
        cursor = command.span.end
    emit_slice(region.span.end)
    if isinstance(region, ConditionalRegion) and session.context.catcodes[region.tokens[-1].value[0]] == CatCode.LETTER:
        session._emit(region.span.basis.span(region.span.end, region.span.end), " ", operation="SYNTHETIC_SEPARATOR")


def emit_bibliography(session, observation, owner):
    """Expose a retained bibliography site to the existing canonical formatter.

    BBL inspection has its own context and never changes the manuscript reader.
    Both its envelope and entry headers must be established before admission.
    """
    command = observation.command
    try:
        command.value("names")  # Computed resource names stay at this site.
        if session.bibliography_context is not None:
            raise ReadingIssue("bibliography_sites", "Multiple bibliography sites need separate preparation")
        context = session.context.copy()
        knowledge = BindingResolver(session.resolver.catalog)
        knowledge.active_packages = list(session.resolver.active_packages)
        path = session.root.with_suffix(".bbl")
        captured = reader = None
        if session.store.contains(path):
            doc = session.store.document(path)
            reader = TexReader(doc.text, source_id=doc.name, occurrence_id=len(session.manifest.input_occurrences),
                               catcodes=context.catcodes, endline_char=context.endlinechar)
            inspector = StructuralDispatcher(reader, context, knowledge, preparation=True, source_commands=True)
            items = list(inspector)
            if boundary := next((i for i in items if isinstance(i, ReadingBoundary)), None):
                raise ReadingIssue("bibliography_reading", boundary.detail)
            commands = [replace(i, unit_id=None) for i in items if isinstance(i, SourceCommand)]
            envelopes = {c.action for c in commands if c.metadata.get("bibliography")}
            if not {"environment_begin", "environment_end"} <= envelopes:
                raise ReadingIssue("bibliography_reading", "No complete observed thebibliography envelope")
            # Conditional insertion must not expose hidden conditional tokens to
            # skipped reading. The same bounded input gate applies to BBL data.
            check_context = session.context.copy()
            check_reader = TexReader(doc.text, source_id=doc.name, occurrence_id=reader.basis.occurrence_id,
                catcodes=check_context.catcodes, endline_char=check_context.endlinechar)
            StructuralDispatcher(check_reader, check_context, knowledge,
                preparation=True, source_commands=True).observe_conditional_input()
            captured = DeferredRegion(reader.basis.whole, "observed_bibliography",
                "Formatted bibliography retained inside an uninterpreted source region", observations=tuple(
                    DeferredRegion(c.span, "observed_bibliography", "Source-visible bibliography header", command=c)
                    for c in commands))
    except (ReadingIssue, SourceDecodingError, OSError, InvalidCharacterError) as error:
        session.require(command.span, getattr(error, "reason", "bibliography_reading"), str(error),
                        stage="preparation", unit_id=command.unit_id, dependency="possible", next_step="bibliography_resolution")
        session._emit(command.span, deferred=observation)
        return
    session.commands.append(command)
    session._emit(command.span, command=command, deferred=observation)
    session.bibliography_context = session.context.copy()
    session.bibliography_knowledge = knowledge
    session.bibliography_observed = True
    if reader is None:
        return  # The native formatter can use the emitted canonical BibTeX resource.
    session.register_reader(path, reader, candidate=True, parent=command.span.basis.occurrence_id)
    captured = session.dispatcher.identify(captured, command.unit_id)
    session._observations[reader.basis].append(captured)
    session.require(captured.span, "observed_bibliography", captured.detail, unit_id=captured.unit_id)
    session.manifest.candidate_dependencies.append({"source": command.span.basis.source_id,
        "occurrence": command.span.basis.occurrence_id, "start": command.span.start, "end": command.span.end,
        "kind": "formatted_bibliography", "target": session.name(path), "context": owner.reason,
        "context_span": [owner.span.start, owner.span.end], "basis": "entry_reading_and_search_state",
        "unit_id": command.unit_id, "status": "prepared", "payload": "master.tex"})
    start, cursor = len(session.pieces), 0
    for header in captured.observations:
        cmd = header.command
        session._emit(reader.basis.span(cursor, cmd.span.start), deferred=captured)
        session._emit(cmd.span, command=cmd, deferred=header)
        cursor = cmd.span.end
    session._emit(reader.basis.span(cursor, reader.basis.length), deferred=captured)
    session.bibliography_pieces = session.pieces[start:]
