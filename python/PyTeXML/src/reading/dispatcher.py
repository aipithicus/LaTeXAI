"""Structural execution routing over one source-preserving reader cursor.

Execute resolved local operations through the shared engine catalog.
Literal, stored-definition and skipped-branch scanning is delegated to dedicated
scanners. Constant and established boolean conditionals execute here. Package discovery, expansion
and master.tex assembly remain outside this slice. Unsupported behavior leaves
a located boundary and unchanged residue.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections import deque
from typing import Callable, Iterator

from ..engine.primitives.definitions import boolean_value
from ..engine.requests import package_request, expand_literal_argument, forwarding_request, origin
from .context import ExecutionMode, ReaderContext
from .contracts import (
    ConditionalRule, EffectiveReadingProfile, LiteralRegion, ReadingBoundary, ReadingIssue,
    ReadingKnowledge, SkippedRegion, StoredDefinition, SourceCommand, SourceEnd, require_resolved,
    DeferredRegion, UnresolvedBindingResult, UnresolvedReason, BooleanMeaning, CommandDefinition,
    EnvironmentDefinition, UncertainMeaning, BoundMeaning, CharacterCodeMeaning, ScannedArgument, TokenArgument, TokenListMeaning, UndefinedMeaning,
)
from .argument_scanner import ArgumentScanner, key_values
from .configuration import entries, configured_options
from .assignment_scanner import AssignmentScanner
from .effects import declared_effects, command_summary, definition_summary, observed_write_names
from .environment_registry import resolve_environment
from .environment_scanner import EnvironmentScanner
from .definition_scanner import DefinitionScanner
from .deferred_scanner import DeferredScanner
from .literal_scanner import LiteralScanner
from .skipped_scanner import SkippedBranchScanner, SkippedScan
from .conditional_scanner import ConditionalScanner
from .input_scanner import InputScanner
from .dependencies import argument_activity
from .loads import SourceLoadState
from .spans import SourceSpan
from .units import UnitRegistry
from .options import OptionBody, OptionScope, option_items
from .operations import EFFECT_OPERATIONS, FAMILY_OPERATIONS
from ..engine.catalog import CORE_OPERATIONS
from ..engine.primitive import PrimitiveMeaning
from ..engine.observation import capture_primitive
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
    unit_id: str | None = None


@dataclass(frozen=True, slots=True)
class _BranchStart:
    argument: ScannedArgument
    after: tuple
    unit_id: str
    branch: str


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
    pending: tuple
    branch_replays: dict
    active_branches: tuple


class StructuralDispatcher:
    """Route active events and preserve original source spans.

    Applied directives and group tokens retain their original ReadEvent. The
    dispatcher owns its structural group stack; caller-created lexical scopes
    cannot be closed by source. A boundary retains state at the stopping point,
    without repairing groups or rolling back effects already executed. Conditionals
    have an independent stack and create no lexical scopes. EOF in executed text
    with unclosed structure anchors the diagnostic to an opener with empty residue.
    """

    operations = CORE_OPERATIONS

    def __init__(self, reader: TexReader, context: ReaderContext, knowledge: ReadingKnowledge,
                 *, source_commands: bool = False, preparation: bool = False, units: UnitRegistry | None = None,
                 options: OptionScope | None = None, loads: SourceLoadState | None = None,
                 option_forwarder: Callable[[tuple[SourceCommand, ...]], None] | None = None,
                 program: bool = False):
        self.literals = LiteralScanner(reader, context, knowledge)
        self.environments = EnvironmentScanner(reader, context)
        self.skipped = SkippedBranchScanner(reader, context, knowledge)
        self.reader, self.context, self.knowledge = reader, context, knowledge
        self._base_scope_depth = context.scope_depth
        self._groups: list[_GroupFrame] = []
        self._conditionals: list[_ConditionalFrame] = []
        self._skip_start: int | None = None
        self._pending_skip: SkippedScan | None = None
        self._lexical_failure: tuple[ReadingBoundary, InvalidCharacterError] | None = None
        self.halted = False
        self._finished = False
        self.source_commands = source_commands
        # Preparation captures ordinary uninterpreted expressions and continues.
        # The default execution API retains its strict boundary behavior.
        self.preparation = preparation
        self._parents: list[tuple[TexReader, dict[str, CatCode], OptionScope | None]] = []
        self.options = options
        # The source owner validates/commits a complete batch. Frozen replay
        # admits only forwarding, never arbitrary source I/O.
        self.option_forwarder = option_forwarder
        self._environment_stack: list[str] = []
        self._root_ended = False
        self._replays = {}
        self.units = units if units is not None else UnitRegistry()
        self.loads = loads if loads is not None else SourceLoadState()
        self.decisions = []
        self._conditional_units = {}
        self._pending = deque()
        self._branch_replays = {}
        self._active_branches = []
        self.program = program
        self.program_sources = []
        self.program_serial = 0

    def input_recovery(self) -> InputRecovery:
        """Snapshot only at an active handoff, before entering retained code."""
        if not self.preparation or self.halted or self._finished or self._pending_skip or self._skip_start is not None:
            raise ValueError("Recovery requires an active preparation handoff")
        parents, options = self._copy_option_stack(self._parents, self.options)
        return InputRecovery(self, self.reader, self.context.copy(), parents,
                             tuple(self._groups), tuple(replace(f) for f in self._conditionals),
                             tuple(self._environment_stack), dict(self._replays),
                             options, tuple(self._pending), dict(self._branch_replays), tuple(self._active_branches))

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
        self._pending = deque(saved.pending)
        self._branch_replays = dict(saved.branch_replays)
        self._active_branches = list(saved.active_branches)
        self._skip_start = self._pending_skip = None
        self.halted = self._finished = False
        self._set_reader(saved.reader)

    def _set_reader(self, reader: TexReader) -> None:
        self.reader = reader
        reader.endline_char = self.context.endlinechar
        self.literals = LiteralScanner(reader, self.context, self.knowledge)
        self.environments = EnvironmentScanner(reader, self.context)
        self.skipped = SkippedBranchScanner(reader, self.context, self.knowledge)

    def execute_continuation(self, opening):
        """Commit one admitted operation only after its pending input is settled."""
        from ..engine.continuation import execute
        reader, saved_cursor = self.reader, self.reader.checkpoint()
        saved_context, saved_units = self.context.copy(), self.units.checkpoint()
        conditionals = [replace(frame) for frame in self._conditionals]
        decisions, conditional_units = list(self.decisions), dict(self._conditional_units)
        skipped, pending_skip = self._skip_start, self._pending_skip
        try:
            return execute(self, opening)
        except (ReadingIssue, InvalidCharacterError):
            self.context.restore_from(saved_context)
            self.units.restore(saved_units)
            self._conditionals, self.decisions = conditionals, decisions
            self._conditional_units = conditional_units
            self._skip_start, self._pending_skip = skipped, pending_skip
            self._set_reader(reader)
            reader.restore(saved_cursor)
            raise

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

    def halt(self, span: SourceSpan, reason: str, detail: str,
             *, remainder_start: int | None = None, causes=(), unit_id: str | None = None) -> ReadingBoundary:
        """Stop for an execution or caller-owned publication boundary.

        Preparation may subsequently retain the input and resume its saved caller;
        merely constructing a diagnostic does not authorize that recovery.
        """
        self.halted = True
        start = span.start if remainder_start is None else remainder_start
        return ReadingBoundary(span, self.reader.source_span(start, len(self.reader.text)), reason, detail,
                               unit_id, causes=tuple(causes))

    @staticmethod
    def _require(condition: bool, reason: str, detail: str) -> None:
        if not condition:
            raise ReadingIssue(reason, detail)

    def next_item(self) -> ReadEvent | LiteralRegion | StoredDefinition | EnvironmentDefinition | SkippedRegion | ReadingBoundary | SourceCommand | SourceEnd | DeferredRegion | None:
        item = self._next_item()
        return self.identify(item) if item is not None and not isinstance(item, ReadEvent) else item

    def lexical_failure(self, boundary):
        """Expose only a failure at the ordinary token-fetch boundary.

        A scanner may have consumed a partial header/body before failing. Those
        failures cannot resume through this handoff.
        """
        saved = self._lexical_failure
        return saved[1] if self.halted and saved and saved[0] == boundary else None

    def discard_invalid_character(self, boundary):
        error = self.lexical_failure(boundary)
        if error is None:
            raise ValueError("No resumable ordinary lexical failure at this boundary")
        event = self.reader.discard_invalid_character(error)
        self._lexical_failure = None
        self.halted = False
        return event

    def _activity_evidence(self):
        guards = [(f.unit_id, "else" if f.in_alternative else "then") for f in self._conditionals]
        guards.extend(self._active_branches)
        if guards:
            identifier, branch = max(guards, key=lambda g: int(g[0].split("-")[-1]))
            return {"reason": "selected_branch", "decision_unit_id": identifier, "branch": branch}
        return {"reason": "source_sequence", "assumption": "source_visible_reading"}

    @property
    def branch_in_progress(self):
        return bool(self._pending or self._branch_replays)

    def identify(self, item, parent_id: str | None = None):
        """Register a captured item and nested units without reading or execution.

        Parent links denote observation containment. Existing identities are
        validated against the shared registry and returned unchanged.
        """
        if item.unit_id is not None:
            self.units.require(item.unit_id, item.span)
            return item
        activity = "unresolved" if parent_id else "reached"
        evidence = {"reason": "deferred_observation"} if parent_id else self._activity_evidence()
        if isinstance(item, SkippedRegion):
            activity = "skipped"
            evidence = {"reason": "excluded_branch", "decision_unit_id": self._conditional_units.get(item.conditional),
                        "branch": item.branch}
        identifier = self.units.add(item.span, type(item).__name__, parent_id, activity=activity, evidence=evidence)
        item = replace(item, unit_id=identifier)
        if isinstance(item, SourceCommand) and item.arguments:
            arguments = {}
            for arg in item.arguments:
                derived = isinstance(arg, TokenArgument)
                arguments[arg.name] = self.units.add(arg.span, "token_argument" if derived else "argument", identifier,
                    activity=argument_activity(arg.role), evidence={"reason": "declared_argument_role",
                        "argument_name": arg.name, "argument_role": arg.role,
                        **({"location_relation": "invocation_anchor",
                            "token_origins": [{"source": t.span.basis.source_id, "occurrence": t.span.basis.occurrence_id,
                                              "start": t.span.start, "end": t.span.end} for t in arg.tokens]} if derived else {}),
                        "binding_id": item.metadata.get("binding_id", "")})
            item = replace(item, metadata={**item.metadata, "argument_units": arguments})
        if isinstance(item, (StoredDefinition, EnvironmentDefinition)):
            self.units.add(item.body, "stored_body", identifier, activity="stored",
                           evidence={"reason": "stored_definition"})
        if isinstance(item, DeferredRegion):
            # A captured command is another view of the same observed unit.
            item = replace(item, command=replace(item.command, unit_id=identifier) if item.command else None,
                           observations=tuple(self.identify(o, identifier) for o in item.observations))
        if isinstance(item, LiteralRegion):
            item = replace(item, interpolations=tuple(self.identify(o, identifier) for o in item.interpolations))
        return item

    def _next_item(self):
        if self.halted or self._finished:
            return None
        if self._pending:
            item = self._pending.popleft()
            if not isinstance(item, _BranchStart):
                return item
            cursor = TokenCursor(item.argument, self.reader.text, self.context)
            self._branch_replays[cursor] = (self.reader, item.after)
            self._active_branches.append((item.unit_id, item.branch))
            self._set_reader(cursor)
        reader, context = self.reader, self.context
        # A skipped scan has consumed its delimiter, but it is still owed to the
        # output stream. A context failure here must retain that source too.
        cursor_span = (self._pending_skip.terminator.span if self._pending_skip is not None
                       else reader.source_span(reader.position, reader.position))
        if context.mode != ExecutionMode.ACTIVE_EXECUTION:
            return self.halt(cursor_span, "inactive_context",
                                  "An owning scanner must handle this execution mode")
        if (reader.catcodes is not context.catcodes or reader.endline_char != context.endlinechar
                or context.scope_depth != self._base_scope_depth + len(self._groups)):
            return self.halt(cursor_span, "context_changed",
                                  "Reader parameters or scope ownership changed outside the dispatcher")
        if self._skip_start is not None:
            return self._scan_skipped()
        if self._pending_skip is not None:
            pending, self._pending_skip = self._pending_skip, None
            try:
                self.route_conditional(pending.rule, pending.terminator.span)
                return pending.terminator
            except ReadingIssue as error:
                return self.halt(pending.terminator.span, error.reason, error.detail, causes=error.causes)
        try:
            event = reader.next_event()
        except InvalidCharacterError as error:
            boundary = self.halt(error.span, "invalid_character", str(error))
            self._lexical_failure = (boundary, error)
            return boundary
        if event is None:
            if reader in self._branch_replays:
                parent, after = self._branch_replays.pop(reader)
                self._active_branches.pop()
                self._set_reader(parent)
                self._pending.extendleft(reversed(after))
                return self._next_item()
            if reader in self._replays:
                parent, closing, name, metadata = self._replays.pop(reader)
                self._set_reader(parent)
                return SourceCommand(closing, name, "transparent_end", (), metadata)
            if self.program:
                return None  # The bounded token-program owner supplies the continuation.
            if self._parents:
                end = SourceEnd(reader.terminated_span or reader.source_span(len(reader.text), len(reader.text)),
                                "endinput" if reader.terminated_span else "eof")
                parent, saved, self.options = self._parents.pop()
                for char, code in saved.items():
                    self.context.catcodes[char] = code
                self._set_reader(parent)
                return end
            if self._conditionals:
                return self.halt(self._conditionals[-1].opening, "unclosed_conditional",
                                      f"EOF with {len(self._conditionals)} unclosed conditional(s)",
                                      remainder_start=len(reader.text))
            if self._groups:
                return self.halt(self._groups[-1].opening, "unclosed_group",
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
        meaning = context.resolve_meaning(self.knowledge, token.value, token.kind)
        definition = context.lookup_definition(token.value, token.kind)
        if definition is not None and not self.preparation:
            return self.halt(event.span, "stored_macro",
                                  f"Stored macro {token.value!r} requires interpretation; defined at "
                                  f"{definition.span.basis.source_id}:{definition.span.start}")
        if event.kind != EventKind.TOKEN:
            # Implicit paragraph tokens normally pass through, but a stored
            # redefinition must block that route just like an explicit command.
            return event
        if token.kind == TokenKind.ACTIVE_CHARACTER and not self.preparation:
            return self.halt(event.span, "active_character", "Active character meaning is unresolved")
        if token.catcode in {CatCode.MATH_SHIFT, CatCode.ALIGNMENT_TAB} and not self.preparation:
            return self.halt(event.span, "unsupported_structure",
                                  "Math and alignment require their own mode and scope handling")
        try:
            deferred = DeferredScanner(reader, context)
            if isinstance(meaning, PrimitiveMeaning):
                if meaning.uncertain is not None:
                    if (self.preparation and meaning.operation == "conditional.route"
                            and meaning.operand.evaluation in {"always_true", "always_false"}):
                        return self.capture_conditional(token, ConditionalRule("opener", "deferred", 0),
                                                        causes=(meaning.uncertain,))
                    raise ReadingIssue("uncertain_meaning", "Primitive meaning may have changed", causes=(meaning.uncertain,))
                operation = self.operations[meaning.operation]
                if operation.expansion is not None:
                    return self.execute_continuation(event)
                return operation.execute(self, event, meaning)
            if isinstance(meaning, UndefinedMeaning):
                if meaning.uncertain is not None:
                    raise ReadingIssue("uncertain_meaning", "Undefined state may have changed", causes=(meaning.uncertain,))
                if self.preparation and token.value in context.engine_profile.capture_integer_setup:
                    from ..engine.catalog import EXTENSIONS
                    captured = capture_primitive(reader, context, token, EXTENSIONS[token.value])
                    return replace(captured, action="external_engine_setup",
                                   metadata={**captured.metadata, "engine_profile": context.engine_profile.name,
                                             "exposed": False, "executed": False})
                raise ReadingIssue("undefined_control_sequence", f"{token.value!r} is established undefined")
            if isinstance(meaning, TokenListMeaning):
                if meaning.uncertain is not None:
                    raise ReadingIssue("uncertain_meaning", "Token-list meaning may have changed", causes=(meaning.uncertain,))
                if self.program:
                    from ..engine.programs import expand_call
                    return expand_call(self, event, meaning)
                if self.preparation:
                    return self._deferred(deferred.command(token, "stored_macro", "Token-list content requires interpretation"))
                raise ReadingIssue("stored_macro", "Token-list content requires interpretation")
            if isinstance(meaning, CharacterCodeMeaning):
                if meaning.uncertain is not None:
                    raise ReadingIssue("uncertain_meaning", "Character code may have been redefined", causes=(meaning.uncertain,))
                if self.preparation:
                    return DeferredRegion(event.span, "character_interpretation",
                                          "Character-code content requires interpretation", (token,))
                raise ReadingIssue("character_interpretation", "Character-code content requires interpretation")
            if isinstance(meaning, UncertainMeaning):
                raise ReadingIssue("uncertain_meaning", f"{token.value!r} may have been redefined at {meaning.span}", causes=(meaning.span,))
            if isinstance(meaning, BoundMeaning):
                if meaning.uncertain is not None:
                    raise ReadingIssue("uncertain_meaning", f"Copied meaning of {token.value!r} may have changed at {meaning.uncertain}", causes=(meaning.uncertain,))
                self._require(meaning.profile is not None, "character_meaning",
                              "A character meaning is captured; its execution needs a downstream token interpreter")
            if (isinstance(reader, TokenCursor) and not self.program and reader not in self._branch_replays and token.kind == TokenKind.CHARACTER
                    and token.catcode not in {CatCode.SPACE, CatCode.BEGIN_GROUP, CatCode.END_GROUP}):
                raise ReadingIssue("option_body", "Option text requires interpretation beyond reading effects")
            if isinstance(meaning, BooleanMeaning):
                if self.preparation and meaning.uncertain is not None and meaning.target is None:
                    return self.capture_conditional(token, ConditionalRule("opener", "deferred", 0), causes=(meaning.uncertain,))
                if meaning.uncertain is not None:
                    raise ReadingIssue("uncertain_boolean", f"Meaning of {token.value!r} may have changed in unexecuted source at {meaning.uncertain}", causes=(meaning.uncertain,))
                if meaning.target is not None:
                    truth = boolean_value(context, self.knowledge, meaning.source)
                    context.record_meaning(meaning.target, BooleanMeaning(event.span, truth))
                else:
                    self.route_conditional(context.conditional_rule(token.value, self.knowledge), event.span,
                                      metadata={"predicate": "established_boolean"})
                return event
            if definition is not None:
                if self.program:
                    from ..engine.programs import expand_call
                    return expand_call(self, event, definition)
                if self.source_commands:
                    from ..engine.programs import setup_request
                    request = setup_request(self, event, definition)
                    if request is not None:
                        return request
                if self.source_commands and (request := package_request(self, event)) is not None:
                    return request
                summary = definition_summary(definition, context, self.knowledge)
                detail = f"Unexpanded {token.value!r}; definition at {definition.span.basis.source_id}:{definition.span.start}"
                # A completely bounded argument-free body consumes no following
                # groups. Those groups still belong to ordinary source execution.
                region = (DeferredRegion(event.span, "stored_macro", detail, (token,)) if summary.selective
                          else deferred.command(token, "stored_macro", detail))
                return self._deferred(replace(region, effect_summary=summary))
            if token.kind == TokenKind.ACTIVE_CHARACTER:
                return self._deferred(DeferredRegion(event.span, "active_character", "Active character retained without expansion", (token,)))
            if self.preparation and token.catcode == CatCode.MATH_SHIFT:
                return self._deferred(deferred.math(token))
            if self.preparation and token.catcode == CatCode.ALIGNMENT_TAB:
                return DeferredRegion(event.span, "alignment_interpretation", "Alignment retained without interpretation", (token,))
            if token.catcode in {CatCode.BEGIN_GROUP, CatCode.END_GROUP}:
                identity = "scope.begin" if token.catcode == CatCode.BEGIN_GROUP else "scope.end"
                return self.operations[identity].execute(self, event, PrimitiveMeaning(identity, "simple"))
            if token.kind != TokenKind.CONTROL_SEQUENCE:
                return event
            resolved = meaning.profile if isinstance(meaning, BoundMeaning) else self.knowledge.resolve_command(token.value)
            if self.preparation and isinstance(resolved, UnresolvedBindingResult):
                if resolved.reason == UnresolvedReason.UNKNOWN_CONSTRUCT:
                    return self._deferred(deferred.command(token, resolved.reason.value, resolved.detail))
                if resolved.reason == UnresolvedReason.PACKAGE_NOT_LOADED:
                    syntax = self.knowledge.source_command_syntax(token.value)
                    if syntax is not None:
                        command = ArgumentScanner(reader, context).read(event.span, syntax)
                        return self._deferred(DeferredRegion(command.span, resolved.reason.value, resolved.detail,
                                              (token,) + tuple(t for arg in command.arguments for t in arg.tokens),
                                              command, syntax.binding_id))
                    # An inactive literal binding can require a different mouth.
                    # Do not treat its body as ordinary executed TeX.
            profile = require_resolved(resolved)
            operation = FAMILY_OPERATIONS.get(profile.family)
            if operation is not None:
                return operation.execute(self, event, profile)
            if profile.family == "assignment_prefix":
                raise ReadingIssue("assignment_prefix", "Prefixed assignments require explicit scope and prefix resolution")
            if profile.family == "configuration_command":
                return self._configuration(event.span, profile)
            if profile.family == "option_control":
                self._require(not isinstance(reader, TokenCursor), "option_body",
                              "Nested option declarations/processing require further resolution")
                command = ArgumentScanner(reader, context).read(event.span, profile)
                return self._options(command)
            if profile.family == "source_command":
                self._require(self.source_commands or profile.action in {"reading_noop", "capture_setting"}
                              or profile.action == "pass_options" and self.option_forwarder is not None,
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
                if command.action == "pass_options":
                    return forwarding_request(self, command)
                if command.action == "branch_test":
                    return self._branch_test(command)
                if command.action == "declared_effects":
                    declared_effects(command, context, self.knowledge)
                if command.action == "summarized_effects":
                    for argument in command.arguments:
                        argument.literal()
                    return self._deferred(DeferredRegion(command.span, "summarized_effects",
                        "Bounded writes retained without computing the operation's values", command=command,
                        binding_id=profile.binding_id, effect_summary=command_summary(command.metadata, context)))
                if command.action in {"opaque", "metadata", "citation"} and any(
                        t.kind in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER}
                        for arg in command.arguments if arg.role not in {"data", "diagnostic", "stored"} for t in arg.tokens):
                    self.defer_effects(command.span)
                if command.action == "end_input":
                    self._require(not isinstance(reader, TokenCursor), "token_input_boundary",
                                  "Endinput in captured argument tokens needs the physical input owner")
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
            if profile.action is not None:
                operation = EFFECT_OPERATIONS.get(profile.action)
                self._require(operation is not None, "unsupported_operation", f"No execution route for {profile.action!r}")
                return operation.execute(self, event, profile)
            if profile.family in {"grouping", "catcode_mutator"}:
                raise ReadingIssue("unsupported_operation", "Reading effect has no executable action")
            self._require(not isinstance(reader, TokenCursor), "option_body",
                          "Literal and environment reading requires a character-input contract")
            configuration_gaps = ()
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
                    profile, configuration_gaps = self._configured_environment(name, profile, options)
                elif profile.configuration:
                    profile, configuration_gaps = self._configured_environment(name, profile, None)
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
            if profile.grammar.get("handler") in {"token_delimited", "physical_line_literal"} and configuration_gaps:
                return self._deferred(DeferredRegion(region.span, "literal_configuration",
                    self._configuration_detail(configuration_gaps), binding_id=profile.binding_id))
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
            return self.halt(event.span, error.reason, error.detail, causes=error.causes)
        except InvalidCharacterError as error:
            return self.halt(error.span, "invalid_character", str(error), remainder_start=event.span.start)

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
            resolved = state.resolve(namespace, captured, contract, preserve_unclassified=self.preparation)
            self.knowledge.check_configuration(command.name, state.reading_values(resolved, contract), contract)
            state.store("values", namespace, resolved, contract["assignment_scope"])
            gaps = state.unclassified(resolved, contract)
            if gaps:
                return self._deferred(DeferredRegion(command.span, "literal_configuration",
                    self._configuration_detail(gaps), command=command, binding_id=profile.binding_id))
        return command

    @staticmethod
    def _configuration_detail(keys):
        return (f"Unclassified configuration keys: {', '.join(keys)}. Source retained using the declared "
                "capture grammar and resolved reading options; remaining option semantics require binding knowledge.")

    def _configured_environment(self, name, profile, argument):
        options = configured_options(profile, argument, self.context, preserve_unclassified=self.preparation)
        resolved = require_resolved(resolve_environment(name, options.values, self.context, self.knowledge))
        return resolved, options.unclassified

    def _options(self, command: SourceCommand) -> SourceCommand:
        """Capture first, select later, then reuse strict dispatch over frozen tokens.

        Option replay is an effect-only operation. Its source is already captured
        by DeclareOption and is never re-emitted or added to top-level coverage.
        Each selected body must be self-contained with respect to groups and
        conditionals. Only the owner's atomic forwarding capability is admitted;
        source loads and arbitrary macro execution remain explicit limits.
        """
        scope = self.options
        self._require(scope is not None, "option_context", "Option commands require a package/class load")
        self._require(self.context.scope_depth == scope.depth, "option_scope",
                      "Option controls inside an additional lexical group need further resolution")
        if command.action == "declare_option":
            option = None
            if not command.argument("star"):
                names = option_items(command.argument("name"))
                self._require(len(names) == 1, "option_name", "An option declaration needs one literal name")
                option = names[0]
            scope.declare(option.name if option else None, OptionBody(command.argument("body"), self.reader.text, option))
            return command
        if command.action == "execute_options":
            plan = scope.defaults(option_items(command.argument("options")))
        else:
            order = command.metadata["starred_order" if command.argument("star") else "order"]
            plan = scope.plan(order)
        saved = self.context.copy()
        definition_checks, requests = [], []
        try:
            previous = self.context.lookup_meaning("CurrentOption")
            if command.action == "execute_options":
                # ExecuteOptions saves one expansion, then edef-restores it
                # after the bodies. General parameterized donors stay bounded.
                self._require(isinstance(previous, (TokenListMeaning, StoredDefinition))
                              and getattr(previous, "uncertain", None) is None
                              and not getattr(previous, "parameter_tokens", ())
                              and not getattr(previous, "parameter_count", 0),
                              "option_current", "ExecuteOptions needs an established parameterless CurrentOption")
                previous_tokens = previous.replacement_tokens
            for option, body in plan:
                name = option.name
                self.context.record_meaning("CurrentOption", TokenListMeaning(command.span, option.tokens))
                self._require(not any(t.catcode == CatCode.PARAMETER for t in body.argument.tokens),
                              "option_body", f"Option {name!r} requires parameter-token compilation")
                cursor = TokenCursor(body.argument, body.text, self.context)
                replay = StructuralDispatcher(cursor, self.context, self.knowledge, units=self.units, loads=self.loads,
                                              option_forwarder=self.option_forwarder)
                replay.decisions = self.decisions
                for item in replay:
                    if isinstance(item, (ReadingBoundary, DeferredRegion)):
                        raise ReadingIssue("option_body", f"Option {name!r} requires {item.reason} at "
                                           f"{item.span.basis.source_id}:{item.span.start}: {item.detail}", causes=item.causes)
                    if isinstance(item, (CommandDefinition, EnvironmentDefinition)) and item.target_check == "unverified":
                        definition_checks.append({"unit_id": item.unit_id, "declaration": item.declaration,
                                                  "target": item.name if isinstance(item, EnvironmentDefinition) else item.target.value,
                                                  "requirement": item.target_requirement})
                    if isinstance(item, SourceCommand) and item.action == "pass_options":
                        requests.append(item)
            restored = ()
            if command.action == "execute_options":
                restored = expand_literal_argument(self, TokenArgument("CurrentOption", command.span, previous_tokens)).tokens
            self.context.record_meaning("CurrentOption", TokenListMeaning(command.span, restored))
            if requests:
                self.option_forwarder(tuple(requests))
        except ReadingIssue:
            # Failed bounded resolution publishes no partly applied option state.
            self.context.restore_from(saved)
            raise
        finally:
            self.reader.endline_char = self.context.endlinechar
        if command.action == "process_options":
            scope.processed = True
        return replace(command, metadata={**command.metadata, "selected_options": [option.name for option, _ in plan],
            "definition_checks": definition_checks,
            "forwarded_options": [{"unit_id": request.unit_id, "target_kind": request.metadata["target_kind"],
                "target": request.value("name"), "options": [option.name for option in option_items(request.argument("options"))],
                "tokens": [origin(t.span) for t in request.argument("options").tokens]} for request in requests]})

    def _deferred(self, region: DeferredRegion) -> DeferredRegion:
        # Bare arithmetic/text math cannot assign meanings. Other unexecuted
        # expressions may redefine a boolean or its setter, even globally.
        if region.reason != "math_interpretation" or any(
                t.kind in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER} for t in region.tokens):
            self.defer_effects(region.span, reason=region.reason, detail=region.detail, summary=region.effect_summary)
        return region

    def uncertainty_origin(self, span):
        from ..engine.programs import source_origin
        return source_origin(self.program_sources, span)

    def defer_effects(self, span, *, reason="unresolved_reading", detail="Reading effects remain unresolved", summary=None):
        """Unknown execution can invalidate live and suspended bounded state."""
        span = self.uncertainty_origin(span)
        selective = summary is not None and summary.selective
        changed = (self.context.invalidate_writes(summary, span) if selective
                   else self.context.invalidate_observed_meanings(span))
        changed = self.context.hooks.invalidate_effects(summary, span) or changed
        for scope in (self.options, *(parent[2] for parent in self._parents)):
            if (scope is not None and scope.uncertain is None
                    and (not selective or summary.options.contains(scope.name))):
                scope.uncertain = span
                changed = True
        if changed:
            self.units.uncertainty_cause(span, reason, detail, evidence=self._activity_evidence())

    def capture_conditional(self, token, rule, *, causes=()):
        try:
            region = ConditionalScanner(self.reader, self.context).read(token, rule, classify=self._observed_conditional,
                protect=lambda t, **kw: self._protect_deferred_environment(t, conditional=True, **kw))
        except ReadingIssue as error:
            raise ReadingIssue(error.reason, error.detail, causes=tuple(dict.fromkeys((*causes, *error.causes)))) from error
        region = replace(region, causes=tuple(causes))
        self.context.invalidate_meanings(region.changed_meanings, self.uncertainty_origin(region.span))
        return self._deferred(region)

    def _observed_conditional(self, candidate):
        if candidate.kind != TokenKind.CONTROL_SEQUENCE:
            return None
        meaning = self.context.lookup_meaning(candidate.value)
        if (isinstance(meaning, PrimitiveMeaning) and meaning.operation == "conditional.route"
                and meaning.operand.evaluation in {"always_true", "always_false"}):
            return ConditionalRule("opener", "deferred", 0)
        if isinstance(meaning, BooleanMeaning):
            # Retain its declared nesting role as an explicit assumption;
            # uncertainty prohibits choosing a branch, not source capture.
            return ConditionalRule("opener", "deferred", 0) if meaning.target is None else None
        return self.context.conditional_rule(candidate.value, self.knowledge)

    def observe_input(self, *, may_skip=False):
        """Capture a candidate file, never dispatch it as an active input."""
        return InputScanner(self.reader, self.context).read(may_skip=may_skip, classify=self._observed_conditional,
            protect=lambda t, **kw: self._protect_deferred_environment(t, conditional=may_skip, **kw))

    def _protect_deferred_environment(self, token, *, shadowed=(), conditional=False) -> bool | DeferredRegion | StoredDefinition | EnvironmentDefinition:
        """Locate known protected syntax without executing an unbound body.

        Routing remains here, not in the envelope scanner. Bounded conditionals
        are captured without branch selection; reading effects still need resolution.
        """
        if token.catcode == CatCode.MATH_SHIFT:
            return DeferredScanner(self.reader, self.context).math(token)
        if token.kind != TokenKind.CONTROL_SEQUENCE:
            return False
        if token.value in shadowed:
            return DeferredScanner(self.reader, self.context).command(
                token, "stored_macro", "Unexecuted definition shadows the entry grammar")
        if not conditional and (rule := self._observed_conditional(token)) is not None:
            self._require(rule.role == "opener", "conditional_structure", "Unmatched conditional delimiter in deferred source")
            return ConditionalScanner(self.reader, self.context).read(token, rule,
                classify=self._observed_conditional,
                protect=lambda t, **kw: self._protect_deferred_environment(t, conditional=True, **kw))
        meaning = self.context.resolve_meaning(self.knowledge, token.value)
        if isinstance(meaning, PrimitiveMeaning):
            captured = capture_primitive(self.reader, self.context, token, meaning)
            if captured is not None:
                return captured
            raise ReadingIssue("environment_reading", "Primitive effects in retained source require resolution")
        if isinstance(meaning, BooleanMeaning) and meaning.target is not None:
            return DeferredScanner(self.reader, self.context).command(token, "conditional_interpretation",
                "Boolean setter retained without selecting or executing a branch")
        if isinstance(meaning, (StoredDefinition, EnvironmentDefinition)):
            # Observing an invocation inside an already deferred body requires
            # no more execution than observing an unknown command there. Keep
            # its envelope protected; do not dispatch the old binding or body.
            return DeferredScanner(self.reader, self.context).command(
                token, "stored_macro", "Stored invocation inside an unbound environment remains unexpanded")
        if meaning is not None and not isinstance(meaning, BoundMeaning):
            raise ReadingIssue("environment_reading", "A conditional or setter inside an unbound environment needs reading resolution")
        if isinstance(meaning, BoundMeaning):
            self._require(meaning.uncertain is None and meaning.profile is not None,
                          "environment_reading", "Copied meaning requires further resolution")
        profile = meaning.profile if isinstance(meaning, BoundMeaning) else self.knowledge.resolve_command(token.value)
        if isinstance(profile, UnresolvedBindingResult):
            if profile.reason == UnresolvedReason.PACKAGE_NOT_LOADED:
                syntax = self.knowledge.source_command_syntax(token.value)
                if syntax is not None:
                    command = ArgumentScanner(self.reader, self.context).read(token.span, syntax)
                    return DeferredRegion(command.span, profile.reason.value, profile.detail,
                        (token,) + tuple(t for arg in command.arguments for t in arg.tokens), command, syntax.binding_id)
            if profile.reason != UnresolvedReason.UNKNOWN_CONSTRUCT:
                raise ReadingIssue(profile.reason.value, profile.detail)
            return DeferredScanner(self.reader, self.context).command(token, profile.reason.value, profile.detail)
        if profile.family == "stored_definition":
            return DefinitionScanner(self.reader, self.context).read(token.span.start, profile)  # capture, never install
        if profile.family == "meaning_assignment":
            return AssignmentScanner(self.reader, self.context).let(token.span, profile.name)
        if profile.family == "collected_environment_definition":
            return self.environments.definition(token.span.start, profile)  # capture, never install
        if profile.family in {"conditional", "conditional_factory", "catcode_mutator", "catcode_assignment", "character_code_definition", "grouping", "environment_factory", "option_control", "configuration_command", "assignment_prefix", "parameter_assignment"}:
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
            if "effect_summary" in command.metadata:
                command = replace(command, metadata={**command.metadata,
                    "observed_write_names": observed_write_names(command, self.context, self.knowledge)})
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
                    nested, _ = self._configured_environment(name, nested, options)
                elif nested.configuration:
                    nested, _ = self._configured_environment(name, nested, None)
                self._require(not nested.interpolations, "environment_reading",
                              "Interpolation inside an unbound environment requires further reading resolution")
                self.literals.read(token.span.start, nested)
                return True
            if isinstance(nested, UnresolvedBindingResult) and nested.reason != UnresolvedReason.UNKNOWN_CONSTRUCT:
                raise ReadingIssue(nested.reason.value, nested.detail)
            self.reader.restore(checkpoint)
        return False

    def _branch_test(self, command):
        """Route a YAML-described braced branch over its already captured tokens."""
        command = self.identify(command)
        causes, definitions = (), ()
        try:
            name = command.value("name")
            self._require(bool(name), "computed_argument", "A load query needs a nonempty literal name")
            status = self.loads.query(command.metadata["kind"], name, self.context)
            truth, facts, unknown = status.truth, list(status.load_units), list(status.uncertainty_units)
            causes, definitions = status.causes, status.definition_units
            detail = "The current package/class load marker is unresolved" if truth is None else ""
        except ReadingIssue as error:
            name, truth, facts, unknown, detail = None, None, [], [], error.detail
        self.decisions.append({"unit_id": command.unit_id, "predicate": "loaded",
            "kind": command.metadata["kind"], "name": name, "truth": truth,
            "definition_unit_ids": list(definitions), "load_unit_ids": facts, "uncertainty_unit_ids": unknown,
            "assumption": "source_visible_loads"})
        if truth is None:
            return self._deferred(DeferredRegion(command.span, "branch_selection", detail,
                tuple(t for a in command.arguments for t in a.tokens), command,
                command.metadata["binding_id"], unit_id=command.unit_id, causes=causes))
        then, otherwise = command.argument("then"), command.argument("else")
        selected, rejected = (then, otherwise) if truth else (otherwise, then)
        for arg in (selected, rejected):
            self.units.decide(command.metadata["argument_units"][arg.name],
                "reached" if arg is selected else "skipped",
                {"reason": "selected_branch" if arg is selected else "excluded_branch",
                 "decision_unit_id": command.unit_id, "branch": arg.name})
        span = command.span
        prefix = span.basis.span(span.start, then.span.start)
        self._conditional_units[prefix] = command.unit_id
        boundary = lambda s: SourceCommand(s, command.name, "branch_boundary", metadata={"decision_unit_id": command.unit_id})
        middle = boundary(span.basis.span(then.span.end, otherwise.span.start))
        suffix = boundary(span.basis.span(otherwise.span.end, span.end))
        skipped = SkippedRegion(rejected.span, prefix, rejected.name)
        before = [boundary(prefix)] if truth else [boundary(prefix), skipped, middle]
        after = (middle, skipped, suffix) if truth else (suffix,)
        self._pending.extend((*before, _BranchStart(selected, after, command.unit_id, selected.name)))
        return self._next_item()

    def route_conditional(self, rule: ConditionalRule, span: SourceSpan, *, metadata=None):
        """Own execution and stack changes; conditionals do not create scopes."""
        if rule.role == "opener":
            self._require(rule.evaluation in {"always_true", "always_false"},
                          "unsupported_conditional", "Conditional predicate requires interpretation")
            truth = rule.evaluation == "always_true"
            identifier = self.units.add(span, "conditional_decision", activity="reached", evidence=self._activity_evidence())
            self._conditional_units[span] = identifier
            self.decisions.append({"unit_id": identifier, "predicate": "constant", "truth": truth,
                                   "definition_unit_ids": [], **(metadata or {})})
            self._conditionals.append(_ConditionalFrame(span, truth, unit_id=identifier))
            if not truth:
                self._skip_start = span.end
            return identifier
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
            return self.halt(frame.opening, error.reason, error.detail, remainder_start=self._skip_start, causes=error.causes)
        except InvalidCharacterError as error:
            return self.halt(error.span, "invalid_character", str(error), remainder_start=self._skip_start)
        self._skip_start = None
        self._pending_skip = scanned
        return SkippedRegion(scanned.span, frame.opening, "else" if frame.in_alternative else "then")

    def begin_group(self, kind: str, span: SourceSpan) -> None:
        """Own the execution frame; the shared state owns scope restoration."""
        self.context.push_scope()
        self._groups.append(_GroupFrame(kind, span))

    def end_group(self, kind: str) -> None:
        self._require(bool(self._groups), "unmatched_group", "No source group is available to close")
        self._require(self._groups[-1].kind == kind, "mismatched_group",
                      f"Cannot close {self._groups[-1].kind} group with {kind} closer")
        self.context.pop_scope()
        self._groups.pop()

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
