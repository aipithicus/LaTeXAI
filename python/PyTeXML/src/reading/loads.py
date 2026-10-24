"""Ordered source-visible load facts, independent of binding availability.

Absence is only established under the source-visible loading assumption. An
observed possible load or an unread local-code suffix makes negative queries
unknown; positive facts remain usable. Nothing here reads files or activates code.
"""
class SourceLoadState:
    def __init__(self):
        self.loaded = {}
        self.uncertainties = []

    def record(self, kind, name, unit_id):
        self.loaded[(kind, name)] = unit_id

    def invalidate(self, unit_id):
        if unit_id not in self.uncertainties:
            self.uncertainties.append(unit_id)

    def query(self, kind, name):
        key = (kind, name)
        if key in self.loaded:
            return True, [self.loaded[key]], []
        if self.uncertainties:
            return None, [], list(self.uncertainties)
        return False, [], []
