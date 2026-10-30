"""Scoped immutable state values for glue, font selections and format data."""
from dataclasses import dataclass, replace
from ..reading.contracts import ReadingIssue


@dataclass(frozen=True, slots=True)
class Cell:
    value: object
    span: object = None
    uncertain: object = None


class StateCells:
    def __init__(self):
        self.values, self.scopes = {}, []
        self.default_uncertain = None

    def copy(self):
        result = StateCells()
        result.values = dict(self.values)
        result.scopes = [dict(s) for s in self.scopes]
        result.default_uncertain = self.default_uncertain
        return result

    def push(self):
        self.scopes.append({})

    def pop(self):
        for key, value in self.scopes.pop().items():
            if value is None:
                self.values.pop(key, None)
            else:
                self.values[key] = value

    def assign(self, key, value, span, *, global_=False):
        if global_:
            for saved in self.scopes:
                saved.pop(key, None)
        elif self.scopes:
            self.scopes[-1].setdefault(key, self.values.get(key))
        self.values[key] = Cell(value, span)

    def read(self, key):
        value = self.values.get(key)
        if value is None:
            raise ReadingIssue("unavailable_state", f"No established state for {key!r}")
        if value.uncertain is not None:
            raise ReadingIssue("uncertain_state", f"State {key!r} may have changed", causes=(value.uncertain,))
        return value.value

    def initial(self, value):
        if self.default_uncertain is not None:
            raise ReadingIssue("uncertain_state", "Initial state may have changed", causes=(self.default_uncertain,))
        return value

    def invalidate(self, span):
        changed = self.default_uncertain is None
        self.default_uncertain = self.default_uncertain or span
        for values in (self.values, *self.scopes):
            for key, value in list(values.items()):
                if value is not None and value.uncertain is None:
                    values[key] = replace(value, uncertain=span)
                    changed = True
        return changed
