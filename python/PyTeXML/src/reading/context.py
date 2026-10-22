"""Document-local execution mode and scoped lexical state."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Iterator
from .contracts import EffectiveReadingProfile, MouthBaseline
from .tex_reader import CatCode, CatcodeTable


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

    def copy(self) -> _ScopeSnapshot:
        return _ScopeSnapshot(self.catcodes.copy(), self.endlinechar,
                              self.expl3_active, dict(self.expl3_saved_catcodes),
                              self.expl3_saved_endlinechar)


class ReaderContext:
    """Immediate lexical state; source dispatch and global assignments live above it.

    Literal callers establish a lexical_scope(), enter the resolved profile, and
    restore it on exit. A live TexReader can share catcodes; the caller must also
    synchronize endline_char before it loads subsequent physical lines.
    """

    def __init__(self, *, baseline: MouthBaseline, catcodes: CatcodeTable | None = None,
                 endlinechar: int | None = None,
                 mode: ExecutionMode = ExecutionMode.ACTIVE_EXECUTION):
        self.baseline = baseline
        self.catcodes = catcodes.copy() if catcodes is not None else baseline.new_catcodes()
        self.endlinechar = baseline.endlinechar if endlinechar is None else endlinechar
        self.mode = mode
        self.expl3_active = False
        self.expl3_saved_catcodes: dict[str, CatCode] = {}
        self.expl3_saved_endlinechar = self.endlinechar
        self._scope_stack: list[_ScopeSnapshot] = []

    def _snapshot(self) -> _ScopeSnapshot:
        return _ScopeSnapshot(self.catcodes.copy(), self.endlinechar,
                              self.expl3_active, dict(self.expl3_saved_catcodes),
                              self.expl3_saved_endlinechar)

    def _restore(self, saved: _ScopeSnapshot) -> None:
        self.catcodes.restore_from(saved.catcodes)
        self.endlinechar = saved.endlinechar
        self.expl3_active = saved.expl3_active
        self.expl3_saved_catcodes = dict(saved.expl3_saved_catcodes)
        self.expl3_saved_endlinechar = saved.expl3_saved_endlinechar

    def copy(self) -> ReaderContext:
        ctx = ReaderContext(baseline=self.baseline, mode=self.mode)
        ctx._restore(self._snapshot())
        ctx._scope_stack = [saved.copy() for saved in self._scope_stack]
        return ctx

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

    @property
    def scope_depth(self) -> int:
        """Number of lexical snapshots; structural group kinds belong to routing."""
        return len(self._scope_stack)

    def pop_scope(self) -> bool:
        if not self._scope_stack:
            return False
        self._restore(self._scope_stack.pop())
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
