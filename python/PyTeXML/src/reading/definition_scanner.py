"""Non-expanding primitive definition capture over the shared mouth cursor.

This scanner never resolves command meanings, dispatches bodies, installs a
definition, or opens execution scopes. The dispatcher owns those decisions.
Parameter validation follows TeX82's scan_toks(macro_def=true, xpand=false),
without its error recovery. Captures retain lexical tokens, including ## pairs;
they are not TeX's compiled match/out_param token representation.
"""
from __future__ import annotations

from .context import ExecutionMode, ReaderContext
from .contracts import EffectiveReadingProfile, ReadingIssue, StateManagementRule, StoredDefinition
from .tex_reader import CatCode, TexReader, Token, TokenKind


class DefinitionScanner:
    def __init__(self, reader: TexReader, context: ReaderContext):
        self.reader, self.context = reader, context

    @staticmethod
    def _require(condition: bool, reason: str, detail: str) -> None:
        if not condition:
            raise ReadingIssue(reason, detail)

    def _token(self) -> Token:
        token = self.reader.next_token()
        if token is None:
            raise ReadingIssue("unclosed_definition", "EOF while scanning a definition")
        return token

    @staticmethod
    def _digit(token: Token) -> int | None:
        # TeX requires an OTHER-category ASCII digit, not merely a numeric glyph.
        if (token.kind == TokenKind.CHARACTER and token.catcode == CatCode.OTHER
                and token.value in "123456789"):
            return int(token.value)
        return None

    def read(self, start: int, profile: EffectiveReadingProfile) -> StoredDefinition:
        """Capture one local primitive definition after its command token was read."""
        self._require(self.context.mode == ExecutionMode.ACTIVE_EXECUTION,
                      "inactive_context", "Definition scanning requires an active declaration")
        self._require(self.reader.catcodes is self.context.catcodes
                      and self.reader.endline_char == self.context.endlinechar,
                      "context_changed", "Definition scanner and reader must share reading state")
        self._require(profile.family == "stored_definition"
                      and profile.grammar == {"handler": "primitive_definition", "expansion": "none"}
                      and profile.state_management == StateManagementRule()
                      and profile.action is None and not profile.catcode_layers
                      and not profile.catcode_overrides and not profile.reader_parameters
                      and not profile.interpolations and not profile.active_options
                      and profile.terminator is None and not profile.tex_mechanics,
                      "unsupported_definition", "Only local, unexpanded primitive definitions are supported")
        with self.context.stored_definition():
            return self._read(start, profile.binding_id)

    def _read(self, start: int, binding_id: str) -> StoredDefinition:
        target = self._token()
        while target.catcode == CatCode.SPACE:
            target = self._token()
        self._require(target.kind in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER},
                      "invalid_definition_target", "Expected a control sequence or active character")

        parameters: list[Token] = []
        count, hash_brace = 0, None
        while True:
            token = self._token()
            if token.catcode == CatCode.BEGIN_GROUP:
                opening = token
                break
            self._require(token.catcode != CatCode.END_GROUP, "invalid_definition",
                          "Closing group before the replacement text's opening group")
            parameters.append(token)
            if token.catcode == CatCode.PARAMETER:
                following = self._token()
                if following.catcode == CatCode.BEGIN_GROUP:
                    hash_brace = opening = following
                    break
                self._require(count < 9 and self._digit(following) == count + 1,
                              "invalid_definition_parameter", "Parameters must be numbered consecutively from 1 to 9")
                parameters.append(following)
                count += 1

        body: list[Token] = []
        depth = 1
        while True:
            token = self._token()
            if token.catcode == CatCode.BEGIN_GROUP:
                depth += 1
            elif token.catcode == CatCode.END_GROUP:
                depth -= 1
                if depth == 0:
                    closing = token
                    break
            body.append(token)
            if token.catcode == CatCode.PARAMETER:
                following = self._token()
                number = self._digit(following)
                self._require(following.catcode == CatCode.PARAMETER
                              or (number is not None and number <= count),
                              "invalid_definition_parameter", "Replacement text requires a declared parameter or doubled marker")
                body.append(following)

        span = self.reader.source_span
        return StoredDefinition(
            span(start, closing.span.end), span(start, opening.span.end),
            span(target.span.end, opening.span.start),
            span(opening.span.end, closing.span.start), closing.span, target,
            tuple(parameters), tuple(body), count, hash_brace, binding_id)
