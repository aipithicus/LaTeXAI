"""Document hook state. Captures are immutable; registrations are global.

The first format bridge executes the top-level label only. Other labels and
ordering operations remain explicit uncertainty, never an empty hook.
"""
from dataclasses import dataclass

from ..reading.contracts import ReadingIssue
from ..reading.spans import SourceSpan
from ..reading.tex_reader import Token


@dataclass(frozen=True, slots=True)
class HookCode:
    tokens: tuple[Token, ...]
    registration: SourceSpan


class HookState:
    def __init__(self):
        self.code: dict[str, tuple[HookCode, ...]] = {}
        self.uncertain: dict[str, SourceSpan] = {}
        self.version = 0
        self.context_reads: set[int] = set()
        self.context_stack: list[tuple] = []

    def copy(self):
        other = HookState()
        other.code, other.uncertain = dict(self.code), dict(self.uncertain)
        other.version = self.version
        other.context_reads = set(self.context_reads)
        other.context_stack = list(self.context_stack)
        return other

    def add(self, name, tokens, span, *, label="top-level"):
        self.version += 1
        if label != "top-level":
            self.uncertain[name] = span
        self.code[name] = self.code.get(name, ()) + (HookCode(tuple(tokens), span),)

    def invalidate(self, name, span):
        self.version += 1
        self.uncertain[name] = span

    def invalidate_effects(self, summary, span):
        """Guard observed hook state using the reader's bounded effect contract."""
        if summary is not None and summary.complete:
            names = summary.hooks
        else:
            names = self.code.keys() | self.uncertain.keys()
        changed = False
        for name in names:
            if name not in self.uncertain:
                self.invalidate(name, span)
                changed = True
        return changed

    def remove(self, name, *, label="top-level"):
        self.version += 1
        if label == "top-level":
            self.code[name] = ()
        # Unsupported labels/order cannot be made known by deleting one label.

    def bodies(self, name):
        cause = self.uncertain.get(name) or self.uncertain.get("*")
        if cause is not None:
            raise ReadingIssue("hook_order", f"Hook {name!r} has unresolved registration/order semantics",
                               causes=(cause,))
        return self.code.get(name, ())

    def relevant(self, names):
        return bool(self.uncertain.get("*")) or any(
            name in self.code or name in self.uncertain for name in names)
