"""Reusable literal scanners on the live reader; no top-level execution routing."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
import re

from .context import ExecutionMode, ReaderContext
from .contracts import (
    EffectiveReadingProfile, LiteralRegion, ReadingIssue, ReadingKnowledge, require_resolved, DeferredRegion,
)
from .tex_reader import (
    CatCode, TexReader, Token, TokenKind,
)
from .spans import SourceSpan
from .argument_scanner import ArgumentScanner
from .configuration import configured_options

_NEWLINE = re.compile(r"\r\n|\r|\n")

class LiteralScanner:
    """Consume a resolved literal occurrence with temporary lexical settings.

    The structural dispatcher owns activation, header recognition and diagnostics.
    This scanner owns literal grammar and local profile entry/exit. It does not
    pull ordinary document events, execute commands from a body, or build XML.
    """

    def __init__(self, reader: TexReader, context: ReaderContext, knowledge: ReadingKnowledge):
        if reader.catcodes is not context.catcodes:
            raise ValueError("Reader and context must share their category table")
        if reader.endline_char != context.endlinechar:
            raise ValueError("Reader and context must agree on endlinechar")
        self.reader, self.context, self.knowledge = reader, context, knowledge

    @staticmethod
    def _require(condition: bool, detail: str) -> None:
        if not condition:
            raise ReadingIssue("unsupported_literal_grammar", detail)

    def read(self, start: int, profile: EffectiveReadingProfile, *, defer_interpolation=False) -> LiteralRegion:
        """Enter at the current cursor, retaining the original occurrence start."""
        reader = self.reader
        if self.context.mode != ExecutionMode.ACTIVE_EXECUTION:
            raise ReadingIssue("inactive_context", "Literal entry requires active execution")
        try:
            if profile.grammar.get("handler") == "inline_character" and profile.grammar.get("has_optional_arguments"):
                with self.context.argument_scanning():
                    argument = ArgumentScanner(reader, self.context).group("options", optional=True)
                options = configured_options(profile, argument, self.context, preserve_unclassified=False)
                profile = require_resolved(self.knowledge.resolve_command(profile.name, options.values))
            handler = profile.grammar.get("handler")
            self._require(handler in {"inline_character", "token_delimited", "physical_line_literal"},
                          "No initial literal handler is selected by this binding")
            self._require((not profile.interpolations or defer_interpolation) and profile.action is None,
                          "Literal options, actions and interpolation require further dispatch")
            if handler == "physical_line_literal":
                self._require(profile.span_classification.category in {"opaque_literal", "editorial_comment_block", "transparent_block", "interpolated_literal"}
                              and not profile.catcode_overrides,
                              "Reading-affecting options need a further literal handler")
                self._require(len(profile.interpolations) <= 1 and all(r.mode == "tex" for r in profile.interpolations),
                              "Combined or math interpolation needs another reading contract")
                return self._physical_lines(start, profile)
            self._require(not profile.active_options or handler == "inline_character",
                          "Literal options require further dispatch")
            with self.context.lexical_scope():
                self.context.apply_profile(profile)
                reader.endline_char = self.context.endlinechar
                if handler == "inline_character":
                    return self._inline(start, profile)
                return self._block(start, profile)
        finally:
            reader.endline_char = self.context.endlinechar

    def _region(self, start: int, body_start: int, closing: SourceSpan,
                profile: EffectiveReadingProfile) -> LiteralRegion:
        span = self.reader.source_span
        return LiteralRegion(span(start, closing.end), span(start, body_start),
                             span(body_start, closing.start), closing, profile.name, profile.binding_id,
                             profile.span_classification)

    def _physical_lines(self, start: int, profile: EffectiveReadingProfile) -> LiteralRegion:
        rule = profile.terminator
        self._require(rule is not None and rule.matching_domain == "physical_line",
                      "Physical-line literal requires a line terminator contract")
        pattern = re.compile(rule.regex_pattern)
        body_start = (self.reader.current_line.span.end if profile.grammar.get("body_start") == "next_physical_line"
                      else self.reader.position)
        line_start = (body_start if profile.grammar.get("body_start") == "next_physical_line"
                      else self.reader.current_line.span.start)
        source = self.reader.text
        interpolations, cursor = [], body_start
        while line_start < self.reader.limit:
            newline = _NEWLINE.search(source, line_start, self.reader.limit)
            content_end = newline.start() if newline else self.reader.limit
            line_end = newline.end() if newline else self.reader.limit
            line = source[line_start:content_end].rstrip(" ")
            matches = pattern.finditer(line, max(0, body_start - line_start))
            for match in matches:
                if profile.interpolations:
                    interpolation = profile.interpolations[0]
                    candidate = line_start + match.start()
                    while cursor < candidate:
                        opening = source.find(interpolation.opening, cursor, candidate)
                        if opening < 0:
                            cursor = candidate
                            break
                        captured = self._interpolation(opening, interpolation, profile)
                        interpolations.append(captured)
                        cursor = captured.span.end
                    if cursor > candidate:
                        continue
                if not ((not rule.requires_column_zero or match.start() == 0)
                    and (rule.trailing_content_allowed or match.end() == len(line))):
                    continue
                end = line_start + match.end()
                if rule.trailing_line_behavior == "discard_with_warning" or not rule.trailing_content_allowed:
                    end = line_end
                closing = self.reader.source_span(line_start + match.start(), end)
                # These handlers capture raw lines only under their declared
                # reading configuration. An arbitrary author-made comment or
                # active character outside the profile cannot be ignored.
                actual = ReaderContext(baseline=self.context.baseline, catcodes=self.context.catcodes,
                                       endlinechar=self.context.endlinechar)
                expected = ReaderContext(baseline=self.context.baseline)
                literal_profile = replace(profile, interpolations=())
                actual.apply_profile(literal_profile)
                expected.apply_profile(literal_profile)
                self._require(actual.endlinechar == expected.endlinechar
                              and all(actual.catcodes[c] == expected.catcodes[c]
                                      for c in set(source[body_start:end]) if c not in "\r\n"),
                              "Live reading state differs from the physical-line literal contract")
                self.reader.consume_raw_to(end)
                region = self._region(start, body_start, closing, profile)
                region = replace(region, interpolations=tuple(interpolations))
                if rule.trailing_line_behavior == "discard_with_warning" and line[match.end():].strip():
                    region = replace(region, warnings=("Package discards content following the literal terminator on this line",))
                return region
            line_start = line_end
        raise ReadingIssue("unclosed_literal", "No matching physical-line literal terminator")

    def _interpolation(self, start, rule, profile):
        """Capture unexpanded escape tokens under entry state, including comments.

        Active closing characters are recognized by token identity, not a raw
        substring search through TeX comments/control sequences. Execution that
        could change this reading is an explicit downstream requirement.
        """
        reader = self.reader
        reader.consume_raw_to(start + len(rule.opening))
        tokens, recent = [], deque(maxlen=len(rule.closing))
        with self.context.lexical_scope():
            self.context.catcodes[rule.closing[0]] = CatCode.ACTIVE
            expected = tuple((c, self.context.catcodes[c]) for c in rule.closing)
            while (token := reader.next_token()) is not None:
                tokens.append(token)
                recent.append((token.value, token.catcode))
                if tuple(recent) == expected:
                    return DeferredRegion(reader.source_span(start, token.span.end),
                        "literal_interpolation", "Unexpanded TeX escape captured under entry reading state; its effects remain unresolved",
                        tuple(tokens[:-len(expected)]), binding_id=profile.binding_id)
        raise ReadingIssue("unclosed_interpolation", "No closing escape delimiter under entry reading state")

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
        self._require(grammar.get("delimiter_mode") in {"dynamic_char", "hybrid_delim_or_braced"} and
                      grammar.get("multiline_allowed") is False,
                      "Only single-line dynamic-character literals are supported")
        unit = reader.peek_character()
        if (grammar.get("star_token_allowed") and unit is not None
                and unit.value == grammar.get("star_token") and unit.catcode == CatCode.OTHER):
            reader.next_event()
            profile = require_resolved(self.knowledge.resolve_command(grammar["starred_command"]))
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
            raise ReadingIssue("missing_delimiter", "Inline literal has no delimiter on this physical line")
        self._require(unit.value not in grammar.get("invalid_delimiters", []),
                      "Delimiter is outside this binding's supported grammar")
        self._require(unit.catcode in {CatCode.LETTER, CatCode.OTHER, CatCode.ACTIVE},
                      "Delimiter requires additional argument scanning")
        delimiter = "}" if unit.value == "{" and grammar.get("delimiter_mode") == "hybrid_delim_or_braced" else unit.value
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
        raise ReadingIssue("unclosed_literal", "Inline literal has no closing delimiter on this physical line")

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
        raise ReadingIssue("unclosed_literal", "Block literal has no matching closing token sequence")
