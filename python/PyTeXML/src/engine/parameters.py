"""Scoped integer parameter values, separate from assignable token meanings.

A copied primitive refers to the same parameter cell. No format-dependent
initial value is guessed: a read needs an established assignment. Unexecuted
writes invalidate values and saved outer values using their actual write scope.
"""
from dataclasses import dataclass, replace

from ..reading.contracts import ReadingIssue
from ..reading.spans import SourceSpan
from .causal import cell_read, cell_write


@dataclass(frozen=True, slots=True)
class IntegerValue:
    value: int | None
    span: SourceSpan
    uncertain: SourceSpan | None = None


class IntegerParameters:
    def __init__(self):
        self.values: dict[str, IntegerValue] = {}
        # TeX primitive initialization, not LaTeX-format parameter guesses.
        self.values.update((name, IntegerValue(value, None)) for name, value in
                           (("escapechar", 92), ("newlinechar", -1), ("globaldefs", 0)))
        self.scopes: list[dict[str, IntegerValue | None]] = []

    def copy(self):
        result = IntegerParameters()
        result.values = dict(self.values)
        result.scopes = [dict(saved) for saved in self.scopes]
        return result

    def push(self):
        self.scopes.append({})

    def pop(self):
        for key, previous in self.scopes.pop().items():
            if previous is None:
                self.values.pop(key, None)
            else:
                self.values[key] = previous
            cell_write(self, key, previous.value if previous is not None else None, restore=True)

    def assign(self, key, value, span, *, global_=False):
        if global_:
            for scope in self.scopes:
                scope.pop(key, None)
        elif self.scopes:
            self.scopes[-1].setdefault(key, self.values.get(key))
        self.values[key] = IntegerValue(value, span)
        cell_write(self, key, value, global_=global_)

    def read(self, key):
        current = self.values.get(key)
        if current is None:
            raise ReadingIssue("unavailable_integer", f"No established value for parameter {key!r}")
        if current.uncertain is not None:
            raise ReadingIssue("uncertain_integer", f"Parameter {key!r} may have changed",
                               causes=(current.uncertain,))
        return cell_read(self, key, current.value)

    def invalidate(self, span, *, names=None, global_=True):
        keys = set(self.values)
        if global_:
            keys.update(key for saved in self.scopes for key in saved)
        if names is not None:
            keys.intersection_update(names)

        def uncertain(value):
            if value is None:
                return IntegerValue(None, span, uncertain=span)
            return value if value.uncertain is not None else replace(value, uncertain=span)

        changed = False
        for key in keys:
            previous = self.values.get(key)
            if not global_ and self.scopes:
                self.scopes[-1].setdefault(key, previous)
            self.values[key] = uncertain(previous)
            changed |= self.values[key] != previous
            if global_:
                for saved in self.scopes:
                    outer = saved.get(key, previous)
                    saved[key] = uncertain(outer)
                    changed |= saved[key] != outer
        return changed
