"""Read captured tokens without running them through the character mouth again.

The original text is shared only for diagnostics and source spans. Categories and
control-sequence spellings come from capture time. There are no physical-line or
literal-character operations, and this cursor never changes a suspended mouth's
N/M/S state. Event states are inert MID_LINE markers for the token-stream API.
"""
from dataclasses import dataclass

from .tex_reader import EventKind, ReadEvent, ReaderState, Token


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    owner: object
    index: int
    position: int
    last_token: Token | None


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
        self._last_token = None
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
        return _Checkpoint(self, self.index, self.position, self._last_token)

    def restore(self, saved):
        if saved.owner is not self:
            raise ValueError("Checkpoint belongs to another token cursor")
        self.index, self.position = saved.index, saved.position
        self._last_token = saved.last_token

    def next_token(self):
        self._last_token = None
        if self.index == len(self.tokens):
            self.position = self.window.end
            return None
        token = self.tokens[self.index]
        self.index += 1
        self.position = token.span.end
        self._last_token = token
        return token

    def unread_token(self, token):
        if self._last_token is not token or token is None:
            raise ValueError("Only the last returned token can be put back")
        self.index -= 1
        self.position = token.span.start
        self._last_token = None

    def next_event(self):
        token = self.next_token()
        if token is None:
            return None
        return ReadEvent(EventKind.TOKEN, token.span, ReaderState.MID_LINE,
                         ReaderState.MID_LINE, token)
