"""Read captured tokens without running them through the character mouth again.

The original text is shared only for diagnostics and source spans. Categories and
control-sequence spellings come from capture time. There are no physical-line or
literal-character operations, and this cursor never changes a suspended mouth's
N/M/S state. Event states are inert MID_LINE markers for the token-stream API.
"""
from dataclasses import dataclass

from .tex_reader import EventKind, ReadEvent, ReaderState


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    owner: object
    index: int
    position: int


class TokenCursor:
    def __init__(self, argument, text, context):
        self.tokens = argument.tokens
        self.window = argument.span
        self.basis = self.window.basis
        self.text = text
        self.catcodes = context.catcodes
        self.endline_char = context.endlinechar
        self.position = self.window.start
        self.index = 0
        for token in self.tokens:
            self.basis.require(token.span)
            if not self.window.start <= token.span.start <= token.span.end <= self.window.end:
                raise ValueError("Captured token is outside its body")

    def source_span(self, start, end):
        return self.basis.span(start, end)

    def source_slice(self, span):
        self.basis.require(span)
        return self.text[span.start:span.end]

    def checkpoint(self):
        return _Checkpoint(self, self.index, self.position)

    def restore(self, saved):
        if saved.owner is not self:
            raise ValueError("Checkpoint belongs to another token cursor")
        self.index, self.position = saved.index, saved.position

    def next_token(self):
        if self.index == len(self.tokens):
            self.position = self.window.end
            return None
        token = self.tokens[self.index]
        self.index += 1
        self.position = token.span.end
        return token

    def next_event(self):
        token = self.next_token()
        if token is None:
            return None
        return ReadEvent(EventKind.TOKEN, token.span, ReaderState.MID_LINE,
                         ReaderState.MID_LINE, token)
