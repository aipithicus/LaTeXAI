r"""Incremental TeX character reader, independent of expansion and rewriting.

The lexical algorithm follows TeX82's input_ln/get_next/start_input (including
tex.web sections 343--359). This module reads one *file-like*, decoded source buffer:
CRLF, CR and LF delimit physical lines; physical trailing ASCII spaces are
removed; a captured endlinechar is appended to each line, including an
unterminated final line. An empty file supplies one empty line, as in start_input.

N/M/S transitions and all 16 category codes are supported. Classic ^^ notation
is supported (ASCII toggle and two lowercase hexadecimal digits), including
control-sequence lookahead. XeTeX/LuaTeX extended ^^^^/^^^^^^ notation, input
encoding conversion and engine-specific Unicode category initialization are
not implied. The caller supplies a compiled category table and endlinechar;
this module contains no format-specific initialization or profile loading.

The caller owns catcode assignments, scoping, meanings, literal-mode dispatch
and file/token input stacks. This reader does not execute commands, expand
macros, recognize environments, cap paragraphs or serialize cleaned source.
Call next_token() incrementally when the caller must apply effects between
tokens. list(reader) is valid only when no external effects need applying.

No file I/O or logging is performed. Spans are half-open Python string offsets
in the unchanged input (Unicode code points, NOT UTF-8 bytes or UTF-16 units).
The source owner is responsible for mapping them to original encoded bytes.
Events expose skipped material without retaining a second document-sized list.
Only a physical-line window and a few lookahead characters are buffered.

Reference: https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum, IntEnum
import re
from typing import Iterator, Mapping

from .character_rules import CatcodeLayer, category
from .spans import SourceBasis, SourceSpan


class CatCode(IntEnum):
    ESCAPE = 0
    BEGIN_GROUP = 1
    END_GROUP = 2
    MATH_SHIFT = 3
    ALIGNMENT_TAB = 4
    END_OF_LINE = 5
    PARAMETER = 6
    SUPERSCRIPT = 7
    SUBSCRIPT = 8
    IGNORED = 9
    SPACE = 10
    LETTER = 11
    OTHER = 12
    ACTIVE = 13
    COMMENT = 14
    INVALID = 15


class ReaderState(Enum):
    NEW_LINE = "N"
    MID_LINE = "M"
    SKIP_BLANKS = "S"


class TokenKind(Enum):
    CHARACTER = "character"
    CONTROL_SEQUENCE = "control_sequence"
    ACTIVE_CHARACTER = "active_character"


class EventKind(Enum):
    TOKEN = "token"
    COMMENT = "comment"
    IGNORED_SPACE = "ignored_space"
    IGNORED_CHARACTER = "ignored_character"
    END_OF_LINE = "end_of_line"
    DISABLED_ENDLINE = "disabled_endline"
    RECOVERED_INVALID = "recovered_invalid"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    value: str
    catcode: CatCode | None
    span: SourceSpan
    # True when ^^ conversion or a synthetic endlinechar contributed to spelling.
    transformed: bool = False


@dataclass(frozen=True, slots=True)
class ReadEvent:
    kind: EventKind
    # Consumed source, including discarded suffix for COMMENT/END_OF_LINE.
    # A token's own origin can be narrower than the consumed event span.
    span: SourceSpan
    state_before: ReaderState
    state_after: ReaderState
    token: Token | None = None
    # Exact introducer spelling (including ^^ conversion), supplied by the
    # mouth so consumers need not guess where a comment's payload starts.
    comment_marker: SourceSpan | None = None


class InvalidCharacterError(ValueError):
    def __init__(self, character: str, span: SourceSpan):
        self.character = character
        self.span = span
        super().__init__(
            f"Catcode 15 character U+{ord(character):04X} in {span.basis.source_id} "
            f"occurrence {span.basis.occurrence_id} at characters {span.start}:{span.end}"
        )


class CatcodeTable:
    """Caller-owned mutable categories; copies belong to separate reading contexts."""

    def __init__(self, assignments: Mapping[str, int] | None = None,
                 *, default: int, layers: tuple[CatcodeLayer, ...] = ()):
        self._cache: dict[str, CatCode] = {}
        self.default = default
        self._layers = layers
        self._assignments: dict[str, CatCode] = {}
        for character, category in (assignments or {}).items():
            self[character] = category

    def __getitem__(self, character: str) -> CatCode:
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError("Catcode lookup requires one character")
        if character in self._assignments:
            return self._assignments[character]
        if character not in self._cache:
            result = self.default
            for layer in reversed(self._layers):
                code = layer.resolve(character)
                if code is not None:
                    result = CatCode(code)
                    break
            self._cache[character] = result
        return self._cache[character]

    def __setitem__(self, character: str, category: int) -> None:
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError("A catcode assignment requires one Unicode character")
        self._assignments[character] = CatCode(validate_category(category))

    @property
    def default(self) -> CatCode:
        return self._default

    @default.setter
    def default(self, value: int) -> None:
        self._default = CatCode(validate_category(value))
        self._cache.clear()

    def apply_layer(self, layer: CatcodeLayer) -> None:
        """Apply effects in execution order, above any earlier runtime assignments."""
        if self._assignments:
            self._layers += (CatcodeLayer("runtime", assignments=tuple(self._assignments.items())),)
            self._assignments = {}
        self._layers += (layer,)
        self._cache.clear()

    def copy(self) -> CatcodeTable:
        return CatcodeTable(self._assignments, default=self.default, layers=self._layers)

    def restore_from(self, saved: CatcodeTable) -> None:
        """Restore a snapshot in place, retaining references held by a reader."""
        self.default = saved.default
        self._layers = saved._layers
        self._assignments = dict(saved._assignments)


def validate_category(value: int) -> int:
    return category(value, "CatcodeTable")


@dataclass(frozen=True, slots=True)
class _Character:
    value: str
    start: int
    end: int
    transformed: bool = False
    synthetic_endline: bool = False


@dataclass(frozen=True, slots=True)
class CharacterLookahead:
    """An unconsumed mouth character, not a token or an original-source slice.

    Looking ahead may perform ^^ conversion. That conversion stays in the
    cursor even if the caller subsequently changes category codes.
    """
    value: str
    catcode: CatCode
    span: SourceSpan
    transformed: bool
    synthetic_endline: bool


@dataclass(frozen=True, slots=True)
class PhysicalLine:
    """Current original line and its TeX input_ln window (string offsets)."""
    span: SourceSpan
    content_end: int
    mouth_end: int
    endline_char: int | None


@dataclass(frozen=True, slots=True)
class ReaderCheckpoint:
    """Opaque, reader-local cursor snapshot; not a snapshot of execution state."""
    _owner: object
    _cursor: tuple
    _catcodes: CatcodeTable


_PHYSICAL_ENDLINE = re.compile(r"\r\n|\r|\n")
_HEX = frozenset("0123456789abcdef")


class TexReader:
    """Pull reader. Mutate catcodes/endline_char between calls, never via prefetch.

    endline_char uses TeX82's integer convention: values outside 0..255 disable
    insertion. Its value is captured when each physical line is loaded; the
    inserted character's catcode is looked up when it is actually consumed.
    next_event() and next_token() share a cursor; they are alternate views, not
    independent iterators. EOF is None. Invalid characters raise and halt the
    reader, so a caught error cannot silently turn into successful preparation.
    """

    def __init__(self, text: str, *, source_id: str = "<memory>",
                 occurrence_id: int = 0, catcodes: CatcodeTable,
                 endline_char: int):
        if not isinstance(text, str):
            raise TypeError("TexReader expects decoded str; decoding belongs to the source owner")
        self.text = text
        self.start = 0
        self.limit = len(text)
        self.basis = SourceBasis(source_id, occurrence_id, len(text))
        self.catcodes = catcodes
        self.endline_char = endline_char
        self.state = ReaderState.NEW_LINE
        self._queue: deque[_Character] = deque()
        self._started = False
        self._ready = False
        self._next_line = 0
        self._raw_pos = 0
        self._content_end = 0
        self._line_end = 0
        self._line_end_char: int | None = None
        self._endline_queued = False
        self._tail_reported = False
        self._failure: InvalidCharacterError | None = None
        self._position = 0
        self._line_start = 0
        self._physical_content_end = 0
        self._checkpoint_owner = object()
        self._stop_after_line: int | None = None
        self.terminated_span: SourceSpan | None = None
        # Includes discard events consumed inside argument scanners. Emission
        # subtracts preserved regions before turning these into tombstones.
        self.discarded: list[tuple[SourceSpan, str]] = []

    def line_window(self, span: SourceSpan) -> TexReader:
        """Read a proven whole-line region again in memory, retaining its basis.

        Used for packages that capture raw lines and subsequently input that
        body. No substring copy, new file, or fabricated source occurrence.
        """
        self.basis.require(span)
        if not self.start <= span.start <= span.end <= self.limit:
            raise ValueError("Replay window must stay inside the current source window")
        for position in (span.start, span.end):
            if position not in (0, len(self.text)) and (self.text[position - 1] not in "\r\n"
                    or self.text[position - 1:position + 1] == "\r\n"):
                raise ValueError("Replay window must use physical-line boundaries")
        reader = TexReader(self.text, source_id=self.basis.source_id,
                           occurrence_id=self.basis.occurrence_id,
                           catcodes=self.catcodes, endline_char=self.endline_char)
        reader.basis = self.basis
        reader.discarded = self.discarded
        reader._next_line = reader._position = span.start
        reader.start = span.start
        reader.limit = span.end
        reader._started = span.start == span.end
        return reader

    def end_input_after_line(self) -> None:
        """Defer file termination until the next physical-line refill."""
        self._stop_after_line = self._line_end

    @property
    def position(self) -> int:
        """End of consumed source; excludes pending character lookahead."""
        return self._position

    def source_span(self, start: int, end: int) -> SourceSpan:
        return self._span(start, end)

    def source_slice(self, span: SourceSpan) -> str:
        self.basis.require(span)
        return self.text[span.start:span.end]

    @property
    def current_line(self) -> PhysicalLine | None:
        if not self._ready:
            return None
        return PhysicalLine(self._span(self._line_start, self._line_end),
                            self._physical_content_end, self._content_end,
                            self._line_end_char)

    def peek_character(self) -> CharacterLookahead | None:
        """Inspect this loaded line only, without consuming or loading another.

        None means the current line's mouth window is exhausted (or no line
        is loaded), not necessarily end of the source. Use current_line for
        the original trailing spaces/newline that input_ln removes.
        """
        if self._failure is not None:
            raise self._failure
        if not self._ready or (unit := self._expanded_peek()) is None:
            return None
        return CharacterLookahead(unit.value, self.catcodes[unit.value],
                                  self._span(unit.start, unit.end), unit.transformed,
                                  unit.synthetic_endline)

    def checkpoint(self) -> ReaderCheckpoint:
        """Capture bounded lexical lookahead, including already converted chars.

        Callers must not use this to undo execution effects or lexical scopes
        in ReaderContext. Successful literal exit restores scope, not cursor.
        """
        return ReaderCheckpoint(self._checkpoint_owner, (
            self.state, tuple(self._queue), self._started, self._ready,
            self._next_line, self._raw_pos, self._content_end, self._line_end,
            self._line_end_char, self._endline_queued, self._tail_reported,
            self._failure, self._position, self._line_start,
            self._physical_content_end, self.endline_char, self._stop_after_line,
            self.terminated_span, len(self.discarded)), self.catcodes.copy())

    def consume_raw_to(self, end: int) -> None:
        """Hand a proven literal extent back without tokenizing its body.

        Forward only. A handler must establish the extent and owns its meaning.
        Physical line loading still honors input_ln and pending endinput limits.
        """
        if not self.position <= end <= self.limit or self._failure is not None:
            raise ValueError("Invalid raw cursor handoff")
        if self._stop_after_line is not None and end > self._stop_after_line:
            raise ValueError("Raw handoff crosses pending endinput")
        self._queue.clear()
        while not self._ready or end > self._line_end:
            if not self._load_line():
                raise ValueError("Raw handoff crosses source termination")
        self._position = end
        self._raw_pos = end
        if end == self._line_end:
            self._ready = False
            self._endline_queued = True
            self._tail_reported = True
            self.state = ReaderState.NEW_LINE
        else:
            self.state = ReaderState.MID_LINE

    def restore(self, checkpoint: ReaderCheckpoint) -> None:
        if not isinstance(checkpoint, ReaderCheckpoint) or checkpoint._owner is not self._checkpoint_owner:
            raise ValueError("Checkpoint belongs to a different reader")
        (self.state, queued, self._started, self._ready,
         self._next_line, self._raw_pos, self._content_end, self._line_end,
         self._line_end_char, self._endline_queued, self._tail_reported,
         self._failure, self._position, self._line_start,
         self._physical_content_end, self.endline_char, self._stop_after_line,
         self.terminated_span, discarded_count) = checkpoint._cursor
        del self.discarded[discarded_count:]
        self._queue = deque(queued)
        self.catcodes.restore_from(checkpoint._catcodes)

    @property
    def endline_char(self) -> int:
        return self._endline_char

    @endline_char.setter
    def endline_char(self, value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("endline_char must be an integer")
        self._endline_char = value

    def _span(self, start: int, end: int) -> SourceSpan:
        return self.basis.span(start, end)

    def _load_line(self) -> bool:
        self.state = ReaderState.NEW_LINE
        if self._stop_after_line is not None and self._next_line >= self._stop_after_line:
            self.terminated_span = self._span(self._stop_after_line, self.limit)
            return False
        if self._started and self._next_line >= self.limit:
            return False
        self._started = True
        start = self._next_line
        match = _PHYSICAL_ENDLINE.search(self.text, start, self.limit)
        content_end = match.start() if match else self.limit
        self._line_start = start
        self._physical_content_end = content_end
        self._line_end = match.end() if match else self.limit
        self._next_line = self._line_end
        while content_end > start and self.text[content_end - 1] == " ":
            content_end -= 1
        if content_end < self._physical_content_end:
            self.discarded.append((self._span(content_end, self._physical_content_end), "input_ln trailing spaces"))
        self._content_end = content_end
        self._raw_pos = start
        self._line_end_char = self.endline_char if 0 <= self.endline_char <= 255 else None
        self._endline_queued = False
        self._tail_reported = False
        self._ready = True
        return True

    def _peek(self, index: int = 0) -> _Character | None:
        # Lookahead is confined to one physical line. It never tokenizes or
        # assigns categories to future characters, even at a control-word end.
        while len(self._queue) <= index:
            if self._raw_pos < self._content_end:
                pos = self._raw_pos
                self._queue.append(_Character(self.text[pos], pos, pos + 1))
                self._raw_pos += 1
            elif not self._endline_queued and self._line_end_char is not None:
                self._queue.append(_Character(
                    chr(self._line_end_char), self._content_end, self._line_end, True, True))
                self._endline_queued = True
            else:
                return None
        return self._queue[index]

    def _expanded_peek(self) -> _Character | None:
        # ^^ conversion is character preprocessing, not macro expansion. Keep
        # converted lookahead in the buffer: TeX also converts ^^ immediately
        # following a control-word name, even if that character ends the name.
        while (first := self._peek()) is not None:
            if self.catcodes[first.value] != CatCode.SUPERSCRIPT:
                return first
            second = self._peek(1)
            third = self._peek(2) if second and second.value == first.value else None
            if third is None or ord(third.value) >= 128:
                return first
            fourth = self._peek(3) if third.value in _HEX else None
            if fourth is not None and fourth.value in _HEX:
                count = 4
                value = chr(int(third.value + fourth.value, 16))
            else:
                count = 3
                value = chr(ord(third.value) ^ 64)
            consumed = [self._queue.popleft() for _ in range(count)]
            self._queue.appendleft(_Character(value, first.start, consumed[-1].end, True,
                                             any(c.synthetic_endline for c in consumed)))
        return None

    def _finish_line(self) -> None:
        self._queue.clear()
        self._ready = False

    def _control_sequence(self, escape: _Character) -> Token:
        first = self._expanded_peek()
        if first is None:
            # An escape at a line end with disabled endlinechar yields null_cs.
            return Token(TokenKind.CONTROL_SEQUENCE, "", None,
                         self._span(escape.start, escape.end), escape.transformed)
        category = self.catcodes[first.value]
        self.state = (ReaderState.SKIP_BLANKS if category in (CatCode.LETTER, CatCode.SPACE)
                      else ReaderState.MID_LINE)
        name = []
        transformed = escape.transformed
        last = first
        while True:
            unit = self._queue.popleft()
            name.append(unit.value)
            transformed |= unit.transformed
            last = unit
            if category != CatCode.LETTER:
                break
            following = self._expanded_peek()
            if following is None or self.catcodes[following.value] != CatCode.LETTER:
                break
        return Token(TokenKind.CONTROL_SEQUENCE, "".join(name), None,
                     self._span(escape.start, last.end), transformed)

    def next_event(self) -> ReadEvent | None:
        event = self._next_event()
        if event is not None:
            self._position = event.span.end
            if event.token is None and event.span.start < event.span.end:
                self.discarded.append((event.span, event.kind.value))
        else:
            self._position = self.limit
        return event

    def discard_invalid_character(self, error: InvalidCharacterError) -> ReadEvent:
        """Explicitly recover the exact failed character, without changing state.

        This is a cursor primitive, not permission to edit source. Its owner must
        justify and record the emitted repair. Ordinary reads remain sticky failures.
        """
        if error is not self._failure:
            raise ValueError("Recovery requires this reader's current invalid-character failure")
        self._failure = None
        self._position = error.span.end
        self.discarded.append((error.span, EventKind.RECOVERED_INVALID.value))
        return ReadEvent(EventKind.RECOVERED_INVALID, error.span, self.state, self.state)

    def _next_event(self) -> ReadEvent | None:
        if self._failure is not None:
            raise self._failure
        while True:
            if not self._ready and not self._load_line():
                return None
            unit = self._expanded_peek()
            if unit is not None:
                break
            if (self._line_end_char is None and not self._tail_reported
                    and self._content_end < self._line_end):
                self._tail_reported = True
                return ReadEvent(EventKind.DISABLED_ENDLINE,
                                 self._span(self._content_end, self._line_end),
                                 self.state, self.state)
            self._ready = False

        self._queue.popleft()
        category = self.catcodes[unit.value]
        before = self.state
        span = self._span(unit.start, unit.end)
        if category == CatCode.INVALID:
            self._failure = InvalidCharacterError(unit.value, span)
            raise self._failure
        if category == CatCode.IGNORED:
            return ReadEvent(EventKind.IGNORED_CHARACTER, span, before, self.state)
        if category == CatCode.COMMENT:
            consumed = self._span(unit.start, self._line_end)
            self._finish_line()
            return ReadEvent(EventKind.COMMENT, consumed, before, self.state,
                             comment_marker=span)
        if category == CatCode.END_OF_LINE:
            consumed = self._span(unit.start, self._line_end)
            self._finish_line()
            if before == ReaderState.NEW_LINE:
                token = Token(TokenKind.CONTROL_SEQUENCE, "par", None, span, unit.transformed)
            elif before == ReaderState.MID_LINE:
                token = Token(TokenKind.CHARACTER, " ", CatCode.SPACE, span, unit.transformed)
            else:
                token = None
            # TeX resets N when advancing past this line, not on returning a token.
            return ReadEvent(EventKind.END_OF_LINE, consumed, before, self.state, token)
        if category == CatCode.SPACE:
            if before != ReaderState.MID_LINE:
                return ReadEvent(EventKind.IGNORED_SPACE, span, before, self.state)
            self.state = ReaderState.SKIP_BLANKS
            token = Token(TokenKind.CHARACTER, " ", category, span, unit.transformed)
        elif category == CatCode.ESCAPE:
            token = self._control_sequence(unit)
        else:
            self.state = ReaderState.MID_LINE
            kind = TokenKind.ACTIVE_CHARACTER if category == CatCode.ACTIVE else TokenKind.CHARACTER
            token = Token(kind, unit.value, category, span, unit.transformed)
        return ReadEvent(EventKind.TOKEN, token.span, before, self.state, token)

    def next_token(self) -> Token | None:
        while (event := self.next_event()) is not None:
            if event.token is not None:
                return event.token
        return None

    def __iter__(self) -> Iterator[Token]:
        while (token := self.next_token()) is not None:
            yield token
