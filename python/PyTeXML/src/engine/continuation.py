"""One bounded execution after expansion, preserving the owning source extent.

The mouth and expansion frames are one input continuation. Admission is an
operation role; arbitrary text, I/O and layout remain with later consumers.
The dispatcher owns the transaction and publishes only a completed operation.
"""
from dataclasses import replace

from .expansion import ExpansionCursor
from .primitive import PrimitiveMeaning
from ..reading.contracts import BoundMeaning, ReadingIssue
from ..reading.tex_reader import EventKind, ReadEvent, ReaderState


class ContinuationReader:
    def __init__(self, cursor, start):
        self.cursor, self.start = cursor, start

    def __getattr__(self, name):
        value = getattr(self.cursor.source, name)
        if not callable(value):
            return value
        def source_operation(*args, **kwargs):
            if self.cursor.pending:
                raise ReadingIssue("expansion_continuation", "Raw source operation has pending replacement tokens")
            return value(*args, **kwargs)
        return source_operation

    @property
    def position(self):
        return self.cursor.source.position

    @property
    def endline_char(self):
        return self.cursor.source.endline_char

    @endline_char.setter
    def endline_char(self, value):
        self.cursor.source.endline_char = value

    def next_token(self):
        return self.cursor.next_token()

    def next_event(self):
        token = self.next_token()
        return None if token is None else ReadEvent(
            EventKind.TOKEN, token.span, ReaderState.MID_LINE, ReaderState.MID_LINE, token)

    def source_span(self, start, end):
        if not self.start <= start <= end <= self.position:
            raise ReadingIssue("continuation_origin", "Operation extent is not a contiguous authored source range")
        return self.cursor.source.source_span(start, end)

    def enclose_definition(self, definition):
        """Authored envelope includes the expansion prefix and outer delimiters.

        Individual opening/body ranges still partition that envelope; extending
        every span with the same start would swallow the replacement body.
        """
        return replace(definition, span=self.source_span(self.start, self.position),
                       closing=self.source_span(definition.closing.start, self.position))

    def checkpoint(self):
        return self.cursor.checkpoint()

    def restore(self, saved):
        self.cursor.restore(saved)

    def unread_token(self, token):
        self.cursor.unread_token(token)


def execute(host, opening):
    from ..reading.operations import FAMILY_OPERATIONS
    source = host.reader
    cursor = ExpansionCursor(source, host.context, host.knowledge, host.operations)
    cursor.allow_name_assignment = True
    cursor.push((opening.token,))
    def admitted(profile):
        operation = FAMILY_OPERATIONS.get(profile.family)
        return operation is not None and operation.continuation
    token = cursor.next_expanded(stop_operation=lambda op: op.continuation, stop=admitted)
    if token is None or cursor.suppressed:
        raise ReadingIssue("expansion_continuation", "Expansion has no supported execution result")
    meaning = host.context.resolve_meaning(host.knowledge, token.value, token.kind)
    operation = host.operations.get(meaning.operation) if isinstance(meaning, PrimitiveMeaning) else None
    operand = meaning
    if isinstance(meaning, BoundMeaning) and meaning.profile is not None:
        operation = FAMILY_OPERATIONS.get(meaning.profile.family)
        operand = meaning.profile
    if operation is None or not operation.continuation:
        raise ReadingIssue("expansion_continuation", "Expanded output needs another execution consumer")
    span = source.source_span(opening.span.start, source.position)
    # The operation owns its prefix too. Its token identity is separate from
    # this enclosing source anchor; no serialization/re-tokenization occurs.
    event = replace(opening, span=span, token=replace(token, span=span))
    host._set_reader(ContinuationReader(cursor, opening.span.start))
    try:
        result = operation.execute(host, event, operand)
        if cursor.pending:
            raise ReadingIssue("expansion_continuation", "Operation left replacement tokens pending")
        return result
    finally:
        host._set_reader(source)
