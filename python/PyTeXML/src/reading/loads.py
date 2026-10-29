"""Load history and the current LaTeX marker meaning are different facts.

The format's load guard compares ver@<name>.<extension> with relax. Ordinary
definitions, aliases and scope restoration therefore affect subsequent requests.
The history supplies evidence, never an overriding second meaning table.
"""
from dataclasses import dataclass

from ..engine.primitive import PrimitiveMeaning
from .contracts import TokenListMeaning, UncertainMeaning, UndefinedMeaning


def load_marker(kind, name):
    return f"ver@{name}.{'cls' if kind == 'class' else 'sty'}"


@dataclass(frozen=True)
class LoadStatus:
    truth: bool | None
    load_units: tuple = ()
    definition_units: tuple = ()
    uncertainty_units: tuple = ()
    causes: tuple = ()


class SourceLoadState:
    def __init__(self):
        self.loaded = {}
        self.uncertainties = []

    def record(self, kind, name, unit_id, context, span):
        self.loaded[(kind, name)] = unit_id
        # latex.ltx 2026-06-01, load@onefile@withoptions: a global empty
        # marker precedes the file read. This bridge uses ordinary meanings;
        # source-executed loading will eventually own the same assignment.
        context.record_meaning(load_marker(kind, name), TokenListMeaning(
            span, (), format_origin="latex-load-marker/2026-06-01"), global_=True)

    def invalidate(self, unit_id):
        if unit_id not in self.uncertainties:
            self.uncertainties.append(unit_id)

    def query(self, kind, name, context):
        key = (kind, name)
        facts = (self.loaded[key],) if key in self.loaded else ()
        meaning = context.lookup_meaning(load_marker(kind, name))
        cause = meaning.span if isinstance(meaning, UncertainMeaning) else getattr(meaning, "uncertain", None)
        if cause is not None:
            return LoadStatus(None, facts, causes=(cause,))
        if meaning is not None:
            identifier = getattr(meaning, "unit_id", None)
            absent = isinstance(meaning, UndefinedMeaning) or (
                isinstance(meaning, PrimitiveMeaning) and meaning.operation == "execution.relax")
            return LoadStatus(not absent, facts, (identifier,) if identifier else ())
        if self.uncertainties:
            return LoadStatus(None, facts, uncertainty_units=tuple(self.uncertainties))
        return LoadStatus(False, facts)
