"""Observe citation keys without treating missing interpretation as nocite{*}.

Only dispatcher-established headers contribute keys. A uniquely described but
inactive binding can contribute an explicitly provisional observation. No raw
source search, package activation, argument execution or macro expansion occurs.
Unobserved keys remain available in the canonical bibliography resource.
"""
from dataclasses import dataclass
from ..reading.contracts import ReadingIssue
from ..reading.spans import SourceSpan
from ..reading.tex_reader import TokenKind


@dataclass(frozen=True)
class CitationRequirement:
    span: SourceSpan
    reason: str
    detail: str


@dataclass(frozen=True)
class CitationSelection:
    keys: list[str]
    established_keys: set[str]
    gaps: list[dict]
    deferred_contexts: int
    requirements: list[CitationRequirement]

    @property
    def discovery(self):
        return "partial" if self.gaps or self.deferred_contexts else "complete"


def discover_citations(pieces, resolver, *, line):
    """Return observations and requests; the caller owns manifest/unit updates."""
    keys, established, gaps, deferred_contexts = [], set(), [], 0
    requirements = []

    def gap(span, reason, detail, **extra):
        gaps.append(dict(source=span.basis.source_id, occurrence=span.basis.occurrence_id,
                         start=span.start, end=span.end, line=line(span),
                         reason=reason, detail=detail, **extra))

    for piece in pieces:
        deferred = piece.deferred
        command = piece.command or (deferred.command if deferred else None)
        if command is not None and command.action == "citation":
            if deferred:
                gap(command.span, "citation_binding_pending", deferred.detail,
                    binding=deferred.binding_id, command=command.name)
            try:
                observed = [key.strip() for key in command.value("keys").split(",")]
                if any(not key or any(c.isspace() or c in "\\{}%#[]" for c in key)
                       or ("*" in key and not (key == "*" and command.metadata.get("allow_wildcard")))
                       for key in observed):
                    raise ReadingIssue("bibliography_keys", "Citation keys need expansion or a richer key grammar")
            except ReadingIssue as error:
                gap(command.span, error.reason, error.detail)
                requirements.append(CitationRequirement(command.span, error.reason, error.detail))
            else:
                keys.extend(observed)
                if deferred is None:
                    established.update(observed)
        elif deferred and deferred.reason not in {"math_interpretation", "alignment_interpretation"}:
            # A retained invocation/environment may contain or produce citations.
            # Keep that uncertainty separate from the known key selection.
            deferred_contexts += 1

        if piece.operation == "PRESERVE_UNRESOLVED":
            gap(piece.span, "unread_source", "Citation discovery did not read this retained source extent")
        elif piece.operation == "DEFER_RESOLUTION" and command and command.action in {
                "source_input", "source_include", "source_import", "source_subimport"}:
            gap(piece.span, "unread_input", "Unresolved source input may contain further citations")

        # Captured command arguments and math may themselves contain citations.
        # They are not executed merely to fill the bibliography; locate the gap.
        tokens = (t for arg in command.arguments for t in arg.tokens) if command else (
            iter(deferred.tokens) if deferred else iter(()))
        for token in tokens:
            if token.kind != TokenKind.CONTROL_SEQUENCE:
                continue
            profile = resolver.resolve_command(token.value)
            if getattr(profile, "action", None) != "citation":
                profile = resolver.source_command_syntax(token.value)
            if getattr(profile, "action", None) == "citation":
                gap(token.span, "nested_citation", "Citation inside an uninterpreted argument or region needs its owning context")

    return CitationSelection(list(dict.fromkeys(keys)), established, gaps, deferred_contexts, requirements)
