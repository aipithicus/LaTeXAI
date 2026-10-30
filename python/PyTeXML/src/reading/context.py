"""Document-local execution mode, lexical state, and stored definitions."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterator
from .contracts import (EffectiveReadingProfile, MouthBaseline, StoredDefinition,
                        EnvironmentDeclaration, EnvironmentDefinition, ScannedArgument,
                        BooleanMeaning, BoundMeaning, CharacterCodeMeaning, ConditionalRule, ReadingIssue, UncertainMeaning,
                        TokenListMeaning, UndefinedMeaning)
from .tex_reader import CatCode, CatcodeTable, TokenKind
from .configuration import ConfigurationState
from .spans import SourceSpan
from ..engine.parameters import IntegerParameters
from ..engine.primitive import PrimitiveMeaning
from ..engine.hooks import HookState
from ..engine.fonts import FontState
from ..engine.read_streams import ReadStreams
from ..engine.token_registers import TokenRegisters
from ..engine.state_cells import StateCells


DefinitionKey = tuple[TokenKind, str]
LocalMeaning = StoredDefinition | EnvironmentDefinition | BooleanMeaning | BoundMeaning | CharacterCodeMeaning | TokenListMeaning | UncertainMeaning | UndefinedMeaning | PrimitiveMeaning


class ExecutionMode(str, Enum):
    ACTIVE_EXECUTION = "active_execution"
    ARGUMENT_SCANNING = "argument_scanning"
    STORED_DEFINITION = "stored_definition"
    SKIPPED_BRANCH = "skipped_branch"


@dataclass
class _ScopeSnapshot:
    catcodes: CatcodeTable
    endlinechar: int
    expl3_active: bool
    expl3_saved_catcodes: dict[str, CatCode]
    expl3_saved_endlinechar: int
    uncertain_prefixes: dict[str, SourceSpan]

    def copy(self) -> _ScopeSnapshot:
        return _ScopeSnapshot(self.catcodes.copy(), self.endlinechar,
                              self.expl3_active, dict(self.expl3_saved_catcodes),
                              self.expl3_saved_endlinechar, dict(self.uncertain_prefixes))


class ReaderContext:
    """Scoped reading state and meaning writes; source dispatch lives above it.

    Literal callers establish a lexical_scope(), enter the resolved profile, and
    restore it on exit. A live TexReader can share catcodes; the caller must also
    synchronize endline_char before it loads subsequent physical lines.
    """

    def __init__(self, *, baseline: MouthBaseline, catcodes: CatcodeTable | None = None,
                 endlinechar: int | None = None,
                 mode: ExecutionMode = ExecutionMode.ACTIVE_EXECUTION, initial_meanings=None, engine_profile="etex",
                 primitive_initial_state=False):
        # Environment assembly imports family handlers that use ReaderContext.
        # Select it at context construction, after the state classes are loaded.
        from ..engine.profiles import engine_profile as select_engine_profile
        self.engine_profile = select_engine_profile(engine_profile)
        self.primitive_initial_state = primitive_initial_state
        self.baseline = baseline
        self.catcodes = catcodes.copy() if catcodes is not None else baseline.new_catcodes()
        self.endlinechar = baseline.endlinechar if endlinechar is None else endlinechar
        self.mode = mode
        self.expl3_active = False
        self.expl3_saved_catcodes: dict[str, CatCode] = {}
        self.expl3_saved_endlinechar = self.endlinechar
        self._uncertain_prefixes = {}
        self._scope_stack: list[_ScopeSnapshot] = []
        self._meanings: dict[DefinitionKey, LocalMeaning] = dict(initial_meanings or {})
        # Journal only changed meanings, avoiding a copy of every definition at
        # each group (including temporary literal scopes).
        self._meaning_scopes: list[dict[DefinitionKey, LocalMeaning | None]] = []
        self._environments: dict[str, EnvironmentDeclaration | EnvironmentDefinition] = {}
        self._environment_scopes: list[dict[str, EnvironmentDeclaration | EnvironmentDefinition | None]] = []
        self._capture_settings: dict[str, ScannedArgument] = {}
        self._capture_setting_scopes: list[dict[str, ScannedArgument | None]] = []
        self.configurations = ConfigurationState()
        self.integer_parameters = IntegerParameters()
        self.fonts = FontState(initial=primitive_initial_state)
        self.read_streams = ReadStreams(initial=primitive_initial_state)
        self.token_registers = TokenRegisters(initial=primitive_initial_state)
        self.state_cells = StateCells()
        self.after_assignment = None
        self.after_groups = []
        self.hooks = HookState()
        # Preparation assumptions are derivations, not TeX state assignments.
        self.recovery_contexts: tuple[str, ...] = ()

    def _snapshot(self) -> _ScopeSnapshot:
        return _ScopeSnapshot(self.catcodes.copy(), self.endlinechar,
                              self.expl3_active, dict(self.expl3_saved_catcodes),
                              self.expl3_saved_endlinechar, dict(self._uncertain_prefixes))

    def _restore(self, saved: _ScopeSnapshot) -> None:
        self.catcodes.restore_from(saved.catcodes)
        self.endlinechar = saved.endlinechar
        self.expl3_active = saved.expl3_active
        self.expl3_saved_catcodes = dict(saved.expl3_saved_catcodes)
        self.expl3_saved_endlinechar = saved.expl3_saved_endlinechar
        self._uncertain_prefixes = dict(saved.uncertain_prefixes)

    def copy(self) -> ReaderContext:
        ctx = ReaderContext(baseline=self.baseline, mode=self.mode, engine_profile=self.engine_profile,
                            primitive_initial_state=self.primitive_initial_state)
        ctx._restore(self._snapshot())
        ctx._scope_stack = [saved.copy() for saved in self._scope_stack]
        ctx._meanings = dict(self._meanings)
        ctx._meaning_scopes = [dict(saved) for saved in self._meaning_scopes]
        ctx._environments = dict(self._environments)
        ctx._environment_scopes = [dict(saved) for saved in self._environment_scopes]
        ctx._capture_settings = dict(self._capture_settings)
        ctx._capture_setting_scopes = [dict(saved) for saved in self._capture_setting_scopes]
        ctx.configurations = self.configurations.copy()
        ctx.integer_parameters = self.integer_parameters.copy()
        ctx.fonts = self.fonts.copy()
        ctx.read_streams = self.read_streams.copy()
        ctx.token_registers = self.token_registers.copy()
        ctx.state_cells = self.state_cells.copy()
        ctx.after_assignment = self.after_assignment
        ctx.after_groups = [list(tokens) for tokens in self.after_groups]
        ctx.hooks = self.hooks.copy()
        ctx.recovery_contexts = self.recovery_contexts
        return ctx

    def restore_from(self, saved: ReaderContext) -> None:
        """Restore a suspended input's state without replacing the live table."""
        if self.baseline != saved.baseline or self.engine_profile != saved.engine_profile:
            raise ValueError("Cannot restore a different reading baseline")
        self._restore(saved._snapshot())
        self.mode = saved.mode
        self._scope_stack = [state.copy() for state in saved._scope_stack]
        self._meanings = dict(saved._meanings)
        self._meaning_scopes = [dict(state) for state in saved._meaning_scopes]
        self._environments = dict(saved._environments)
        self._environment_scopes = [dict(state) for state in saved._environment_scopes]
        self._capture_settings = dict(saved._capture_settings)
        self._capture_setting_scopes = [dict(state) for state in saved._capture_setting_scopes]
        self.configurations = saved.configurations.copy()
        self.integer_parameters = saved.integer_parameters.copy()
        self.fonts = saved.fonts.copy()
        self.read_streams = saved.read_streams.copy()
        self.token_registers = saved.token_registers.copy()
        self.state_cells = saved.state_cells.copy()
        self.after_assignment = saved.after_assignment
        self.after_groups = [list(tokens) for tokens in saved.after_groups]
        self.hooks = saved.hooks.copy()
        self.recovery_contexts = saved.recovery_contexts

    def lookup_environment(self, name: str) -> EnvironmentDeclaration | EnvironmentDefinition | None:
        return self._environments.get(name)

    def record_environment(self, declaration: EnvironmentDeclaration | EnvironmentDefinition) -> None:
        if self.mode != ExecutionMode.ACTIVE_EXECUTION:
            raise ValueError("Environment registration requires active execution")
        name = declaration.name
        if self._environment_scopes:
            self._environment_scopes[-1].setdefault(name, self._environments.get(name))
        self._environments[name] = declaration
        for command in (name, "end" + name):
            key = (TokenKind.CONTROL_SEQUENCE, command)
            if self._meaning_scopes:
                self._meaning_scopes[-1].setdefault(key, self._meanings.get(key))
            self._meanings.pop(key, None)

    def lookup_definition(self, name: str, kind: TokenKind = TokenKind.CONTROL_SEQUENCE) -> StoredDefinition | EnvironmentDefinition | None:
        """Active characters and same-spelled control symbols have distinct meanings."""
        meaning = self.lookup_meaning(name, kind)
        return meaning if isinstance(meaning, (StoredDefinition, EnvironmentDefinition)) else None

    def record_collected_environment(self, definition: EnvironmentDefinition) -> None:
        self.record_environment(definition)
        for name in (definition.name, "end" + definition.name):
            self.record_meaning(name, definition)

    def lookup_capture_setting(self, name: str) -> ScannedArgument | None:
        return self._capture_settings.get(name)

    def record_capture_setting(self, name: str, value: ScannedArgument) -> None:
        if self.mode != ExecutionMode.ACTIVE_EXECUTION:
            raise ValueError("Capture settings require active execution")
        if self._capture_setting_scopes:
            self._capture_setting_scopes[-1].setdefault(name, self._capture_settings.get(name))
        self._capture_settings[name] = value

    def lookup_meaning(self, name: str, kind: TokenKind = TokenKind.CONTROL_SEQUENCE) -> LocalMeaning | None:
        meaning = self._meanings.get((kind, name))
        if meaning is None and kind == TokenKind.CONTROL_SEQUENCE:
            for prefix, span in self._uncertain_prefixes.items():
                if name.startswith(prefix):
                    return UncertainMeaning(span)
        return meaning

    def resolve_meaning(self, knowledge, name, kind=TokenKind.CONTROL_SEQUENCE):
        from ..engine.resolution import resolve_meaning
        meaning = resolve_meaning(self, knowledge, name, kind)
        if (isinstance(meaning, TokenListMeaning) and meaning.span is not None
                and meaning.format_origin == "latex-file-hooks/2026-06-01"):
            self.hooks.context_reads.add(meaning.span.basis.occurrence_id)
        return meaning

    def invalidate_writes(self, summary, span) -> bool:
        """Invalidate named meanings, including fallback knowledge, with TeX scope.

        Namespace barriers also cover meanings not yet queried. A fresh explicit
        declaration overrides the barrier; local barriers disappear on group exit.
        """
        names = summary.meanings
        global_ = summary.scope != "local"
        keys = {key for key in self._meanings if key[0] == TokenKind.CONTROL_SEQUENCE and names.contains(key[1])}
        keys.update((TokenKind.CONTROL_SEQUENCE, name) for name in names.names)
        if global_:
            keys.update(key for saved in self._meaning_scopes for key in saved
                        if key[0] == TokenKind.CONTROL_SEQUENCE and names.contains(key[1]))

        def uncertain(value):
            if isinstance(value, (BooleanMeaning, BoundMeaning, CharacterCodeMeaning, TokenListMeaning, UndefinedMeaning, PrimitiveMeaning)):
                return value if value.uncertain is not None else replace(value, uncertain=span)
            return value if isinstance(value, UncertainMeaning) else UncertainMeaning(span)

        changed = self.integer_parameters.invalidate(span, names=summary.registers, global_=global_)
        changed |= self.token_registers.invalidate(span, names=summary.registers, global_=global_)
        # Register summaries currently have no font identity domain. Conservatively
        # retain uncertainty rather than publishing a value after unknown writes.
        if summary.registers:
            changed |= self.fonts.invalidate(span)
            changed |= self.state_cells.invalidate(span)
        for key in keys:
            previous = self._meanings.get(key)
            if not global_ and self._meaning_scopes:
                self._meaning_scopes[-1].setdefault(key, previous)
            self._meanings[key] = uncertain(previous)
            changed |= self._meanings[key] != previous
            if global_:
                for saved in self._meaning_scopes:
                    outer = saved.get(key, previous)
                    saved[key] = uncertain(outer)
                    changed |= saved[key] != outer
        for prefix in names.prefixes:
            changed |= prefix not in self._uncertain_prefixes
            self._uncertain_prefixes.setdefault(prefix, span)
            if global_:
                for saved in self._scope_stack:
                    changed |= prefix not in saved.uncertain_prefixes
                    saved.uncertain_prefixes.setdefault(prefix, span)
        return changed

    def meaning_names(self):
        """Names whose current author meaning can affect structural observation."""
        return {name for kind, name in self._meanings if kind == TokenKind.CONTROL_SEQUENCE}

    def conditional_rule(self, name: str, knowledge) -> ConditionalRule | None:
        """Resolve nesting from the current meaning, including local shadows."""
        meaning = self.lookup_meaning(name)
        if meaning is None:
            meaning = self.engine_profile.lookup(name)
        if isinstance(meaning, PrimitiveMeaning):
            if meaning.uncertain is not None:
                raise ReadingIssue("uncertain_meaning", "Primitive meaning may have changed", causes=(meaning.uncertain,))
            return meaning.operand if meaning.operation == "conditional.route" else None
        if isinstance(meaning, UncertainMeaning):
            raise ReadingIssue("uncertain_meaning", f"Meaning of {name!r} depends on retained source at {meaning.span}", causes=(meaning.span,))
        if isinstance(meaning, UndefinedMeaning) and meaning.uncertain is not None:
            raise ReadingIssue("uncertain_meaning", f"Undefined state of {name!r} may have changed",
                               causes=(meaning.uncertain,))
        if isinstance(meaning, BooleanMeaning):
            if meaning.uncertain is not None:
                # Even its nesting meaning may have changed, not just its value.
                raise ReadingIssue("uncertain_boolean", f"Meaning of {name!r} may have changed at "
                                   f"{meaning.uncertain.basis.source_id}:{meaning.uncertain.start}", causes=(meaning.uncertain,))
            if meaning.target is not None:
                return None  # A setter has macro meaning; it does not nest while skipping.
            return ConditionalRule("opener", "always_true" if meaning.truth else "always_false", 0)
        if isinstance(meaning, BoundMeaning):
            if meaning.uncertain is not None:
                raise ReadingIssue("uncertain_meaning", f"Copied meaning may have changed at {meaning.uncertain}", causes=(meaning.uncertain,))
            return meaning.profile.conditional if meaning.profile else None
        return None if meaning is not None else knowledge.resolve_conditional(name)

    def invalidate_observed_meanings(self, span) -> bool:
        """Keep unexecuted effects explicit; no inference of arbitrary macro purity.

        Unknown code can make global assignments, so suspended outer meanings are
        also uncertain. A later fresh declaration can establish a new local meaning.
        This is a bounded guard, not a general context dependency analysis.
        """
        changed = self.integer_parameters.invalidate(span)
        changed |= self.fonts.invalidate(span)
        changed |= self.read_streams.invalidate(span)
        changed |= self.token_registers.invalidate(span)
        changed |= self.state_cells.invalidate(span)
        for meanings in (self._meanings, *self._meaning_scopes):
            for key, meaning in list(meanings.items()):
                if isinstance(meaning, (BooleanMeaning, BoundMeaning, CharacterCodeMeaning, TokenListMeaning, UndefinedMeaning, PrimitiveMeaning)) and meaning.uncertain is None:
                    meanings[key] = replace(meaning, uncertain=span)
                    changed = True
        return changed

    def record_meaning(self, name: str, meaning: LocalMeaning,
                       kind: TokenKind = TokenKind.CONTROL_SEQUENCE, *, global_: bool = False,
                       scope_cause: SourceSpan | None = None) -> None:
        """Install a meaning, cancelling older restorations for a global write.

        This is equivalent to retaining a level-one meaning during TeX's unsave:
        no enclosing journal may restore a value predating this write. A later
        local write saves this global value normally. Other names and lexical
        state keep their existing restoration entries.
        """
        if self.mode != ExecutionMode.ACTIVE_EXECUTION:
            raise ValueError("Meanings can only be installed in active execution")
        key = (kind, name)
        if scope_cause is not None:
            # Both assignment scopes install this value now. On any enclosing
            # exit it may persist or restore a prior value, so neither wins.
            for saved in self._meaning_scopes:
                saved[key] = UncertainMeaning(scope_cause)
        elif global_:
            for saved in self._meaning_scopes:
                saved.pop(key, None)
        elif self._meaning_scopes:
            self._meaning_scopes[-1].setdefault(key, self._meanings.get(key))
        self._meanings[key] = meaning

    def record_definition(self, definition: StoredDefinition, *, global_: bool = False,
                          scope_cause: SourceSpan | None = None) -> None:
        """Publish a completed definition with the operation's assignment scope."""
        self.record_meaning(definition.target.value, definition, definition.target.kind,
                            global_=global_, scope_cause=scope_cause)

    def invalidate_meanings(self, names, span) -> None:
        """Observed declarations are not installed; neither may old meanings win.

        Possible global prefixes are uninterpreted, so outer journals are also
        invalidated. A later established declaration can replace this uncertainty.
        """
        for name in names:
            key = (TokenKind.CONTROL_SEQUENCE, name)
            self._meanings[key] = UncertainMeaning(span)
            for saved in self._meaning_scopes:
                if key in saved:
                    saved[key] = UncertainMeaning(span)

    @contextmanager
    def execution_mode(self, mode: ExecutionMode) -> Iterator[None]:
        previous = self.mode
        self.mode = mode
        try:
            yield
        finally:
            self.mode = previous

    @contextmanager
    def argument_scanning(self) -> Iterator[None]:
        with self.execution_mode(ExecutionMode.ARGUMENT_SCANNING):
            yield

    @contextmanager
    def stored_definition(self) -> Iterator[None]:
        with self.execution_mode(ExecutionMode.STORED_DEFINITION):
            yield

    @contextmanager
    def skipped_branch(self) -> Iterator[None]:
        with self.execution_mode(ExecutionMode.SKIPPED_BRANCH):
            yield

    def push_scope(self) -> None:
        self._scope_stack.append(self._snapshot())
        self._meaning_scopes.append({})
        self._environment_scopes.append({})
        self._capture_setting_scopes.append({})
        self.configurations.push()
        self.integer_parameters.push()
        self.token_registers.push()
        self.state_cells.push()
        self.after_groups.append([])

    @property
    def scope_depth(self) -> int:
        """Number of lexical snapshots; structural group kinds belong to routing."""
        return len(self._scope_stack)

    def assign_catcode(self, character, category, *, global_=False):
        self.catcodes[character] = category
        if global_:
            for saved in self._scope_stack:
                saved.catcodes[character] = category

    def assign_endlinechar(self, value, *, global_=False):
        self.endlinechar = value
        if global_:
            for saved in self._scope_stack:
                saved.endlinechar = value

    def pop_scope(self) -> bool:
        if not self._scope_stack:
            return False
        self._restore(self._scope_stack.pop())
        self.configurations.pop()
        self.integer_parameters.pop()
        self.token_registers.pop()
        self.state_cells.pop()
        self.after_groups.pop()
        for key, previous in self._meaning_scopes.pop().items():
            if previous is None:
                self._meanings.pop(key, None)
            else:
                self._meanings[key] = previous
        for name, previous in self._environment_scopes.pop().items():
            if previous is None:
                self._environments.pop(name, None)
            else:
                self._environments[name] = previous
        for name, previous in self._capture_setting_scopes.pop().items():
            if previous is None:
                self._capture_settings.pop(name, None)
            else:
                self._capture_settings[name] = previous
        return True

    @contextmanager
    def lexical_scope(self) -> Iterator[None]:
        self.push_scope()
        try:
            yield
        finally:
            self.pop_scope()

    def apply_profile(self, profile: EffectiveReadingProfile) -> bool:
        """Apply immediate effects, not a literal scanner or command's full behavior.

        Refuse unresolved results and interpolation plans rather than silently
        presenting them as completely applied. In inactive modes nothing changes.
        """
        if not isinstance(profile, EffectiveReadingProfile):
            raise TypeError("Only a resolved reading profile can be applied")
        if self.mode != ExecutionMode.ACTIVE_EXECUTION:
            return False
        if profile.interpolations:
            raise ValueError("Interpolation requires a literal dispatcher")
        if profile.action == "assign_catcode_dynamic":
            raise ValueError("Assignment requires argument scanning and execution routing")
        if profile.family == "configuration_command":
            raise ValueError("Configuration requires argument scanning and execution routing")
        if profile.state_management and profile.state_management.scope != "local":
            raise ValueError("Global assignments require the execution dispatcher")
        unknown = set(profile.reader_parameters) - {"endlinechar"}
        if unknown:
            raise ValueError(f"Unsupported reader parameters: {sorted(unknown)}")

        action = profile.action
        if action == "push_lexical_scope":
            self.push_scope()
            return True
        if action == "pop_lexical_scope":
            return self.pop_scope()
        if action == "expl3_lexical_exit":
            if self.expl3_active:
                for char, code in self.expl3_saved_catcodes.items():
                    self.catcodes[char] = code
                self.endlinechar = self.expl3_saved_endlinechar
                self.expl3_saved_catcodes = {}
                self.expl3_active = False
            return True
        if action == "expl3_lexical_enter" and not self.expl3_active:
            if profile.state_management is None:
                raise ValueError("ExplSyntaxOn requires a state management contract")
            chars = profile.state_management.saved_parameters.get("catcodes", [])
            self.expl3_saved_catcodes = {char: self.catcodes[char] for char in chars}
            self.expl3_saved_endlinechar = self.endlinechar
            self.expl3_active = True

        # Repeated ExplSyntaxOn reapplies effects, without overwriting the baseline.
        for layer in profile.catcode_layers:
            self.catcodes.apply_layer(layer)
        for char, code in profile.catcode_overrides.items():
            self.catcodes[char] = code
        if "endlinechar" in profile.reader_parameters:
            self.endlinechar = profile.reader_parameters["endlinechar"]
        return True
