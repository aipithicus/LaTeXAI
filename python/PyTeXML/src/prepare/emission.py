"""Emission pieces retain occurrence coordinates through preparation edits."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from ..reading.spans import SourceSpan
from ..reading.edit_map import EditMap
from ..reading.contracts import DeferredRegion, SourceCommand
from ..reading.tex_reader import ReadEvent, TokenKind, CatCode, EventKind, ReaderState
from .policy import ExtractionPolicy


@dataclass(frozen=True, slots=True)
class SourcePiece:
    text: str
    span: SourceSpan
    source_line: int
    operation: str = "IDENTITY"
    command: object | None = None
    image_references: tuple[tuple[SourceCommand, str], ...] = ()
    source_end_line: int | None = None
    deferred: DeferredRegion | None = None
    mapping: EditMap | None = None
    # Replacement relations are independent of the text's own source origin.
    replaces: tuple[SourceSpan, ...] = ()
    key: object = field(default_factory=object, compare=False, repr=False)

    def __post_init__(self):
        if self.mapping is None:
            mapping = (EditMap.copied(self.span) if self.operation == "IDENTITY"
                       else EditMap.replaced(self.span, len(self.text)))
            object.__setattr__(self, "mapping", mapping)
        if self.mapping.length != len(self.text):
            raise ValueError("Emission mapping length does not match its text")

    def rewritten(self, text: str, operation: str) -> SourcePiece:
        return self.edited(0, len(self.text), text, operation)

    def edited(self, start: int, end: int, text: str, operation: str) -> SourcePiece:
        if not 0 <= start <= end <= len(self.text):
            raise ValueError("Edit is outside current text")
        if self.text[start:end] == text:
            return self
        mapping = self.mapping.edit(start, end, len(text))
        return replace(self, text=self.text[:start] + text + self.text[end:],
                       operation=operation, mapping=mapping)

    def edit_source(self, span: SourceSpan, text: str, operation: str) -> SourcePiece:
        ranges = sorted(self.mapping.project(span), key=lambda r: (r.start, r.end))
        if (not ranges or any(r.relation == "enclosing" for r in ranges)
                or any(a.end != b.start for a, b in zip(ranges, ranges[1:]))):
            raise ValueError("Source edit requires one precisely mapped output range")
        return self.edited(ranges[0].start, ranges[-1].end, text, operation)


@dataclass(frozen=True, slots=True)
class EventEmission:
    """A pure emission decision; the source owner records edits and metadata."""
    text: str
    suffix: str = ""
    metadata: dict | None = None
    kept_span: SourceSpan | None = None


class MouthEmitter:
    """Serialize established reader events under a validated preparation policy.

    No filesystem access, execution, or scanning inside protected slices. Comment
    suppression is preserved by joining lines without manufacturing an endline
    token. Kept comments retain their physical terminator, including at input EOF.
    """

    def __init__(self, policy: ExtractionPolicy):
        unsupported = []
        if policy.lexical_events.comment_line == "route_to_sidecar":
            unsupported.append("lexical_events.comment_line=route_to_sidecar (no comment-sidecar contract)")
        if policy.lexical_events.line_continuation != "preserve":
            unsupported.append("lexical_events.line_continuation=eliminate (would change endline suppression)")
        if policy.normalization.paragraph_breaks != "preserve":
            unsupported.append("structural_normalization.paragraph_breaks=coalesce (paragraph tokens may have observable meanings)")
        if policy.normalization.trailing_whitespace != "strip":
            unsupported.append("structural_normalization.trailing_whitespace=preserve (requires physical-line emission)")
        if unsupported:
            raise ValueError(f"{policy.source}: unsupported preparation settings: " + "; ".join(unsupported))
        self.policy = policy

    def emit(self, event: ReadEvent, source: str) -> EventEmission:
        raw = source[event.span.start:event.span.end]
        if event.kind != EventKind.COMMENT:
            return EventEmission(_token_text(event, raw))
        # N means this line has not produced a token. Whitespace-like source
        # characters with other catcodes cannot fool a character-prefix test.
        whole_line = event.state_before == ReaderState.NEW_LINE
        directive = comment_directive(event, source) if whole_line else None
        action = (self.policy.lexical_events.magic_directive if directive else
                  self.policy.lexical_events.comment_line if whole_line else
                  self.policy.lexical_events.comment_inline)
        if action == "preserve":
            return EventEmission(raw, "" if raw.endswith(("\r", "\n")) else "\n")
        metadata = directive if action == "extract_metadata" else None
        marker = event.comment_marker
        if (marker is not None and event.span.end == len(source)
                and event.state_before != ReaderState.SKIP_BLANKS):
            spelling = source[marker.start:marker.end]
            if spelling and not any(c in spelling for c in "\r\n"):
                # At file EOF, deleting the suppression itself can create a
                # space (or a paragraph for an otherwise empty file). Keep only
                # the proven marker; the payload still receives a tombstone.
                return EventEmission(spelling, "\n", metadata, marker)
        return EventEmission("", metadata=metadata)


def comment_directive(event: ReadEvent, source: str) -> dict | None:
    """Read !TeX key=value metadata only after a mouth-proven comment marker.

    Unknown keys are data. Values never configure execution or output paths.
    This also works with alternative comment characters and ^^ spellings.
    """
    if event.kind != EventKind.COMMENT or event.comment_marker is None:
        return None
    payload = source[event.comment_marker.end:event.span.end].strip()
    # split handles tabs and repeated whitespace in editor metadata.
    parts = payload.split(None, 1)
    if len(parts) != 2 or parts[0].casefold() != "!tex":
        return None
    key, equals, value = parts[1].partition("=")
    if not equals or not key.strip():
        return None
    return {"kind": "tex_directive", "key": " ".join(key.casefold().split()), "value": value.strip()}


def _token_text(event: ReadEvent, raw: str) -> str:
    """Serialize bounded mouth events without accidental input-join paragraphs.

    Literal and definition bodies never enter this function. Control-word
    delimiter spaces are lexical separators. Physical endlines that generated
    spaces become spaces; paragraph tokens become explicit paragraph commands.
    """
    token = event.token
    if token is None:
        return ""
    if event.kind == EventKind.END_OF_LINE:
        return "\\par " if token.kind == TokenKind.CONTROL_SEQUENCE else " "
    if token.catcode == CatCode.SPACE:
        return " "
    if token.kind == TokenKind.CONTROL_SEQUENCE and event.state_after == ReaderState.SKIP_BLANKS:
        return raw + " "
    return raw
