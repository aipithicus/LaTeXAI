"""Structural execution routing over one source-preserving reader cursor.

Execute only resolved local reading effects in an established active context.
Literal, stored-definition and skipped-branch scanning is delegated to dedicated
scanners. Constant and established boolean conditionals execute here. Package discovery, expansion
and master.tex assembly remain outside this slice. Unsupported behavior leaves
a located boundary and unchanged residue.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator

from .context import ExecutionMode, ReaderContext
from .contracts import (
    ConditionalRule, EffectiveReadingProfile, LiteralRegion, ReadingBoundary, ReadingIssue,
    ReadingKnowledge, SkippedRegion, StoredDefinition, SourceCommand, SourceEnd, require_resolved,
    DeferredRegion, UnresolvedBindingResult, UnresolvedReason, BooleanMeaning, CommandDefinition,
    EnvironmentDefinition, UncertainMeaning,
)
from .boolean_scanner import declaration as boolean_declaration
from .argument_scanner import ArgumentScanner, key_values
from .configuration import entries, configured_options
from .assignment_scanner import AssignmentScanner
from .environment_registry import declarations, resolve_environment
from .environment_scanner import EnvironmentScanner
from .definition_scanner import DefinitionScanner
from .deferred_scanner import DeferredScanner
from .literal_scanner import LiteralScanner
from .skipped_scanner import SkippedBranchScanner, SkippedScan
from .conditional_scanner import ConditionalScanner
from .predicates import compare_characters
from .spans import SourceSpan
from .units import UnitRegistry
from .options import OptionBody, OptionScope, option_names
from .token_cursor import TokenCursor
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


@dataclass(frozen=True, slots=True)
class InputRecovery:
    """Preparation-only resumption point; abandoning input is not TeX execution."""
    owner: object
    reader: TexReader
    context: ReaderContext
    parents: tuple
    groups: tuple
    conditionals: tuple
    environments: tuple
    replays: dict
    options: OptionScope | None


class StructuralDispatcher:
    """Route active events and preserve original source spans.

    Applied directives and group tokens retain their original ReadEvent. The
    dispatcher owns its structural group stack; caller-created lexical scopes
    cannot be closed by source. A boundary retains state at the stopping point,
    without repairing groups or rolling back effects already executed. Conditionals
    have an independent stack and create no lexical scopes. EOF in executed text
    with unclosed structure anchors the diagnostic to an opener with empty residue.
    """

    def __init__(self, reader: TexReader, context: ReaderContext, knowledge: ReadingKnowledge,
                 *, source_commands: bool = False, preparation: bool = False, units: UnitRegistry | None = None,
                 options: OptionScope | None = None):
        self.literals = LiteralScanner(reader, context, knowledge)
        self.definitions = DefinitionScanner(reader, context)
        self.environments = EnvironmentScanner(reader, context)
        self.skipped = SkippedBranchScanner(reader, context, knowledge)
        self.reader, self.context, self.knowledge = reader, context, knowledge
        self._base_scope_depth = context.scope_depth
        self._groups: list[_GroupFrame] = []
        self._conditionals: list[_ConditionalFrame] = []
        self._skip_start: int | None = None
        self._pending_skip: SkippedScan | None = None
        self.halted = False
        self._finished = False
        self.source_commands = source_commands
        # Preparation captures ordinary uninterpreted expressions and continues.
        # The default execution API retains its strict boundary behavior.
        self.preparation = preparation
        self._parents: list[tuple[TexReader, dict[str, CatCode], OptionScope | None]] = []
        self.options = options
        self._environment_stack: list[str] = []
        self._root_ended = False
        self._replays = {}
        self.units = units if units is not None else UnitRegistry()

    def input_recovery(self) -> InputRecovery:
        """Snapshot only at an active handoff, before entering retained code."""
        if not self.preparation or self.halted or self._finished or self._pending_skip or self._skip_start is not None:
            raise ValueError("Recovery requires an active preparation handoff")
        parents, options = self._copy_option_stack(self._parents, self.options)
        return InputRecovery(self, self.reader, self.context.copy(), parents,
                             tuple(self._groups), tuple(replace(f) for f in self._conditionals),
                             tuple(self._environment_stack), dict(self._replays),
                             options)

    @staticmethod
    def _copy_option_stack(parents, options):
        copies = {}
        def copy(scope):
            if scope is None:
                return None
            if id(scope) not in copies:
                copies[id(scope)] = scope.copy()
            return copies[id(scope)]
        return tuple((reader, saved, copy(scope)) for reader, saved, scope in parents), copy(options)

    def resume_input(self, saved: InputRecovery) -> None:
        """Resume after separately retained unresolved code under explicit assumptions.

        The preparation owner must preserve the code and record the missing effects.
        Strict execution never uses this route. The caller's cursor was suspended,
        so no source is rescanned and no I/O is needed.
        """
        if not self.preparation or saved.owner is not self or not self.halted:
            raise ValueError("Invalid preparation recovery")
        self.context.restore_from(saved.context)
        parents, self.options = self._copy_option_stack(saved.parents, saved.options)
        self._parents = list(parents)
        self._groups = list(saved.groups)
        self._conditionals = [replace(f) for f in saved.conditionals]
        self._environment_stack = list(saved.environments)
        self._replays = dict(saved.replays)
        self._skip_start = self._pending_skip = None
        self.halted = self._finished = False
        self._set_reader(saved.reader)

    def _set_reader(self, reader: TexReader) -> None:
        self.reader = reader
        reader.endline_char = self.context.endlinechar
        self.literals = LiteralScanner(reader, self.context, self.knowledge)
        self.definitions = DefinitionScanner(reader, self.context)
        self.environments = EnvironmentScanner(reader, self.context)
        self.skipped = SkippedBranchScanner(reader, self.context, self.knowledge)

    def enter_source(self, reader: TexReader, *, catcode_overrides: dict[str, int] | None = None,
                     options: OptionScope | None = None) -> None:
        """Suspend one mouth; execution scopes/conditionals belong to the document."""
        if not self.source_commands or self.halted or self._finished or self._pending_skip or self._skip_start is not None:
            raise ValueError("Input may only start at an active source-command boundary")
        if reader.catcodes is not self.context.catcodes:
            raise ValueError("Input occurrences must share the document's catcode table")
        saved = {char: self.context.catcodes[char] for char in catcode_overrides or {}}
        self._parents.append((self.reader, saved, self.options))
        if options is not None:
            self.options = options
        for char, code in (catcode_overrides or {}).items():
            self.context.catcodes[char] = code
        self._set_reader(reader)

    def _boundary(self, span: SourceSpan, reason: str, detail: str,
                  *, remainder_start: int | None = None) -> ReadingBoundary:
        self.halted = True
        start = span.start if remainder_start is None else remainder_start
        return ReadingBoundary(span, self.reader.source_span(start, len(self.reader.text)), reason, detail)

    @staticmethod
    def _require(condition: bool, reason: str, detail: str) -> None:
        if not condition:
            raise ReadingIssue(reason, detail)

    def next_item(self) -> ReadEvent | LiteralRegion | StoredDefinition | EnvironmentDefinition | SkippedRegion | ReadingBoundary | SourceCommand | SourceEnd | DeferredRegion | None:
        item = self._next_item()
        return self._identify(item) if item is not None and not isinstance(item, ReadEvent) else item

    def _identify(self, item, parent_id=None):
        if item.unit_id is not None:
            self.units.require(item.unit_id, item.span)
            return item
        activity = "unresolved" if parent_id else "skipped" if isinstance(item, SkippedRegion) else "reached"
        identifier = self.units.add(item.span, type(item).__name__, parent_id, activity=activity)
        item = replace(item, unit_id=identifier)
        if isinstance(item, DeferredRegion):
            # A captured command is another view of the same observed unit.
            item = replace(item, command=replace(item.command, unit_id=identifier) if item.command else None,
                           observations=tuple(self._identify(o, identifier) for o in item.observations))
        if isinstance(item, LiteralRegion):
            item = replace(item, interpolations=tuple(self._identify(o, identifier) for o in item.interpolations))
        return item

    def _next_item(self):
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
            if reader in self._replays:
                parent, closing, name, metadata = self._replays.pop(reader)
                self._set_reader(parent)
                return SourceCommand(closing, name, "transparent_end", (), metadata)
            if self._parents:
                end = SourceEnd(reader.terminated_span or reader.source_span(len(reader.text), len(reader.text)),
                                "endinput" if reader.terminated_span else "eof")
                parent, saved, self.options = self._parents.pop()
                for char, code in saved.items():
                    self.context.catcodes[char] = code
                self._set_reader(parent)
                return end
            if self._conditionals:
                return self._boundary(self._conditionals[-1].opening, "unclosed_conditional",
                                      f"EOF with {len(self._conditionals)} unclosed conditional(s)",
                                      remainder_start=len(reader.text))
            if self._groups:
                return self._boundary(self._groups[-1].opening, "unclosed_group",
                                      f"EOF with {len(self._groups)} unclosed source group(s)",
                                      remainder_start=len(reader.text))
            self._finished = True
            if self.source_commands and not self._root_ended:
                self._root_ended = True
                return SourceEnd(reader.terminated_span or reader.source_span(len(reader.text), len(reader.text)),
                                 "endinput" if reader.terminated_span else "eof")
            return None
        if event.token is None:
            return event
        token = event.token
        meaning = context.lookup_meaning(token.value, token.kind)
        definition = context.lookup_definition(token.value, token.kind)
        if definition is not None and not self.preparation:
            return self._boundary(event.span, "stored_macro",
                                  f"Stored macro {token.value!r} requires interpretation; defined at "
                                  f"{definition.span.basis.source_id}:{definition.span.start}")
        if event.kind != EventKind.TOKEN:
            # Implicit paragraph tokens normally pass through, but a stored
            # redefinition must block that route just like an explicit command.
            return event
        if token.kind == TokenKind.ACTIVE_CHARACTER and not self.preparation:
            return self._boundary(event.span, "active_character", "Active character meaning is unresolved")
        if token.catcode in {CatCode.MATH_SHIFT, CatCode.ALIGNMENT_TAB} and not self.preparation:
            return self._boundary(event.span, "unsupported_structure",
                                  "Math and alignment require their own mode and scope handling")
        try:
            deferred = DeferredScanner(reader, context)
            if isinstance(meaning, UncertainMeaning):
                raise ReadingIssue("uncertain_meaning", f"{token.value!r} may have been redefined at {meaning.span}")
            if (isinstance(reader, TokenCursor) and token.kind == TokenKind.CHARACTER
                    and token.catcode not in {CatCode.SPACE, CatCode.BEGIN_GROUP, CatCode.END_GROUP}):
                raise ReadingIssue("option_body", "Option text requires interpretation beyond reading effects")
            if isinstance(meaning, BooleanMeaning):
                if self.preparation and meaning.uncertain is not None and meaning.target is None:
                    return self._capture_conditional(token, ConditionalRule("opener", "deferred", 0))
                self._require(meaning.uncertain is None, "uncertain_boolean",
                              f"Meaning of {token.value!r} may have changed in unexecuted source at "
                              f"{meaning.uncertain}")
                if meaning.target is not None:
                    truth = self._boolean_value(meaning.source)
                    context.record_meaning(meaning.target, BooleanMeaning(event.span, truth))
                else:
                    self._conditional(context.conditional_rule(token.value, self.knowledge), event.span)
                return event
            if definition is not None:
                return self._deferred(deferred.command(token, "stored_macro", f"Unexpanded {token.value!r}; definition at "
                    f"{definition.span.basis.source_id}:{definition.span.start}"))
            if token.kind == TokenKind.ACTIVE_CHARACTER:
                return self._deferred(DeferredRegion(event.span, "active_character", "Active character retained without expansion", (token,)))
            if self.preparation and token.catcode == CatCode.MATH_SHIFT:
                return self._deferred(deferred.math(token))
            if self.preparation and token.catcode == CatCode.ALIGNMENT_TAB:
                return DeferredRegion(event.span, "alignment_interpretation", "Alignment retained without interpretation", (token,))
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
            resolved = self.knowledge.resolve_command(token.value)
            if self.preparation and isinstance(resolved, UnresolvedBindingResult):
                if resolved.reason == UnresolvedReason.UNKNOWN_CONSTRUCT:
                    return self._deferred(deferred.command(token, resolved.reason.value, resolved.detail))
                if resolved.reason == UnresolvedReason.PACKAGE_NOT_LOADED:
                    inspect = getattr(self.knowledge, "source_command_syntax", None)
                    syntax = inspect(token.value) if inspect else None
                    if syntax is not None:
                        command = ArgumentScanner(reader, context).read(event.span, syntax)
                        return self._deferred(DeferredRegion(command.span, resolved.reason.value, resolved.detail,
                                              (token,) + tuple(t for arg in command.arguments for t in arg.tokens),
                                              command, syntax.binding_id))
                    # An inactive literal binding can require a different mouth.
                    # Do not treat its body as ordinary executed TeX.
            profile = require_resolved(resolved)
            if profile.family == "configuration_command":
                return self._configuration(event.span, profile)
            if profile.family == "collected_environment_definition":
                definition = self.environments.definition(event.span.start, profile)
                known = (context.lookup_environment(definition.name) is not None
                         or context.lookup_meaning(definition.name) is not None
                         or isinstance(self.knowledge.resolve_environment(definition.name), EffectiveReadingProfile)
                         or isinstance(self.knowledge.resolve_command(definition.name), EffectiveReadingProfile))
                end_known = (context.lookup_meaning("end" + definition.name) is not None
                             or isinstance(self.knowledge.resolve_command("end" + definition.name), EffectiveReadingProfile))
                self._require(not (known or end_known) or definition.target_requirement != "absent",
                              "definition_conflict", f"{definition.name!r} already has an established meaning")
                definition = self._identify(replace(definition, target_check="known_present" if known else "unverified"))
                context.record_collected_environment(definition)
                return definition
            if profile.family == "option_control":
                self._require(not isinstance(reader, TokenCursor), "option_body",
                              "Nested option declarations/processing require further resolution")
                command = ArgumentScanner(reader, context).read(event.span, profile)
                return self._options(command)
            if profile.family == "conditional_factory":
                self._require(profile.grammar.get("handler") == "boolean_declaration"
                              and profile.state_management is not None
                              and profile.state_management.scope == "local",
                              "unsupported_boolean_declaration", "Boolean declaration needs a local recipe")
                command = boolean_declaration(reader, context, event.span, profile)
                # Resolve before publishing any of the generated meanings.
                truth = self._boolean_value(profile.grammar["initial"])
                target = command.metadata["target"]
                stem = target[len(profile.grammar["target_prefix"]):]
                context.record_meaning(target, BooleanMeaning(command.span, truth))
                for suffix, source in profile.grammar["setters"].items():
                    context.record_meaning(stem + suffix, BooleanMeaning(command.span, target=target, source=source))
                return command
            if profile.family == "environment_factory":
                command = ArgumentScanner(reader, context).read(event.span, profile)
                for declaration in declarations(command, self.knowledge):
                    context.record_environment(declaration)
                return command
            if profile.family == "catcode_assignment":
                self._require(profile.grammar.get("handler") == "literal_catcode_assignment"
                              and profile.state_management.scope == "local",
                              "unsupported_reading_effect", "Assignment needs a supported local scanner")
                command = AssignmentScanner(reader, context).catcode(event.span, profile)
                context.catcodes[command.metadata["character"]] = command.metadata["category"]
                return command
            if profile.family == "source_command":
                self._require(self.source_commands or profile.action in {"reading_noop", "capture_setting"},
                              "unsupported_operation", "Source commands require an input owner")
                checkpoint = reader.checkpoint()
                try:
                    command = ArgumentScanner(reader, context).read(event.span, profile)
                except ReadingIssue:
                    if not self.preparation or profile.action not in {"opaque", "metadata", "citation"}:
                        raise
                    # Source packages may overload a data command's signature.
                    # Preserve the complete observational envelope without applying
                    # the mismatched argument grammar or hiding later source.
                    reader.restore(checkpoint)
                    return self._deferred(deferred.command(token, "argument_behavior",
                        "Entry argument grammar does not match this reached data command"))
                if command.action == "capture_setting":
                    value = command.argument("value")
                    if command.metadata["value_kind"] == "tokens":
                        self.environments.validate_final(value)
                    context.record_capture_setting(command.metadata["key"], value)
                    return command
                if command.action in {"opaque", "metadata", "citation"} and any(
                        t.kind in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER}
                        for arg in command.arguments for t in arg.tokens):
                    self.defer_effects(command.span)
                if command.action == "end_input":
                    reader.end_input_after_line()
                elif command.action == "environment_end":
                    name = command.value("name")
                    self._require(bool(self._environment_stack) and self._environment_stack[-1] == name
                                  and bool(self._groups) and self._groups[-1].kind == "environment:" + name,
                                  "mismatched_environment", f"No matching environment group for {name}")
                    self._environment_stack.pop()
                    self._groups.pop()
                    context.pop_scope()
                    reader.endline_char = context.endlinechar
                    env = require_resolved(self.knowledge.resolve_environment(name))
                    command = SourceCommand(command.span, command.name, command.action, command.arguments, env.tex_mechanics)
                return command
            if profile.family == "conditional":
                self._require(profile.conditional is not None and profile.action is None
                              and not profile.grammar and not profile.catcode_overrides
                              and not profile.catcode_layers and not profile.reader_parameters
                              and not profile.interpolations and not profile.active_options
                              and profile.terminator is None and profile.state_management is None,
                              "unsupported_conditional", "Conditional requires a standalone nesting/evaluation rule")
                command = compare_characters(reader, context, token, profile.conditional)
                if command is not None:
                    self._conditional(ConditionalRule("opener", "always_true" if command.metadata["truth"] else "always_false"), command.span)
                    return command
                if (self.preparation and profile.conditional.role == "opener"
                        and profile.conditional.evaluation == "deferred"):
                    return self._capture_conditional(token, profile.conditional)
                self._conditional(profile.conditional, event.span)
                return event
            if profile.family == "stored_definition":
                definition = self.definitions.read(event.span.start, profile)
                if isinstance(definition, CommandDefinition):
                    known = (context.lookup_meaning(definition.target.value) is not None
                             or isinstance(self.knowledge.resolve_command(definition.target.value), EffectiveReadingProfile))
                    self._require(not known or definition.target_requirement != "absent",
                                  "definition_conflict", f"{definition.target.value!r} already has an established meaning")
                    # An incomplete binding inventory cannot prove undefinedness.
                    # Registration records a source declaration, not validation of
                    # its precondition or execution of its replacement text.
                    definition = replace(definition, target_check="known_present" if known else "unverified")
                definition = self._identify(definition)
                context.record_definition(definition)
                return definition
            if profile.action is not None:
                self._effect(profile, event.span)
                return event
            if profile.family in {"grouping", "catcode_mutator"}:
                raise ReadingIssue("unsupported_operation", "Reading effect has no executable action")
            self._require(not isinstance(reader, TokenCursor), "option_body",
                          "Literal and environment reading requires a character-input contract")
            if profile.grammar.get("handler") == "environment_name":
                self._require(profile.grammar.get("argument") == "braced_literal_name",
                              "unsupported_literal_grammar", "Only literal braced environment names are supported")
                with context.argument_scanning():
                    name = self._environment_name()
                declaration = context.lookup_environment(name)
                # The direct environment route must respect author redefinitions
                # of the entry/exit commands as well as of the opener itself.
                for command in (name, "end" + name):
                    meaning = context.lookup_meaning(command)
                    self._require(meaning is None or (isinstance(declaration, EnvironmentDefinition) and meaning is declaration), "stored_macro",
                                  f"Environment command {command!r} has a stored definition")
                if isinstance(declaration, EnvironmentDefinition):
                    return self._deferred(self.environments.collect(event.span, declaration))
                resolved = resolve_environment(name, None, context, self.knowledge)
                if (self.preparation and isinstance(resolved, UnresolvedBindingResult)
                        and resolved.reason == UnresolvedReason.UNKNOWN_CONSTRUCT):
                    return self._deferred(deferred.environment(event.span, name, protect=self._protect_deferred_environment))
                profile = require_resolved(resolved)
                if profile.grammar.get("has_optional_arguments"):
                    with context.argument_scanning():
                        options = ArgumentScanner(reader, context).group("options", optional=True)
                    profile = require_resolved(resolve_environment(name, configured_options(profile, options, context), context, self.knowledge))
                elif profile.configuration:
                    profile = require_resolved(resolve_environment(name, configured_options(profile, None, context), context, self.knowledge))
                if profile.family == "structural_environment" and self.source_commands:
                    header = ArgumentScanner(reader, context).read(event.span, profile)
                    context.push_scope()
                    self._groups.append(_GroupFrame("environment:" + name, event.span))
                    self._environment_stack.append(name)
                    return SourceCommand(header.span, name, "environment_begin", header.arguments, profile.tex_mechanics)
                self._require(profile.grammar.get("handler") in {"token_delimited", "physical_line_literal"}
                              and profile.grammar.get("arity") == 0,
                              "unsupported_literal_grammar", "Environment requires an unsupported header or body handler")
            region = self.literals.read(event.span.start, profile, defer_interpolation=self.preparation)
            for interpolation in region.interpolations:
                self.defer_effects(interpolation.span)
            if region.classification.category == "transparent_block":
                self._require(profile.grammar.get("body_start") == "next_physical_line"
                              and profile.terminator.requires_column_zero
                              and not profile.terminator.trailing_content_allowed,
                              "unsupported_literal_grammar", "Transparent replay needs whole physical lines")
                replay = reader.line_window(region.body)
                metadata = {"semantic_role": region.classification.semantic_role,
                            "closing_source": reader.source_slice(region.closing)}
                self._replays[replay] = (reader, region.closing, region.name, metadata)
                self._set_reader(replay)
                return SourceCommand(region.opening, region.name, "transparent_begin", (), metadata)
            return region
        except ReadingIssue as error:
            return self._boundary(event.span, error.reason, error.detail)
        except InvalidCharacterError as error:
            return self._boundary(event.span, "invalid_character", str(error))

    def _configuration(self, opening, profile):
        # Some package headers establish catcodes before collecting arguments.
        # A replay cursor already contains frozen tokens, so it is never retokenized.
        with self.context.lexical_scope():
            if not isinstance(self.reader, TokenCursor):
                for char, code in profile.tex_mechanics["header_catcodes"].items():
                    self.context.catcodes[char] = code
            command = ArgumentScanner(self.reader, self.context).read(opening, profile)
        for name in profile.tex_mechanics.get("unsupported_arguments", ()):
            if command.argument(name) is not None:
                raise ReadingIssue("configuration_header", f"Configuration argument {name!r} requires further resolution")
        contract, state = profile.configuration, self.context.configurations
        namespace = contract["namespace"]
        captured = entries(command.argument("options"))
        if command.action == "define_configuration":
            name = state.name(command.value("name"), contract)
            self._require(bool(name), "configuration_name", "Configuration name must be nonempty")
            state.store("styles", (namespace, name), captured, contract["definition_scope"])
        else:
            resolved = state.resolve(namespace, captured, contract)
            self.knowledge.check_configuration(command.name, state.reading_values(resolved, contract), contract)
            state.store("values", namespace, resolved, contract["assignment_scope"])
        return command

    def _options(self, command: SourceCommand) -> SourceCommand:
        """Capture first, select later, then reuse strict dispatch over frozen tokens.

        Option replay is an effect-only operation. Its source is already captured
        by DeclareOption and is never re-emitted or added to top-level coverage.
        Each selected body must be self-contained with respect to groups and
        conditionals; dependencies and arbitrary macros remain explicit limits.
        """
        scope = self.options
        self._require(scope is not None, "option_context", "Option commands require a package/class load")
        self._require(self.context.scope_depth == scope.depth, "option_scope",
                      "Option controls inside an additional lexical group need further resolution")
        if command.action == "declare_option":
            name = None if command.argument("star") else command.value("name").replace(" ", "")
            scope.declare(name, OptionBody(command.argument("body"), self.reader.text))
            return command
        if command.action == "execute_options":
            plan = scope.defaults(option_names(command.argument("options")))
        else:
            order = command.metadata["starred_order" if command.argument("star") else "order"]
            plan = scope.plan(order)
        saved = self.context.copy()
        definition_checks = []
        try:
            for name, body in plan:
                self._require(not any(t.catcode == CatCode.PARAMETER for t in body.argument.tokens),
                              "option_body", f"Option {name!r} requires parameter-token compilation")
                cursor = TokenCursor(body.argument, body.text, self.context)
                replay = StructuralDispatcher(cursor, self.context, self.knowledge, units=self.units)
                for item in replay:
                    if isinstance(item, (ReadingBoundary, DeferredRegion)):
                        raise ReadingIssue("option_body", f"Option {name!r} requires {item.reason} at "
                                           f"{item.span.basis.source_id}:{item.span.start}: {item.detail}")
                    if isinstance(item, (CommandDefinition, EnvironmentDefinition)) and item.target_check == "unverified":
                        definition_checks.append({"unit_id": item.unit_id, "declaration": item.declaration,
                                                  "target": item.name if isinstance(item, EnvironmentDefinition) else item.target.value,
                                                  "requirement": item.target_requirement})
        except ReadingIssue:
            # Failed bounded resolution publishes no partly applied option state.
            self.context.restore_from(saved)
            raise
        finally:
            self.reader.endline_char = self.context.endlinechar
        if command.action == "process_options":
            scope.processed = True
        return replace(command, metadata={**command.metadata, "selected_options": [name for name, _ in plan],
                                          "definition_checks": definition_checks})

    def _boolean_value(self, name: str) -> bool:
        rule = self.context.conditional_rule(name.removeprefix("\\"), self.knowledge)
        self._require(rule is not None and rule.role == "opener"
                      and rule.evaluation in {"always_true", "always_false"},
                      "unsupported_boolean_meaning", f"{name!r} has no established boolean value")
        return rule.evaluation == "always_true"

    def _deferred(self, region: DeferredRegion) -> DeferredRegion:
        # Bare arithmetic/text math cannot assign meanings. Other unexecuted
        # expressions may redefine a boolean or its setter, even globally.
        if region.reason != "math_interpretation" or any(
                t.kind in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER} for t in region.tokens):
            self.defer_effects(region.span)
        return region

    def defer_effects(self, span):
        """Unknown execution can invalidate live and suspended bounded state."""
        self.context.invalidate_booleans(span)
        for scope in (self.options, *(parent[2] for parent in self._parents)):
            if scope is not None and scope.uncertain is None:
                scope.uncertain = span

    def _capture_conditional(self, token, rule):
        region = ConditionalScanner(self.reader, self.context).read(token, rule, classify=self._observed_conditional,
            protect=lambda t, **kw: self._protect_deferred_environment(t, conditional=True, **kw))
        self.context.invalidate_meanings(region.changed_meanings, region.span)
        return self._deferred(region)

    def _observed_conditional(self, candidate):
        if candidate.kind != TokenKind.CONTROL_SEQUENCE:
            return None
        meaning = self.context.lookup_meaning(candidate.value)
        if isinstance(meaning, BooleanMeaning):
            # Retain its declared nesting role as an explicit assumption;
            # uncertainty prohibits choosing a branch, not source capture.
            return ConditionalRule("opener", "deferred", 0) if meaning.target is None else None
        return self.context.conditional_rule(candidate.value, self.knowledge)

    def observe_conditional_input(self):
        """Capture a candidate file, never dispatch it as an active input."""
        return ConditionalScanner(self.reader, self.context).source(classify=self._observed_conditional,
            protect=lambda t, **kw: self._protect_deferred_environment(t, conditional=True, **kw))

    def _protect_deferred_environment(self, token, *, shadowed=(), conditional=False) -> bool | DeferredRegion | StoredDefinition | EnvironmentDefinition:
        """Locate known protected syntax without executing an unbound body.

        Routing remains here, not in the envelope scanner. Reading effects and
        conditional control flow require the environment's missing contract.
        """
        if token.catcode == CatCode.MATH_SHIFT:
            return DeferredScanner(self.reader, self.context).math(token)
        if token.kind != TokenKind.CONTROL_SEQUENCE:
            return False
        if token.value in shadowed:
            return DeferredScanner(self.reader, self.context).command(
                token, "stored_macro", "Unexecuted definition shadows the entry grammar")
        meaning = self.context.lookup_meaning(token.value)
        if conditional and isinstance(meaning, BooleanMeaning) and meaning.target is not None:
            return DeferredScanner(self.reader, self.context).command(token, "conditional_interpretation",
                "Boolean setter retained without selecting or executing a branch")
        if isinstance(meaning, (StoredDefinition, EnvironmentDefinition)):
            # Observing an invocation inside an already deferred body requires
            # no more execution than observing an unknown command there. Keep
            # its envelope protected; do not dispatch the old binding or body.
            return DeferredScanner(self.reader, self.context).command(
                token, "stored_macro", "Stored invocation inside an unbound environment remains unexpanded")
        if meaning is not None:
            raise ReadingIssue("environment_reading", "A conditional or setter inside an unbound environment needs reading resolution")
        profile = self.knowledge.resolve_command(token.value)
        if isinstance(profile, UnresolvedBindingResult):
            if profile.reason == UnresolvedReason.PACKAGE_NOT_LOADED:
                inspect = getattr(self.knowledge, "source_command_syntax", None)
                syntax = inspect(token.value) if inspect else None
                if syntax is not None:
                    command = ArgumentScanner(self.reader, self.context).read(token.span, syntax)
                    return DeferredRegion(command.span, profile.reason.value, profile.detail,
                        (token,) + tuple(t for arg in command.arguments for t in arg.tokens), command, syntax.binding_id)
            if profile.reason != UnresolvedReason.UNKNOWN_CONSTRUCT:
                raise ReadingIssue(profile.reason.value, profile.detail)
            return DeferredScanner(self.reader, self.context).command(token, profile.reason.value, profile.detail)
        if profile.family == "stored_definition":
            return self.definitions.read(token.span.start, profile)  # capture, never install
        if profile.family == "collected_environment_definition":
            return self.environments.definition(token.span.start, profile)  # capture, never install
        if profile.family in {"conditional", "conditional_factory", "catcode_mutator", "catcode_assignment", "grouping", "environment_factory", "option_control", "configuration_command"}:
            raise ReadingIssue("environment_reading", "Control flow or reading effects inside an unbound environment require resolution")
        if profile.family == "source_command" and profile.action != "environment_end":
            checkpoint = self.reader.checkpoint()
            try:
                command = ArgumentScanner(self.reader, self.context).read(token.span, profile)
            except ReadingIssue:
                if not conditional or profile.action not in {"opaque", "metadata", "citation"}:
                    raise
                # An unexecuted package may overload a data command's signature.
                # Preserve its adjacent groups; do not invent a resolved header.
                self.reader.restore(checkpoint)
                return DeferredScanner(self.reader, self.context).command(token, "argument_behavior",
                    "Entry argument grammar does not match this retained command")
            return DeferredRegion(command.span, "environment_binding", "Source command inside an unbound environment",
                                  (token,) + tuple(t for arg in command.arguments for t in arg.tokens), command, profile.binding_id)
        handler = profile.grammar.get("handler")
        if handler == "inline_character":
            self.literals.read(token.span.start, profile)
            return True
        if handler == "environment_name":
            checkpoint = self.reader.checkpoint()
            with self.context.argument_scanning():
                name = self._environment_name()
            self._require(name not in shadowed and "end" + name not in shadowed,
                          "environment_reading", "Unexecuted definition may change this environment's reading behavior")
            declaration = self.context.lookup_environment(name)
            if isinstance(declaration, EnvironmentDefinition):
                self._require(all(self.context.lookup_meaning(n) is declaration for n in (name, "end" + name)),
                              "environment_reading", "Collected environment entry or exit was redefined")
                return self.environments.collect(token.span, declaration)
            nested = resolve_environment(name, None, self.context, self.knowledge)
            if isinstance(nested, EffectiveReadingProfile) and nested.grammar.get("handler") in {"token_delimited", "physical_line_literal"}:
                if nested.grammar.get("has_optional_arguments"):
                    with self.context.argument_scanning():
                        options = ArgumentScanner(self.reader, self.context).group("options", optional=True)
                    nested = require_resolved(resolve_environment(name, configured_options(nested, options, self.context), self.context, self.knowledge))
                elif nested.configuration:
                    nested = require_resolved(resolve_environment(name, configured_options(nested, None, self.context), self.context, self.knowledge))
                self._require(not nested.interpolations, "environment_reading",
                              "Interpolation inside an unbound environment requires further reading resolution")
                self.literals.read(token.span.start, nested)
                return True
            if isinstance(nested, UnresolvedBindingResult) and nested.reason != UnresolvedReason.UNKNOWN_CONSTRUCT:
                raise ReadingIssue(nested.reason.value, nested.detail)
            self.reader.restore(checkpoint)
        return False

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

    def __iter__(self) -> Iterator[ReadEvent | LiteralRegion | StoredDefinition | SkippedRegion | ReadingBoundary | SourceCommand | SourceEnd | DeferredRegion]:
        while (item := self.next_item()) is not None:
            yield item
