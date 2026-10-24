"""Emission pieces retain occurrence coordinates through preparation edits."""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from ..reading.spans import SourceSpan
from ..reading.edit_map import EditMap
from ..reading.contracts import DeferredRegion, SourceCommand
from ..reading.tex_reader import ReadEvent, TokenKind, CatCode, EventKind, ReaderState


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


def event_text(event: ReadEvent, raw: str) -> str:
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
