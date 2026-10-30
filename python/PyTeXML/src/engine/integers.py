"""Shared integer scanning over the current, bounded token cursor.

TeX's scan_int/scan_optional_equals expand
while scanning numbers, but not after a backtick. This subset accepts literal
constants, bounded macro expansion and established internal values. A returned
token retains its captured category. Internal quantities consume no optional
trailing space, unlike constants.

One scanner owns all operands of a request. Call finish() before publishing its
effects: replacement input requiring later execution remains a boundary.

Reference: https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web
"""
from __future__ import annotations

from ..reading.contracts import (BoundMeaning, CharacterCodeMeaning,
                                 EffectiveReadingProfile, ReadingIssue)
from ..reading.tex_reader import CatCode, TokenKind
from .operations import OperationHost
from .expansion import ExpansionCursor
from .primitive import PrimitiveMeaning


class IntegerScanner:
    def __init__(self, host: OperationHost, *, relaxed_target=None):
        self.host = host
        self.reader = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations,
                                      relaxed_target=relaxed_target, host=host)
        # chardef gives its target temporary relax meaning before reading RHS.
        # Keep that provisional meaning local until the whole assignment succeeds.
        self.relaxed_target = relaxed_target
        self._depth = 0
        self.ends_control_word = False

    @staticmethod
    def _other(token, spelling):
        return (token is not None and token.kind == TokenKind.CHARACTER
                and token.catcode == CatCode.OTHER and token.value in spelling)

    def _meaning(self, token):
        if self.relaxed_target == (token.kind, token.value):
            return None  # provisional relax, with no integer role
        meaning = self.host.context.resolve_meaning(self.host.knowledge, token.value, token.kind)
        if isinstance(meaning, (BoundMeaning, CharacterCodeMeaning, PrimitiveMeaning)) and meaning.uncertain is not None:
            raise ReadingIssue("uncertain_meaning", "Integer depends on an uncertain meaning",
                               causes=(meaning.uncertain,))
        if isinstance(meaning, CharacterCodeMeaning):
            return meaning
        if isinstance(meaning, PrimitiveMeaning):
            operation = self.host.operations.get(meaning.operation)
            if operation is not None and operation.unexpandable:
                return (operation, meaning)
        if self.reader.suppressed:
            return None  # A suppressed expandable token has no integer role.
        raise ReadingIssue("computed_assignment", "Integer scanning requires expansion or an unsupported internal value")

    def _next(self):
        return self.reader.next_expanded()

    def finish(self):
        """Return source lookahead and require complete replacement consumption.

        ExpansionCursor already returns source tokens to their frozen cursor.
        Leftover replacement tokens need an execution continuation and cannot be
        discarded or attributed to a fabricated manuscript slice.
        """
        if self.reader.pending:
            raise ReadingIssue("integer_continuation",
                               "Integer request leaves replacement tokens requiring execution")
        consumed = self.reader.source_tokens
        self.ends_control_word = bool(consumed and consumed[-1].control_word
                                      and self.host.reader.position == consumed[-1].span.end)

    def _nonspace(self):
        token = self._next()
        while token is not None and token.catcode == CatCode.SPACE:
            token = self._next()
        return token

    def optional_equals(self):
        token = self._nonspace()
        if token is not None and not self._other(token, "="):
            self.reader.unread_token(token)

    def keyword(self, word):
        """scan_keyword: expand letters, restoring unsuccessful lookahead."""
        seen = []
        for index, letter in enumerate(word):
            token = self._nonspace() if index == 0 else self._next()
            if token is not None:
                seen.append(token)
            if (token is None or token.kind != TokenKind.CHARACTER
                    or token.catcode not in {CatCode.LETTER, CatCode.OTHER}
                    or token.value.lower() != letter.lower()):
                if len(seen) == 1:
                    self.reader.unread_token(seen[0])
                else:
                    self.reader.push(tuple(seen))
                return False
        return True

    def internal(self, token):
        meaning = self._meaning(token)
        if isinstance(meaning, CharacterCodeMeaning):
            from .quantities import InternalQuantity
            return InternalQuantity("integer", meaning.value)
        if isinstance(meaning, tuple) and meaning[0].internal_value is not None:
            return meaning[0].internal_value(self, meaning[1])
        raise ReadingIssue("computed_assignment", "Expected an established internal quantity")

    def _optional_space(self):
        token = self._next()
        if token is not None and token.catcode != CatCode.SPACE:
            self.reader.unread_token(token)
        elif token is not None:
            self.ends_control_word = False

    @staticmethod
    def _digit(token, radix):
        if token is None or token.kind != TokenKind.CHARACTER:
            return None
        if token.catcode == CatCode.OTHER and token.value in "0123456789":
            value = ord(token.value) - ord("0")
        elif radix == 16 and token.catcode in {CatCode.LETTER, CatCode.OTHER} and token.value in "ABCDEF":
            value = ord(token.value) - ord("A") + 10
        else:
            return None
        return value if value < radix else None

    def integer(self):
        if self._depth >= 100:
            raise ReadingIssue("computed_assignment", "Internal integer nesting exceeds the supported limit")
        self._depth += 1
        try:
            return self._integer()
        finally:
            self._depth -= 1

    def _integer(self):
        sign = 1
        token = self._nonspace()
        while self._other(token, "+-"):
            if token.value == "-":
                sign = -sign
            token = self._nonspace()
        if self._other(token, "`"):
            character = self.reader.next_token()  # deliberately no expansion
            if character is None or len(character.value) != 1:
                raise ReadingIssue("computed_assignment", "Backtick needs one character or one-character control sequence")
            value = ord(character.value)
            self.ends_control_word = character.control_word
            self._optional_space()
        elif token is not None and token.kind != TokenKind.CHARACTER:
            quantity = self.internal(token)
            if quantity.kind not in {"integer", "dimension"}:
                raise ReadingIssue("computed_assignment", "Expected an integer-compatible internal quantity")
            value = quantity.value
            self.ends_control_word = token.control_word
        else:
            radix = 10
            if self._other(token, "'\""):
                radix = 8 if token.value == "'" else 16
                token = self._next()
            value, count = 0, 0
            self.ends_control_word = False
            while (digit := self._digit(token, radix)) is not None:
                value = value * radix + digit
                count += 1
                if value > 2147483647:
                    raise ReadingIssue("invalid_assignment", "Integer exceeds TeX's signed 31-bit magnitude")
                token = self._next()
            if not count:
                raise ReadingIssue("computed_assignment", "Expected an integer constant or established internal value")
            if token is not None and token.catcode != CatCode.SPACE:
                self.reader.unread_token(token)
        return sign * value
