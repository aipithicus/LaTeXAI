"""Structural execution routing over one source-preserving reader cursor.

Execute only resolved local reading effects in an established active context.
Literal grammar is delegated to LiteralScanner. Definition collection, conditional
execution, package discovery, expansion and master.tex assembly remain outside
this slice. Unsupported behavior leaves a located boundary and unchanged residue.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .context import ExecutionMode, ReaderContext
from .contracts import (
    EffectiveReadingProfile, LiteralRegion, ReadingBoundary, ReadingIssue,
    ReadingKnowledge, require_resolved,
)
from .literal_scanner import LiteralScanner
from .tex_reader import CatCode, EventKind, InvalidCharacterError, ReadEvent, SourceSpan, TexReader, TokenKind


@dataclass(frozen=True, slots=True)
class _GroupFrame:
    kind: str
    opening: SourceSpan


class StructuralDispatcher:
    """Route active events and preserve original source spans.

    Applied directives and group tokens retain their original ReadEvent. The
    dispatcher owns its structural group stack; caller-created lexical scopes
    cannot be closed by source. A boundary retains state at the stopping point,
    without repairing groups or rolling back effects already executed. EOF with
    unclosed groups anchors the diagnostic to an opener and has empty residue.
    """

    def __init__(self, reader: TexReader, context: ReaderContext, knowledge: ReadingKnowledge):
        self.literals = LiteralScanner(reader, context, knowledge)
        self.reader, self.context, self.knowledge = reader, context, knowledge
        self._base_scope_depth = context.scope_depth
        self._groups: list[_GroupFrame] = []
        self.halted = False
        self._finished = False

    def _boundary(self, span: SourceSpan, reason: str, detail: str,
                  *, remainder_start: int | None = None) -> ReadingBoundary:
        self.halted = True
        start = span.start if remainder_start is None else remainder_start
        return ReadingBoundary(span, self.reader.source_span(start, len(self.reader.text)), reason, detail)

    @staticmethod
    def _require(condition: bool, reason: str, detail: str) -> None:
        if not condition:
            raise ReadingIssue(reason, detail)

    def next_item(self) -> ReadEvent | LiteralRegion | ReadingBoundary | None:
        if self.halted or self._finished:
            return None
        reader, context = self.reader, self.context
        cursor_span = reader.source_span(reader.position, reader.position)
        if context.mode != ExecutionMode.ACTIVE_EXECUTION:
            return self._boundary(cursor_span, "inactive_context",
                                  "An owning scanner must handle this execution mode")
        if (reader.catcodes is not context.catcodes or reader.endline_char != context.endlinechar
                or context.scope_depth != self._base_scope_depth + len(self._groups)):
            return self._boundary(cursor_span, "context_changed",
                                  "Reader parameters or scope ownership changed outside the dispatcher")
        try:
            event = reader.next_event()
        except InvalidCharacterError as error:
            return self._boundary(error.span, "invalid_character", str(error))
        if event is None:
            if self._groups:
                return self._boundary(self._groups[-1].opening, "unclosed_group",
                                      f"EOF with {len(self._groups)} unclosed source group(s)",
                                      remainder_start=len(reader.text))
            self._finished = True
            return None
        if event.kind != EventKind.TOKEN or event.token is None:
            return event
        token = event.token
        if token.kind == TokenKind.ACTIVE_CHARACTER:
            return self._boundary(event.span, "active_character", "Active character meaning is unresolved")
        if token.catcode in {CatCode.MATH_SHIFT, CatCode.ALIGNMENT_TAB}:
            return self._boundary(event.span, "unsupported_structure",
                                  "Math and alignment require their own mode and scope handling")
        try:
            if token.catcode in {CatCode.BEGIN_GROUP, CatCode.END_GROUP}:
                profile = require_resolved(self.knowledge.resolve_group(token.catcode))
                expected_action = ("push_lexical_scope" if token.catcode == CatCode.BEGIN_GROUP
                                   else "pop_lexical_scope")
                self._require(profile.action == expected_action, "unsupported_operation",
                              "Group binding does not match this token's grouping category")
                self._effect(profile, event.span)
                return event
            if token.kind != TokenKind.CONTROL_SEQUENCE:
                return event
            profile = require_resolved(self.knowledge.resolve_command(token.value))
            if profile.action is not None:
                self._effect(profile, event.span)
                return event
            if profile.family in {"grouping", "catcode_mutator"}:
                raise ReadingIssue("unsupported_operation", "Reading effect has no executable action")
            if profile.grammar.get("handler") == "environment_name":
                self._require(profile.grammar.get("argument") == "braced_literal_name",
                              "unsupported_literal_grammar", "Only literal braced environment names are supported")
                with context.argument_scanning():
                    name = self._environment_name()
                profile = require_resolved(self.knowledge.resolve_environment(name))
                self._require(profile.grammar.get("handler") == "token_delimited"
                              and profile.grammar.get("arity") == 0,
                              "unsupported_literal_grammar", "Environment requires an unsupported header or body handler")
            return self.literals.read(event.span.start, profile)
        except ReadingIssue as error:
            return self._boundary(event.span, error.reason, error.detail)
        except InvalidCharacterError as error:
            return self._boundary(event.span, "invalid_character", str(error))

    def _effect(self, profile: EffectiveReadingProfile, span: SourceSpan) -> None:
        """Route generic action identities; command spellings remain in bindings."""
        self._require(not profile.grammar and not profile.interpolations
                      and not profile.active_options and profile.terminator is None,
                      "unsupported_reading_effect", "Reading effect requires additional scanning or interpretation")
        state = profile.state_management
        self._require(state is None or state.scope == "local", "unsupported_reading_effect",
                      "Only local reading effects are supported")
        if profile.action in {"push_lexical_scope", "pop_lexical_scope"}:
            self._require(not profile.catcode_overrides and not profile.catcode_layers
                          and not profile.reader_parameters,
                          "unsupported_reading_effect", "Combined grouping and assignments are unsupported")
            kind = state.group_kind if state else None
            self._require(kind in {"simple", "semi_simple"}, "unsupported_reading_effect",
                          "Grouping requires a supported group kind")
            if profile.action == "push_lexical_scope":
                self.context.apply_profile(profile)
                self._groups.append(_GroupFrame(kind, span))
            else:
                self._require(bool(self._groups), "unmatched_group", "No source group is available to close")
                self._require(self._groups[-1].kind == kind, "mismatched_group",
                              f"Cannot close {self._groups[-1].kind} group with {kind} closer")
                self.context.apply_profile(profile)
                self._groups.pop()
        else:
            self._require(profile.action in {"assign_catcode", "expl3_lexical_enter", "expl3_lexical_exit"},
                          "unsupported_operation", f"No execution route for {profile.action!r}")
            self._require(not (set(profile.reader_parameters) - {"endlinechar"}),
                          "unsupported_reading_effect", "Unknown reader parameter")
            self.context.apply_profile(profile)
        # Updating the configured parameter does not change the already loaded
        # physical line or discard pending ^^ conversions. Never reset N/M/S.
        self.reader.endline_char = self.context.endlinechar

    def _environment_name(self) -> str:
        """Read a non-expanding argument; braces here are not execution groups."""
        token = self.reader.next_token()
        while token is not None and token.catcode == CatCode.SPACE:
            token = self.reader.next_token()
        self._require(token is not None and token.catcode == CatCode.BEGIN_GROUP,
                      "unsupported_literal_grammar", "Expected a braced environment name")
        name = []
        while (token := self.reader.next_token()) is not None:
            if token.catcode == CatCode.END_GROUP:
                self._require(bool(name), "unsupported_literal_grammar", "Empty environment name")
                return "".join(name)
            self._require(token.kind == TokenKind.CHARACTER and token.catcode in {CatCode.LETTER, CatCode.OTHER},
                          "unsupported_literal_grammar", "Computed or nested environment names need an argument interpreter")
            name.append(token.value)
        raise ReadingIssue("unclosed_header", "Environment name has no closing brace")

    def __iter__(self) -> Iterator[ReadEvent | LiteralRegion | ReadingBoundary]:
        while (item := self.next_item()) is not None:
            yield item
