"""Source-character intervals and normalized coverage, without source text copies.

Each basis denotes one immutable decoded source occurrence. Identity is deliberately
in-memory and exact: equal filenames, lengths or contents do not identify the same
occurrence. Durable buffer revisions and other coordinate domains belong to the
future source store; this module does not accept token or mouth-view offsets.
"""
from __future__ import annotations

from dataclasses import dataclass
from heapq import merge
from typing import Iterable, Iterator


def _offset(value: int, length: int) -> None:
    if type(value) is not int:
        raise TypeError("Source offsets must be integers")
    if not 0 <= value <= length:
        raise ValueError("Source offset is outside this basis")


@dataclass(frozen=True, slots=True, eq=False)
class SourceBasis:
    """Identity and extent of one source occurrence; equality is object identity."""
    source_id: str
    occurrence_id: int
    length: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or type(self.occurrence_id) is not int:
            raise TypeError("Expected a source name and integer occurrence ID")
        if type(self.length) is not int:
            raise TypeError("Source length must be an integer")
        if self.length < 0:
            raise ValueError("Source length must be nonnegative")

    def span(self, start: int, end: int) -> SourceSpan:
        return SourceSpan(self, start, end)

    @property
    def whole(self) -> SourceSpan:
        return self.span(0, self.length)

    def require(self, span: SourceSpan) -> None:
        if not isinstance(span, SourceSpan):
            raise TypeError("Expected a SourceSpan")
        if span.basis is not self:
            raise ValueError("Source span belongs to a different basis")


@dataclass(frozen=True, slots=True)
class SourceSpan:
    basis: SourceBasis
    start: int
    end: int

    def __post_init__(self) -> None:
        if not isinstance(self.basis, SourceBasis):
            raise TypeError("A source span requires a SourceBasis")
        _offset(self.start, self.basis.length)
        _offset(self.end, self.basis.length)
        if self.start > self.end:
            raise ValueError("Source span ends before it starts")


@dataclass(frozen=True, slots=True, init=False)
class SpanSet:
    """Sorted, disjoint, nonempty coverage intervals; overlap/adjacency is merged.

    Conversion to coverage deliberately loses record identity and empty locations.
    Keep the original region/diagnostic records when that information is needed.
    Construction accepts unordered spans. Operations sweep normalized intervals;
    they never allocate a per-character mask or touch source text.
    """
    basis: SourceBasis
    spans: tuple[SourceSpan, ...]

    def __init__(self, basis: SourceBasis, spans: Iterable[SourceSpan] = ()):
        if not isinstance(basis, SourceBasis):
            raise TypeError("A span set requires a SourceBasis, even when empty")
        pending = list(spans)
        for span in pending:
            basis.require(span)
        pending.sort(key=lambda span: (span.start, span.end))
        normalized: list[SourceSpan] = []
        for span in pending:
            if span.start == span.end:
                continue
            if normalized and span.start <= normalized[-1].end:
                previous = normalized[-1]
                normalized[-1] = basis.span(previous.start, max(previous.end, span.end))
            else:
                normalized.append(span)
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "spans", tuple(normalized))

    def _require(self, other: SpanSet) -> None:
        if not isinstance(other, SpanSet):
            raise TypeError("Expected a SpanSet")
        if self.basis is not other.basis:
            raise ValueError("Cannot combine coverage from different source bases")

    def __iter__(self) -> Iterator[SourceSpan]:
        return iter(self.spans)

    def __bool__(self) -> bool:
        return bool(self.spans)

    @property
    def covered_length(self) -> int:
        return sum(span.end - span.start for span in self.spans)

    def union(self, other: SpanSet) -> SpanSet:
        self._require(other)
        return SpanSet(self.basis, merge(self.spans, other.spans, key=lambda s: (s.start, s.end)))

    def intersection(self, other: SpanSet) -> SpanSet:
        self._require(other)
        result = []
        left = right = 0
        while left < len(self.spans) and right < len(other.spans):
            a, b = self.spans[left], other.spans[right]
            start, end = max(a.start, b.start), min(a.end, b.end)
            if start < end:
                result.append(self.basis.span(start, end))
            if a.end <= b.end:
                left += 1
            else:
                right += 1
        return SpanSet(self.basis, result)

    def difference(self, other: SpanSet) -> SpanSet:
        self._require(other)
        result = []
        right = 0
        for a in self.spans:
            start = a.start
            while right < len(other.spans) and other.spans[right].end <= start:
                right += 1
            while right < len(other.spans) and other.spans[right].start < a.end:
                b = other.spans[right]
                if start < b.start:
                    result.append(self.basis.span(start, b.start))
                start = max(start, b.end)
                if start >= a.end:
                    break  # This subtracting interval can also cover the next a.
                right += 1
            if start < a.end:
                result.append(self.basis.span(start, a.end))
        return SpanSet(self.basis, result)

    def clip(self, window: SourceSpan) -> SpanSet:
        return self.intersection(SpanSet(self.basis, (window,)))

    def complement(self, window: SourceSpan) -> SpanSet:
        """Complement is always relative to an explicitly bounded window."""
        return SpanSet(self.basis, (window,)).difference(self)

    def covers(self, other: SourceSpan | SpanSet) -> bool:
        selection = SpanSet(self.basis, (other,)) if isinstance(other, SourceSpan) else other
        self._require(selection)
        return not selection.difference(self)

    def partition(self, boundaries: Iterable[int]) -> tuple[SourceSpan, ...]:
        """Split covered intervals at given offsets; retain gaps and empty coverage.

        Unlike a SpanSet, the returned sequence intentionally retains adjacency.
        Duplicate/end-point cuts add no empty segments. It carries no claim IDs.
        """
        points = list(boundaries)
        for point in points:
            _offset(point, self.basis.length)
        points = sorted(set(points))
        result = []
        index = 0
        for span in self.spans:
            start = span.start
            while index < len(points) and points[index] <= start:
                index += 1
            while index < len(points) and points[index] < span.end:
                result.append(self.basis.span(start, points[index]))
                start = points[index]
                index += 1
            result.append(self.basis.span(start, span.end))
        return tuple(result)
