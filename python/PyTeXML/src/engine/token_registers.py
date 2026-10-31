"""Scoped token cells; stored lists keep original tokens and provenance."""
from dataclasses import replace
from ..reading.contracts import ReadingIssue, TokenListMeaning
from .causal import cell_read, cell_write


class TokenRegisters:
    def __init__(self, *, initial=False):
        self.initial, self.values, self.scopes = initial, {}, []
        self.default_uncertain = None

    def copy(self):
        result = TokenRegisters(initial=self.initial)
        result.values = dict(self.values)
        result.scopes = [dict(s) for s in self.scopes]
        result.default_uncertain = self.default_uncertain
        return result

    def push(self):
        self.scopes.append({})

    def pop(self):
        for key, old in self.scopes.pop().items():
            if old is None:
                self.values.pop(key, None)
            else:
                self.values[key] = old
            cell_write(self, key, old.replacement_tokens if old is not None else () if self.initial else None, restore=True)

    def assign(self, key, tokens, span, *, global_=False):
        if global_:
            for saved in self.scopes:
                saved.pop(key, None)
        elif self.scopes:
            self.scopes[-1].setdefault(key, self.values.get(key))
        self.values[key] = TokenListMeaning(span, tuple(tokens))
        cell_write(self, key, tuple(tokens), global_=global_)

    def read(self, key):
        value = self.values.get(key)
        if value is None:
            if self.default_uncertain is not None:
                raise ReadingIssue("uncertain_tokens", "Initial token-register state may have changed",
                                   causes=(self.default_uncertain,))
            if self.initial:
                return cell_read(self, key, ())
            raise ReadingIssue("unavailable_tokens", "Token register has no established value")
        if value.uncertain is not None:
            raise ReadingIssue("uncertain_tokens", "Token register may have changed", causes=(value.uncertain,))
        return cell_read(self, key, value.replacement_tokens)

    def invalidate(self, span, *, names=None, global_=True):
        changed = False
        if names is None:
            changed = self.default_uncertain is None
            self.default_uncertain = self.default_uncertain or span
        else:
            # A named write can affect a previously unread, initially empty cell.
            for key in names:
                if key.startswith("toks:") and key not in self.values:
                    if not global_ and self.scopes:
                        self.scopes[-1].setdefault(key, None)
                    self.values[key] = TokenListMeaning(span, (), uncertain=span)
                    changed = True
        for values in (self.values, *self.scopes) if global_ else (self.values,):
            for key, value in list(values.items()):
                if names is not None and key not in names:
                    continue
                if value is not None and value.uncertain is None:
                    if not global_ and self.scopes:
                        self.scopes[-1].setdefault(key, value)
                    values[key] = replace(value, uncertain=span)
                    changed = True
        return changed
