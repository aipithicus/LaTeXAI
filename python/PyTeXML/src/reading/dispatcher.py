"""Source-preserving initial literal dispatch over one live mouth cursor.

This is an active-context fragment reader, not a complete LaTeX executor. The
knowledge provider selects reusable handlers through resolved grammar data.
Unsupported commands, modes and package grammars establish a diagnostic frontier;
the unchanged remainder is retained. No expansion, input discovery, source edits,
logging or preparation-pipeline integration takes place here.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
from typing import Iterator, Protocol

from .context import ExecutionMode, ReaderContext
from .contracts import EffectiveReadingProfile, UnresolvedBindingResult
from .tex_reader import (
    CatCode, EventKind, InvalidCharacterError, ReadEvent, SourceSpan, TexReader,
    Token, TokenKind,
)


class ReadingKnowledge(Protocol):
    """Already loaded knowledge; ownership and package activation stay outside."""
    def resolve_command(self, name: str) -> EffectiveReadingProfile | UnresolvedBindingResult: ...
    def resolve_environment(self, name: str) -> EffectiveReadingProfile | UnresolvedBindingResult: ...


@dataclass(frozen=True, slots=True)
class ReadingBoundary:
    span: SourceSpan
    remainder: SourceSpan
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class LiteralRegion:
    span: SourceSpan
    opening: SourceSpan
    body: SourceSpan
    closing: SourceSpan
    name: str
    binding_id: str


class _Unresolved(Exception):
    def __init__(self, reason: str, detail: str):
        self.reason, self.detail = reason, detail


class LiteralDispatcher:
    """Yield ordinary reader events, complete literal spans, or one boundary.

    The reader and context must share a category table. The caller establishes
    active execution and package knowledge before entering. A boundary halts this
    dispatcher; it never guesses past unknown macros, stored definitions or
    conditional execution. Scopes restore categories and reader parameters, but
    successful literal exit retains the cursor's *exit* N/M/S state.
    """

    def __init__(self, reader: TexReader, context: ReaderContext, knowledge: ReadingKnowledge):
        if reader.catcodes is not context.catcodes:
            raise ValueError("Reader and context must share their category table")
        if reader.endline_char != context.endlinechar:
            raise ValueError("Reader and context must agree on endlinechar")
        self.reader, self.context, self.knowledge = reader, context, knowledge
        self.halted = False

    def _boundary(self, span: SourceSpan, reason: str, detail: str) -> ReadingBoundary:
        self.halted = True
        return ReadingBoundary(span, self.reader.source_span(span.start, len(self.reader.text)),
                               reason, detail)

    @staticmethod
    def _resolved(result: EffectiveReadingProfile | UnresolvedBindingResult) -> EffectiveReadingProfile:
        if isinstance(result, UnresolvedBindingResult):
            raise _Unresolved(result.reason.value, result.detail)
        return result

    @staticmethod
    def _require(condition: bool, detail: str) -> None:
        if not condition:
            raise _Unresolved("unsupported_literal_grammar", detail)

    def next_item(self) -> ReadEvent | LiteralRegion | ReadingBoundary | None:
        if self.halted:
            return None
        reader = self.reader
        if self.context.mode != ExecutionMode.ACTIVE_EXECUTION:
            return self._boundary(reader.source_span(reader.position, reader.position),
                                  "inactive_context", "An owning scanner must handle this execution mode")
        try:
            event = reader.next_event()
        except InvalidCharacterError as error:
            return self._boundary(error.span, "invalid_character", str(error))
        if event is None or event.kind != EventKind.TOKEN or event.token is None:
            return event
        token = event.token
        if token.kind == TokenKind.ACTIVE_CHARACTER:
            return self._boundary(event.span, "active_character", "Active character meaning is unresolved")
        if token.kind != TokenKind.CONTROL_SEQUENCE:
            return event
        try:
            profile = self._resolved(self.knowledge.resolve_command(token.value))
            handler = profile.grammar.get("handler")
            if handler == "environment_name":
                self._require(profile.grammar.get("argument") == "braced_literal_name",
                              "Only literal braced environment names are supported")
                name = self._environment_name()
                profile = self._resolved(self.knowledge.resolve_environment(name))
                handler = profile.grammar.get("handler")
                self._require(handler == "token_delimited" and profile.grammar.get("arity") == 0,
                              "Environment requires an unsupported header or body handler")
            self._require(handler in {"inline_character", "token_delimited"},
                          "No initial literal handler is selected by this binding")
            self._require(not profile.interpolations and not profile.active_options and profile.action is None,
                          "Literal options, actions and interpolation require further dispatch")
            with self.context.lexical_scope():
                self.context.apply_profile(profile)
                reader.endline_char = self.context.endlinechar
                if handler == "inline_character":
                    return self._inline(event.span.start, profile)
                return self._block(event.span.start, profile)
        except _Unresolved as error:
            return self._boundary(event.span, error.reason, error.detail)
        except InvalidCharacterError as error:
            return self._boundary(event.span, "invalid_character", str(error))
        finally:
            reader.endline_char = self.context.endlinechar

    def _environment_name(self) -> str:
        """Read a bounded non-expanding argument; braces here are not execution."""
        token = self.reader.next_token()
        while token is not None and token.catcode == CatCode.SPACE:
            token = self.reader.next_token()
        self._require(token is not None and token.catcode == CatCode.BEGIN_GROUP,
                      "Expected a braced environment name")
        name = []
        while (token := self.reader.next_token()) is not None:
            if token.catcode == CatCode.END_GROUP:
                self._require(bool(name), "Empty environment name")
                return "".join(name)
            self._require(token.kind == TokenKind.CHARACTER and token.catcode in {CatCode.LETTER, CatCode.OTHER},
                          "Computed or nested environment names need an argument interpreter")
            name.append(token.value)
        raise _Unresolved("unclosed_header", "Environment name has no closing brace")

    def _region(self, start: int, body_start: int, closing: SourceSpan,
                profile: EffectiveReadingProfile) -> LiteralRegion:
        span = self.reader.source_span
        return LiteralRegion(span(start, closing.end), span(start, body_start),
                             span(body_start, closing.start), closing, profile.name, profile.binding_id)

    def _check_body_token(self, token: Token, definition: ReaderContext) -> None:
        # A block first scans unexpanded tokens, but subsequently executes its
        # captured body. Unknown active meanings/escapes could have global effects
        # that invalidate resumption after the literal's local scope has closed.
        self._require(token.kind != TokenKind.CONTROL_SEQUENCE
                      and token.catcode in {CatCode.LETTER, CatCode.OTHER, CatCode.SPACE, CatCode.ACTIVE}
                      and (token.kind != TokenKind.ACTIVE_CHARACTER
                           or definition.catcodes[token.value] == CatCode.ACTIVE),
                      "Literal body contains unresolved execution or altered reading behavior")

    def _inline(self, start: int, profile: EffectiveReadingProfile) -> LiteralRegion:
        reader = self.reader
        grammar = profile.grammar
        self._require(grammar.get("delimiter_mode") == "dynamic_char" and
                      grammar.get("multiline_allowed") is False,
                      "Only single-line dynamic-character literals are supported")
        unit = reader.peek_character()
        if (grammar.get("star_token_allowed") and unit is not None
                and unit.value == grammar.get("star_token") and unit.catcode == CatCode.OTHER):
            reader.next_event()
            profile = self._resolved(self.knowledge.resolve_command(grammar["starred_command"]))
            grammar = profile.grammar
            self._require(grammar.get("handler") == "inline_character" and not profile.interpolations,
                          "Starred variant requires a different handler")
            self._require(not profile.active_options and profile.action is None
                          and grammar.get("delimiter_mode") == "dynamic_char"
                          and grammar.get("multiline_allowed") is False,
                          "Starred variant requires unsupported reading behavior")
            self.context.apply_profile(profile)
            reader.endline_char = self.context.endlinechar
            unit = reader.peek_character()
        skipped = grammar.get("delimiter_skip_characters", [])
        while unit is not None and not unit.synthetic_endline and unit.value in skipped:
            reader.next_event()
            unit = reader.peek_character()
        if unit is None or unit.synthetic_endline:
            raise _Unresolved("missing_delimiter", "Inline literal has no delimiter on this physical line")
        self._require(unit.value not in grammar.get("invalid_delimiters", []),
                      "Delimiter is outside this binding's supported grammar")
        self._require(unit.catcode in {CatCode.LETTER, CatCode.OTHER, CatCode.ACTIVE},
                      "Delimiter requires additional argument scanning")
        delimiter = unit.value
        reader.next_event()
        body_start = reader.position
        self._require(grammar.get("delimiter_catcode") == CatCode.ACTIVE,
                      "Only an active closing delimiter is supported")
        self.context.catcodes[delimiter] = grammar["delimiter_catcode"]
        definition = ReaderContext(baseline=self.context.baseline)
        definition.apply_profile(profile)
        while (unit := reader.peek_character()) is not None and not unit.synthetic_endline:
            event = reader.next_event()
            if (event.token is not None and event.token.kind == TokenKind.ACTIVE_CHARACTER
                    and event.token.value == delimiter):
                return self._region(start, body_start, event.span, profile)
            token = event.token
            if token is None:
                continue
            self._check_body_token(token, definition)
        raise _Unresolved("unclosed_literal", "Inline literal has no closing delimiter on this physical line")

    def _block(self, start: int, profile: EffectiveReadingProfile) -> LiteralRegion:
        rule = profile.terminator
        self._require(rule is not None and bool(rule.exact_string), "Literal has no terminator")
        self._require(rule.matching_domain == "mouth_tokens" and rule.boundary_mode == "token_sequence"
                      and rule.regex_pattern == re.escape(rule.exact_string)
                      and not rule.requires_column_zero and rule.trailing_content_allowed
                      and rule.trailing_line_behavior == "preserve_trailing_content"
                      and not profile.grammar.get("allow_nesting", False),
                      "Only exact token delimiters with preserved suffixes are supported")
        self._require(profile.grammar.get("terminator_baseline") == self.context.baseline.name,
                      "Terminator's definition-time category baseline is unavailable")
        # The delimiter was defined under the declared baseline, not under
        # arbitrary later manuscript assignments. Body tokens keep live cats.
        definition = ReaderContext(baseline=self.context.baseline)
        definition.apply_profile(profile)
        expected = [(char, definition.catcodes[char]) for char in rule.exact_string]
        # KMP over token identities: linear scan, bounded delimiter-sized storage.
        failure = [0] * len(expected)
        matched = 0
        for i in range(1, len(expected)):
            while matched and expected[i] != expected[matched]:
                matched = failure[matched - 1]
            if expected[i] == expected[matched]:
                matched += 1
            failure[i] = matched
        recent: deque[SourceSpan] = deque(maxlen=len(expected))
        body_start, matched = self.reader.position, 0
        while (event := self.reader.next_event()) is not None:
            token: Token | None = event.token
            if token is None:
                continue  # TeX discards these before matching macro delimiters.
            self._check_body_token(token, definition)
            key = (token.value, token.catcode)
            recent.append(token.span)
            while matched and key != expected[matched]:
                matched = failure[matched - 1]
            if key == expected[matched]:
                matched += 1
            if matched == len(expected):
                closing = self.reader.source_span(recent[0].start, token.span.end)
                return self._region(start, body_start, closing, profile)
        raise _Unresolved("unclosed_literal", "Block literal has no matching closing token sequence")

    def __iter__(self) -> Iterator[ReadEvent | LiteralRegion | ReadingBoundary]:
        while (item := self.next_item()) is not None:
            yield item
