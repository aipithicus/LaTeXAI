"""Whole-project observations, independent of execution and emission eligibility.

Each physical source is scanned under an independent entry profile. These records
are candidates for later resolution, never active dependency edges. The shared
source store supplies bytes already read by traversal; no output copies are made.
"""
from ..bindings.resolver import BindingResolver
from ..source_io import SourceDecodingError
from ..reading.contracts import (CommandDefinition, EnvironmentDefinition, DeferredRegion, LiteralRegion, ReadingBoundary,
                                SourceCommand, SourceEnd, StoredDefinition, SkippedRegion, ReadingIssue)
from ..reading.dispatcher import StructuralDispatcher
from ..reading.tex_reader import TexReader, TokenKind, InvalidCharacterError


def survey_sources(store, catalog):
    reports = []
    for path in store.files:
        if path.suffix.lower() not in {".tex", ".sty", ".cls", ".bbl", ".tikz"}:
            continue
        report = {"source": path.relative_to(store.root).as_posix(),
                  "basis": "independent_entry_profile", "status": "observed",
                  "commands": [], "protected": [], "boundaries": []}
        reports.append(report)
        try:
            doc = store.document(path)
        except (SourceDecodingError, OSError) as error:
            report.update(status="unreadable", error=str(error))
            continue
        resolver = BindingResolver(catalog)
        report["length"] = len(doc.text)
        context = resolver.new_context()
        if path.suffix.lower() in {".sty", ".cls"}:
            for char, code in catalog.engine_bindings["source_traversal"]["reading"]["package_input_catcodes"].items():
                context.catcodes[char] = code
        reader = TexReader(doc.text, source_id=doc.name, catcodes=context.catcodes,
                           endline_char=context.endlinechar)
        dispatcher = StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True)

        def tokens(items, domain, offset=0):
            for token in items:
                if token.kind in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER}:
                    report["commands"].append({"name": token.value, "context": domain,
                        "start": offset + token.span.start, "end": offset + token.span.end})

        def residue(span, domain):
            # After a reading barrier no activation or delimiter claim is made.
            # The baseline lexical census still locates potential work items.
            probe = TexReader(doc.text[span.start:span.end], source_id=doc.name,
                              catcodes=resolver.new_context().catcodes, endline_char=context.baseline.endlinechar)
            try:
                while (token := probe.next_token()) is not None:
                    tokens((token,), domain, span.start)
            except InvalidCharacterError as error:
                report["status"] = "partial"
                report["boundaries"].append({"start": span.start + error.span.start,
                                             "end": span.end, "reason": "invalid_character"})

        for item in dispatcher:
            if isinstance(item, ReadingBoundary):
                report["boundaries"].append({"start": item.remainder.start, "end": item.remainder.end,
                                             "reason": item.reason})
                residue(item.remainder, "after_reading_boundary")
            elif isinstance(item, SourceCommand):
                arguments = {}
                for arg in item.arguments:
                    try:
                        arguments[arg.name] = {"literal": arg.literal()}
                    except ReadingIssue as error:
                        arguments[arg.name] = {"unresolved": error.reason}
                    tokens(arg.tokens, "argument")
                report["commands"].append({"name": item.name.lstrip("\\"), "action": item.action,
                    "context": "source_visible", "start": item.span.start, "end": item.span.end,
                    "arguments": arguments})
                if item.action == "package_load":
                    value = arguments.get("name", {}).get("literal", "")
                    for name in value.split(","):
                        resolver.load_package(name)
                if item.action == "environment_end" and item.metadata.get("document"):
                    residue(reader.source_span(reader.position, len(doc.text)), "excluded_tail")
                    break
            elif isinstance(item, (StoredDefinition, EnvironmentDefinition)):
                if isinstance(item, (CommandDefinition, EnvironmentDefinition)) and item.optional_default is not None:
                    tokens(item.optional_default.tokens, "stored_definition_default")
                tokens(item.body_tokens, "stored_definition")
                if isinstance(item, EnvironmentDefinition) and item.final_code is not None:
                    if item.final_code.span.basis is item.span.basis and item.span.start <= item.final_code.span.start < item.span.end:
                        tokens(item.final_code.tokens, "stored_definition_final")
                report["protected"].append({"start": item.span.start, "end": item.span.end, "kind": "definition"})
            elif isinstance(item, DeferredRegion):
                tokens(item.tokens, "deferred")
                report["protected"].append({"start": item.span.start, "end": item.span.end, "kind": item.reason})
            elif isinstance(item, (LiteralRegion, SkippedRegion)):
                # A literal is data; skipped source is not executed. Neither is
                # turned into a false dependency merely to increase the census.
                report["protected"].append({"start": item.span.start, "end": item.span.end,
                    "kind": "literal" if isinstance(item, LiteralRegion) else "skipped"})
            elif isinstance(item, SourceEnd) and item.span.end > item.span.start:
                residue(item.span, "excluded_tail")
        report["commands"].sort(key=lambda c: (c["start"], c["end"]))
    return reports
