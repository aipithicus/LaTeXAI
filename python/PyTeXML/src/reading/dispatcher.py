"""Structural execution routing over one source-preserving reader cursor.

Execute only resolved local reading effects in an established active context.
Literal, stored-definition and skipped-branch scanning is delegated to dedicated
scanners. Only constant conditionals execute here. Package discovery, expansion
and master.tex assembly remain outside this slice. Unsupported behavior leaves
a located boundary and unchanged residue.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .context import ExecutionMode, ReaderContext
from .contracts import (
    ConditionalRule, EffectiveReadingProfile, LiteralRegion, ReadingBoundary, ReadingIssue,
    ReadingKnowledge, SkippedRegion, StoredDefinition, require_resolved,
)
from .definition_scanner import DefinitionScanner
from .literal_scanner import LiteralScanner
from .skipped_scanner import SkippedBranchScanner, SkippedScan
from .spans import SourceSpan
from .tex_reader import CatCode, EventKind, InvalidCharacterError, ReadEvent, TexReader, TokenKind


@dataclass(frozen=True, slots=True)
class _GroupFrame:
    kind: str
    opening: SourceSpan


@dataclass(slots=True)
class _ConditionalFrame:
    opening: SourceSpan
    truth: bool
    in_alternative: bool = False


class StructuralDispatcher:
    """Route active events and preserve original source spans.

    Applied directives and group tokens retain their original ReadEvent. The
    dispatcher owns its structural group stack; caller-created lexical scopes
    cannot be closed by source. A boundary retains state at the stopping point,
    without repairing groups or rolling back effects already executed. Conditionals
    have an independent stack and create no lexical scopes. EOF in executed text
    with unclosed structure anchors the diagnostic to an opener with empty residue.
    """

    def __init__(self, reader: TexReader, context: ReaderContext, knowledge: ReadingKnowledge):
        self.literals = LiteralScanner(reader, context, knowledge)
        self.definitions = DefinitionScanner(reader, context)
        self.skipped = SkippedBranchScanner(reader, context, knowledge)
        self.reader, self.context, self.knowledge = reader, context, knowledge
        self._base_scope_depth = context.scope_depth
        self._groups: list[_GroupFrame] = []
        self._conditionals: list[_ConditionalFrame] = []
        self._skip_start: int | None = None
        self._pending_skip: SkippedScan | None = None
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

    def next_item(self) -> ReadEvent | LiteralRegion | StoredDefinition | SkippedRegion | ReadingBoundary | None:
        if self.halted or self._finished:
            return None
        reader, context = self.reader, self.context
        # A skipped scan has consumed its delimiter, but it is still owed to the
        # output stream. A context failure here must retain that source too.
        cursor_span = (self._pending_skip.terminator.span if self._pending_skip is not None
                       else reader.source_span(reader.position, reader.position))
        if context.mode != ExecutionMode.ACTIVE_EXECUTION:
            return self._boundary(cursor_span, "inactive_context",
                                  "An owning scanner must handle this execution mode")
        if (reader.catcodes is not context.catcodes or reader.endline_char != context.endlinechar
                or context.scope_depth != self._base_scope_depth + len(self._groups)):
            return self._boundary(cursor_span, "context_changed",
                                  "Reader parameters or scope ownership changed outside the dispatcher")
        if self._skip_start is not None:
            return self._scan_skipped()
        if self._pending_skip is not None:
            pending, self._pending_skip = self._pending_skip, None
            try:
                self._conditional(pending.rule, pending.terminator.span)
                return pending.terminator
            except ReadingIssue as error:
                return self._boundary(pending.terminator.span, error.reason, error.detail)
        try:
            event = reader.next_event()
        except InvalidCharacterError as error:
            return self._boundary(error.span, "invalid_character", str(error))
        if event is None:
            if self._conditionals:
                return self._boundary(self._conditionals[-1].opening, "unclosed_conditional",
                                      f"EOF with {len(self._conditionals)} unclosed conditional(s)",
                                      remainder_start=len(reader.text))
            if self._groups:
                return self._boundary(self._groups[-1].opening, "unclosed_group",
                                      f"EOF with {len(self._groups)} unclosed source group(s)",
                                      remainder_start=len(reader.text))
            self._finished = True
            return None
        if event.token is None:
            return event
        token = event.token
        definition = context.lookup_definition(token.value, token.kind)
        if definition is not None:
            return self._boundary(event.span, "stored_macro",
                                  f"Stored macro {token.value!r} requires interpretation; defined at "
                                  f"{definition.span.basis.source_id}:{definition.span.start}")
        if event.kind != EventKind.TOKEN:
            # Implicit paragraph tokens normally pass through, but a stored
            # redefinition must block that route just like an explicit command.
            return event
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
            if profile.family == "conditional":
                self._require(profile.conditional is not None and profile.action is None
                              and not profile.grammar and not profile.catcode_overrides
                              and not profile.catcode_layers and not profile.reader_parameters
                              and not profile.interpolations and not profile.active_options
                              and profile.terminator is None and profile.state_management is None,
                              "unsupported_conditional", "Conditional requires a standalone nesting/evaluation rule")
                self._conditional(profile.conditional, event.span)
                return event
            if profile.family == "stored_definition":
                definition = self.definitions.read(event.span.start, profile)
                context.record_definition(definition)
                return definition
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
                # The direct environment route must respect author redefinitions
                # of the entry/exit commands as well as of the opener itself.
                for command in (name, "end" + name):
                    meaning = context.lookup_definition(command)
                    self._require(meaning is None, "stored_macro",
                                  f"Environment command {command!r} has a stored definition")
                profile = require_resolved(self.knowledge.resolve_environment(name))
                self._require(profile.grammar.get("handler") == "token_delimited"
                              and profile.grammar.get("arity") == 0,
                              "unsupported_literal_grammar", "Environment requires an unsupported header or body handler")
            return self.literals.read(event.span.start, profile)
        except ReadingIssue as error:
            return self._boundary(event.span, error.reason, error.detail)
        except InvalidCharacterError as error:
            return self._boundary(event.span, "invalid_character", str(error))

    def _conditional(self, rule: ConditionalRule, span: SourceSpan) -> None:
        """Own execution and stack changes; conditionals do not create scopes."""
        if rule.role == "opener":
            self._require(rule.evaluation in {"always_true", "always_false"},
                          "unsupported_conditional", "Conditional predicate requires interpretation")
            truth = rule.evaluation == "always_true"
            self._conditionals.append(_ConditionalFrame(span, truth))
            if not truth:
                self._skip_start = span.end
            return
        self._require(rule.evaluation is None, "unsupported_conditional",
                      "Only conditional openers may have an evaluation rule")
        self._require(rule.role in {"alternative", "case_alternative", "terminator"},
                      "unsupported_conditional", "Unknown conditional role")
        self._require(bool(self._conditionals), "unmatched_conditional", "No conditional is available to close or branch")
        frame = self._conditionals[-1]
        if rule.role == "terminator":
            self._conditionals.pop()
        elif rule.role == "alternative":
            self._require(not frame.in_alternative, "extra_conditional_alternative",
                          "This conditional already entered its alternative")
            frame.in_alternative = True
            if frame.truth:
                self._skip_start = span.end
        else:
            raise ReadingIssue("unexpected_case_alternative", "A case alternative cannot branch this boolean conditional")

    def _scan_skipped(self) -> SkippedRegion | ReadingBoundary:
        frame = self._conditionals[-1]
        try:
            scanned = self.skipped.read(stop_at_alternative=not frame.in_alternative)
        except ReadingIssue as error:
            return self._boundary(frame.opening, error.reason, error.detail, remainder_start=self._skip_start)
        except InvalidCharacterError as error:
            return self._boundary(error.span, "invalid_character", str(error), remainder_start=self._skip_start)
        self._skip_start = None
        self._pending_skip = scanned
        return SkippedRegion(scanned.span, frame.opening, "else" if frame.in_alternative else "then")

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

    def __iter__(self) -> Iterator[ReadEvent | LiteralRegion | StoredDefinition | SkippedRegion | ReadingBoundary]:
        while (item := self.next_item()) is not None:
            yield item
