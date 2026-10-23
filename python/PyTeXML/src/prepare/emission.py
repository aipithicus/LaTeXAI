"""Emission pieces retain occurrence coordinates through preparation edits."""
from __future__ import annotations
from dataclasses import dataclass, replace
from ..reading.spans import SourceSpan
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

    def rewritten(self, text: str, operation: str) -> SourcePiece:
        return replace(self, text=text, operation=operation)


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
