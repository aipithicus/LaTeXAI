"""Established font parameter arrays, independent of layout and font loading.

The source/format owner supplies metrics through establish(). TeX font parameters
are global even inside a group; transactions still restore failed requests.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType
from ..reading.contracts import ReadingIssue


@dataclass(frozen=True, slots=True)
class FontParameters:
    dimensions: tuple[int, ...]
    uncertain: object = None
    metric: tuple[str, int] | None = None


class FontState:
    def __init__(self, *, initial=False):
        self.values = {"nullfont": FontParameters((0,) * 7)} if initial else {}
        self.latest = "nullfont" if initial else None
        self.sources = None
        self.identifiers = {"nullfont": "nullfont"} if initial else {}
        self._metrics = {}

    def configure(self, sources):
        if any(type(value) is not bytes for value in sources.values()):
            raise TypeError("Font inventory requires TFM bytes")
        self.sources = MappingProxyType(dict(sources))
        self._metrics = {}

    def copy(self):
        result = FontState()
        result.values, result.latest = dict(self.values), self.latest
        result.sources, result.identifiers = self.sources, dict(self.identifiers)
        result._metrics = dict(self._metrics)
        return result

    def establish(self, identity, dimensions, *, metric=None):
        if identity in self.values:
            raise ValueError("Font identity is already established")
        values = tuple(dimensions)
        if len(values) > 10000 or any(type(v) is not int or abs(v) > 1073741823 for v in values):
            raise ValueError("Invalid or excessive font parameter array")
        self.values[identity] = FontParameters(values, metric=metric)
        self.latest = identity

    def parameters(self, identity):
        value = self.values.get(identity)
        if value is None:
            raise ReadingIssue("unavailable_font", "Font parameters have not been established")
        if value.uncertain is not None:
            raise ReadingIssue("uncertain_font", "Retained code may have changed font parameters", causes=(value.uncertain,))
        return value.dimensions

    def cell(self, identity, index, *, writing=False):
        values = self.parameters(identity)
        if index <= 0 or (index > len(values) and (not writing or identity != self.latest)):
            raise ReadingIssue("font_parameter_index", "Only the most recently loaded font can extend its parameters")
        if index > 10000:
            raise ReadingIssue("font_parameter_budget", "Font parameter array exceeds the bounded state budget")
        return values

    def assign(self, identity, index, value):
        values = self.cell(identity, index, writing=True)
        values += (0,) * max(0, index - len(values))
        self.values[identity] = replace(self.values[identity], dimensions=values[:index - 1] + (value,) + values[index:])

    def metrics(self, identity):
        from .tfm import Metrics, metrics
        self.parameters(identity)
        if identity == "nullfont":
            return Metrics((None,) * 256, (), ())
        if identity not in self._metrics:
            entry = self.values[identity].metric
            if entry is None or self.sources is None:
                raise ReadingIssue("unavailable_glyph_metrics", "Font has no established glyph metric source")
            name, size = entry
            data = self.sources.get(name, self.sources.get(name + ".tfm"))
            if data is None:
                raise ReadingIssue("unavailable_glyph_metrics", "Glyph metrics are absent from the inventory")
            self._metrics[identity] = metrics(data, at=size)
        return self._metrics[identity]

    def invalidate(self, span):
        changed = any(v.uncertain is None for v in self.values.values())
        self.values = {k: replace(v, uncertain=v.uncertain or span) for k, v in self.values.items()}
        return changed
