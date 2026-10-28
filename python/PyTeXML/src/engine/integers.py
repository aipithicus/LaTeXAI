"""Shared integer scanning over the current, bounded token cursor.

TeX's scan_int/scan_optional_equals expand
while scanning numbers, but not after a backtick. This subset accepts literal
constants and established internal values; it reports an expansion requirement
instead of treating an unexpanded command as a numeric terminator. A returned
token retains its captured category. Internal quantities consume no optional
trailing space, unlike constants.

Reference: https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web
"""
from __future__ import annotations

from ..reading.contracts import (BoundMeaning, CharacterCodeMeaning,
                                 EffectiveReadingProfile, ReadingIssue)
from ..reading.tex_reader import CatCode, TokenKind
from .operations import OperationHost


class IntegerScanner:
    def __init__(self, host: OperationHost, *, relaxed_target=None):
        self.host = host
        self.reader = host.reader
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
        meaning = self.host.context.lookup_meaning(token.value, token.kind)
        if isinstance(meaning, (BoundMeaning, CharacterCodeMeaning)) and meaning.uncertain is not None:
            raise ReadingIssue("uncertain_meaning", "Integer depends on an uncertain meaning",
                               causes=(meaning.uncertain,))
        if isinstance(meaning, CharacterCodeMeaning):
            return meaning
        profile = (meaning.profile if isinstance(meaning, BoundMeaning)
                   else self.host.knowledge.resolve_command(token.value) if meaning is None else None)
        if isinstance(profile, EffectiveReadingProfile):
            operation = self.host.operations.get(profile.family)
            if operation is not None and operation.unexpandable:
                return (operation, profile)
            if profile.name == r"\relax" and profile.action == "reading_noop":
                return None
        raise ReadingIssue("computed_assignment", "Integer scanning requires expansion or an unsupported internal value")

    def _next(self):
        token = self.reader.next_token()
        if token is not None and token.kind != TokenKind.CHARACTER:
            self._meaning(token)  # establish that it is unexpandable before using it
        return token

    def _nonspace(self):
        token = self._next()
        while token is not None and token.catcode == CatCode.SPACE:
            token = self._next()
        return token

    def optional_equals(self):
        token = self._nonspace()
        if token is not None and not self._other(token, "="):
            self.reader.unread_token(token)

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
            meaning = self._meaning(token)
            if isinstance(meaning, CharacterCodeMeaning):
                value = meaning.value
                self.ends_control_word = token.control_word
            elif isinstance(meaning, tuple) and meaning[0].integer_value is not None:
                value = meaning[0].integer_value(self, meaning[1])
            else:
                raise ReadingIssue("computed_assignment", "Expected an integer, found an unexpandable command")
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
