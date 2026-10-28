"""Non-expanding definition capture over the shared mouth cursor.

This scanner never resolves command meanings, dispatches bodies, installs a
definition, or opens execution scopes. The dispatcher owns those decisions.
Parameter validation follows TeX82's scan_toks(macro_def=true, xpand=false),
without its error recovery. Captures retain lexical tokens, including ## pairs;
they are not TeX's compiled match/out_param token representation.
"""
from __future__ import annotations

from .context import ExecutionMode, ReaderContext
from .argument_scanner import ArgumentScanner
from .contracts import (CommandDefinition, EffectiveReadingProfile, ReadingIssue,
                        ScannedArgument, StateManagementRule, StoredDefinition)
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

    def read(self, start: int, profile: EffectiveReadingProfile, *, expand_body=None) -> StoredDefinition:
        """Capture a supported local declaration after its command token was read."""
        self._require(self.context.mode == ExecutionMode.ACTIVE_EXECUTION,
                      "inactive_context", "Definition scanning requires an active declaration")
        self._require(self.reader.catcodes is self.context.catcodes
                      and self.reader.endline_char == self.context.endlinechar,
                      "context_changed", "Definition scanner and reader must share reading state")
        primitive = (profile.grammar == {"handler": "primitive_definition", "expansion": "none"}
                     or expand_body is not None and profile.grammar ==
                     {"handler": "primitive_definition", "expansion": "full"})
        wrapper = (profile.grammar.get("handler") == "command_definition"
                   and set(profile.grammar) == {"handler", "expansion", "target_requirement", "forbidden_names", "forbidden_prefixes"}
                   and profile.grammar.get("expansion") == "none"
                   and profile.grammar.get("target_requirement") in ("absent", "present")
                   and all(isinstance(profile.grammar[key], list)
                           and all(isinstance(value, str) and value for value in profile.grammar[key])
                           for key in ("forbidden_names", "forbidden_prefixes")))
        self._require(profile.family == "stored_definition" and (primitive or wrapper)
                      and profile.state_management == StateManagementRule()
                      and profile.action is None and not profile.catcode_layers
                      and not profile.catcode_overrides and not profile.reader_parameters
                      and not profile.interpolations and not profile.active_options
                      and profile.terminator is None and not profile.tex_mechanics,
                      "unsupported_definition", "Only supported local definitions can be established")
        with self.context.stored_definition():
            return self._command(start, profile) if wrapper else self._read(start, profile.binding_id, expand_body)

    def _read(self, start: int, binding_id: str, expand_body=None) -> StoredDefinition:
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

        expanded = None
        if expand_body is None:
            body, closing = self.read_body(count)
        else:
            body, closing, expanded = expand_body(self, count)
        span = self.reader.source_span
        return StoredDefinition(
            span(start, closing.span.end), span(start, opening.span.end),
            span(target.span.end, opening.span.start),
            span(opening.span.end, closing.span.start), closing.span, target,
            tuple(parameters), body, count, hash_brace, binding_id, expanded_tokens=expanded)

    def read_body(self, count: int) -> tuple[tuple[Token, ...], Token]:
        """Capture replacement tokens after the opening group was consumed.

        Validate parameter markers against count, consume the matching closing
        token, and return it separately. The caller owns capture mode and any
        eventual definition installation; this method executes no body effects.
        """
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
                self._replacement_parameter(following, count)
                body.append(following)

        return tuple(body), closing

    def _replacement_parameter(self, following: Token | None, count: int) -> None:
        number = self._digit(following) if following is not None else None
        self._require(following is not None and (following.catcode == CatCode.PARAMETER
                      or (number is not None and number <= count)),
                      "invalid_definition_parameter", "Replacement text requires a declared parameter or doubled marker")

    def _command(self, start: int, profile: EffectiveReadingProfile) -> CommandDefinition:
        args = ArgumentScanner(self.reader, self.context)
        first = args.next_nonspace()
        starred = (first is not None and first.kind == TokenKind.CHARACTER
                   and first.catcode == CatCode.OTHER and first.value == "*")
        if starred:
            first = args.next_nonspace()
        self._require(first is not None, "unclosed_definition", "Missing command target")
        if first.catcode == CatCode.BEGIN_GROUP:
            tokens = []
            while (token := self._token()).catcode != CatCode.END_GROUP:
                self._require(token.catcode != CatCode.BEGIN_GROUP, "invalid_definition_target",
                              "Command target must be a single literal control sequence")
                tokens.append(token)
            target_argument = ScannedArgument("target", self.reader.source_span(first.span.end, token.span.start), tuple(tokens))
            targets = [t for t in tokens if t.catcode != CatCode.SPACE]
        else:
            target_argument = ScannedArgument("target", first.span, (first,))
            targets = [first]
        self._require(len(targets) == 1 and targets[0].kind == TokenKind.CONTROL_SEQUENCE,
                      "invalid_definition_target", "Command target must be a single literal control sequence")
        target = targets[0]
        self._require(target.value not in profile.grammar["forbidden_names"]
                      and not any(target.value.startswith(p) for p in profile.grammar["forbidden_prefixes"]),
                      "invalid_definition_target", "Command target is reserved by this declaration recipe")
        target_end = self.reader.position
        count_argument, count, default = self.signature()
        opening = args.next_nonspace()
        self._require(opening is not None, "argument_required", "Missing command replacement text")
        # ltdefns.dtx's long @argdef/@xargdef absorb the replacement as one
        # undelimited argument, before constructing the primitive definition.
        try:
            replacement = args.undelimited("command replacement text", first=opening)
        except ReadingIssue as error:
            if error.reason == "unclosed_argument":
                raise ReadingIssue("unclosed_definition", error.detail) from error
            raise
        tokens = iter(replacement.tokens)
        for token in tokens:
            if token.catcode == CatCode.PARAMETER:
                self._replacement_parameter(next(tokens, None), count)
        braced = opening.catcode == CatCode.BEGIN_GROUP
        end = self.reader.position if braced else replacement.span.end
        span = self.reader.source_span
        return CommandDefinition(
            span(start, end), span(start, replacement.span.start),
            span(target_end, opening.span.start), replacement.span,
            span(replacement.span.end, end), target, (), replacement.tokens, count, None, profile.binding_id,
            declaration=profile.name, starred=starred, target_argument=target_argument,
            argument_count=count_argument, optional_default=default,
            target_requirement=profile.grammar["target_requirement"], body_braced=braced)

    def signature(self):
        """Capture the shared bounded [count][default] declaration signature."""
        args = ArgumentScanner(self.reader, self.context)
        count_argument = args.group("argument_count", optional=True)
        count = 0
        if count_argument is not None:
            digits = [t for t in count_argument.tokens if t.catcode != CatCode.SPACE]
            self._require(len(digits) == 1 and digits[0].kind == TokenKind.CHARACTER
                          and digits[0].catcode == CatCode.OTHER and digits[0].value in "0123456789",
                          "unsupported_definition_count", "Argument count must be a literal digit from 0 to 9")
            count = int(digits[0].value)
        default = args.group("optional_default", optional=True) if count_argument is not None else None
        if default is not None:
            self._require(count > 0, "invalid_definition_default", "An optional default requires at least one argument")
            # The kernel stores the default in a parameterless helper definition.
            # It may contain doubled markers, but cannot reference outer parameters.
            tokens = iter(default.tokens)
            for token in tokens:
                if token.catcode == CatCode.PARAMETER:
                    following = next(tokens, None)
                    self._require(following is not None and following.catcode == CatCode.PARAMETER,
                                  "invalid_definition_parameter", "Default text requires doubled parameter markers")
        return count_argument, count, default
