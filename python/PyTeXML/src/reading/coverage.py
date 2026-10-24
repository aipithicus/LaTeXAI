"""Three-valued coverage queries over established reading records.

This consumes dispatcher output; it never drives execution or authorizes edits.
Nonmatching coverage is relative to a specific query, not evidence of ordinary
prose or permission to normalize source. Missing observations remain unknown.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Literal

from .contracts import (LiteralRegion, ReadingBoundary, SkippedRegion, StoredDefinition,
                        EnvironmentDefinition, SourceCommand, SourceEnd, DeferredRegion)
from .spans import SourceBasis, SourceSpan, SpanSet
from .tex_reader import ReadEvent


class CoverageState(str, Enum):
    MATCH = "match"
    NONMATCH = "nonmatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CoverageSegment:
    span: SourceSpan
    state: CoverageState


@dataclass(frozen=True, slots=True)
class Coverage:
    """Disjoint matches/unknown within one window; the rest is known nonmatch.

    Boolean composition uses strong three-valued logic. A known match settles an
    OR, and a known nonmatch settles an AND; otherwise uncertainty is retained.
    Operands must have the same exact window. Use restrict() explicitly first.
    """
    window: SourceSpan
    matches: SpanSet
    unknown: SpanSet

    def __post_init__(self) -> None:
        universe = SpanSet(self.window.basis, (self.window,))
        if not universe.covers(self.matches) or not universe.covers(self.unknown):
            raise ValueError("Query coverage extends outside its window")
        if self.matches.intersection(self.unknown):
            raise ValueError("Matching and unknown coverage must be disjoint")

    @property
    def nonmatches(self) -> SpanSet:
        return self.matches.union(self.unknown).complement(self.window)

    def _require(self, other: Coverage) -> None:
        if not isinstance(other, Coverage):
            raise TypeError("Expected a Coverage query")
        if self.window != other.window:
            raise ValueError("Coverage queries require the same source basis and window")

    def negate(self) -> Coverage:
        return Coverage(self.window, self.nonmatches, self.unknown)

    def union(self, other: Coverage) -> Coverage:
        self._require(other)
        matches = self.matches.union(other.matches)
        unknown = self.unknown.union(other.unknown).difference(matches)
        return Coverage(self.window, matches, unknown)

    def intersection(self, other: Coverage) -> Coverage:
        self._require(other)
        matches = self.matches.intersection(other.matches)
        nonmatches = self.nonmatches.union(other.nonmatches)
        unknown = matches.union(nonmatches).complement(self.window)
        return Coverage(self.window, matches, unknown)

    def difference(self, other: Coverage) -> Coverage:
        self._require(other)
        return self.intersection(other.negate())

    def restrict(self, window: SourceSpan) -> Coverage:
        self.window.basis.require(window)
        if not self.window.start <= window.start <= window.end <= self.window.end:
            raise ValueError("Restricted window must lie inside the original query window")
        return Coverage(window, self.matches.clip(window), self.unknown.clip(window))

    def partition(self, boundaries: Iterable[int] = ()) -> tuple[CoverageSegment, ...]:
        """Cover the query window once, labeling each segment; no text is copied."""
        cuts = tuple(boundaries)
        segments = [CoverageSegment(span, state)
                    for spans, state in ((self.matches, CoverageState.MATCH),
                                         (self.nonmatches, CoverageState.NONMATCH),
                                         (self.unknown, CoverageState.UNKNOWN))
                    for span in spans.partition(cuts)]
        return tuple(sorted(segments, key=lambda segment: segment.span.start))


ReadingItem = ReadEvent | LiteralRegion | StoredDefinition | EnvironmentDefinition | SkippedRegion | ReadingBoundary | SourceCommand | SourceEnd | DeferredRegion


@dataclass(frozen=True, slots=True, init=False)
class ReadingCoverage:
    """Snapshot of an ordered, non-overlapping stream of top-level reading items.

    Partial streams and gaps are allowed and stay unknown. Boundaries must be
    terminal and retain their diagnostic anchors independently of coverage. Only
    source extents are coalesced; literal/definition/skipped records retain their identity,
    including records with empty bodies. Ordinary per-token events are not stored.
    """
    basis: SourceBasis
    observed: SpanSet
    unknown: SpanSet
    literal_regions: tuple[LiteralRegion, ...]
    stored_definitions: tuple[StoredDefinition | EnvironmentDefinition, ...]
    skipped_regions: tuple[SkippedRegion, ...]
    diagnostics: tuple[ReadingBoundary, ...]
    deferred_regions: tuple[DeferredRegion, ...]

    def __init__(self, basis: SourceBasis, items: Iterable[ReadingItem]):
        if not isinstance(basis, SourceBasis):
            raise TypeError("Reading coverage requires a SourceBasis")
        observed: list[SourceSpan] = []
        literals, definitions, skipped, diagnostics, deferred = [], [], [], [], []
        end = 0
        for item in items:
            if diagnostics:
                raise ValueError("A reading boundary must be the last item")
            if not isinstance(item, (ReadEvent, LiteralRegion, StoredDefinition, EnvironmentDefinition, SkippedRegion, ReadingBoundary, SourceCommand, SourceEnd, DeferredRegion)):
                raise TypeError("Expected a dispatcher reading item")
            basis.require(item.span)
            if isinstance(item, ReadingBoundary):
                basis.require(item.remainder)
                if item.remainder.start < end or item.remainder.end != basis.length:
                    raise ValueError("Boundary residue must be an unobserved source suffix")
                diagnostics.append(item)
                continue
            if item.span.start < end:
                raise ValueError("Reading items overlap or are out of source order")
            end = item.span.end
            if isinstance(item, DeferredRegion):
                deferred.append(item)
                continue  # Captured source is not established structural coverage.
            if isinstance(item, (LiteralRegion, StoredDefinition, EnvironmentDefinition)):
                parts = (item.opening, item.body, item.closing)
                for part in parts:
                    basis.require(part)
                if (parts[0].start != item.span.start or parts[-1].end != item.span.end
                        or parts[0].end != parts[1].start or parts[1].end != parts[2].start):
                    raise ValueError("Region parts must partition the region extent")
                (literals if isinstance(item, LiteralRegion) else definitions).append(item)
                if isinstance(item, LiteralRegion):
                    previous = item.body.start
                    for child in item.interpolations:
                        basis.require(child.span)
                        if not previous <= child.span.start <= child.span.end <= item.body.end:
                            raise ValueError("Interpolation extents must be ordered inside the literal body")
                        previous = child.span.end
                        deferred.append(child)
            if isinstance(item, SkippedRegion):
                if ((item.conditional.basis is basis and item.conditional.end > item.span.start)
                        or item.branch not in ("then", "else")):
                    raise ValueError("Skipped region requires an earlier conditional and a then/else branch")
                skipped.append(item)
            if item.span.start == item.span.end:
                continue
            if observed and observed[-1].end == item.span.start:
                observed[-1] = basis.span(observed[-1].start, item.span.end)
            else:
                observed.append(item.span)
        coverage = SpanSet(basis, observed).difference(SpanSet(basis, (r.span for r in deferred)))
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "observed", coverage)
        object.__setattr__(self, "unknown", coverage.complement(basis.whole))
        object.__setattr__(self, "literal_regions", tuple(literals))
        object.__setattr__(self, "stored_definitions", tuple(definitions))
        object.__setattr__(self, "skipped_regions", tuple(skipped))
        object.__setattr__(self, "diagnostics", tuple(diagnostics))
        object.__setattr__(self, "deferred_regions", tuple(deferred))

    def query(self, kind: Literal["literal", "definition", "skipped"], *,
              part: Literal["span", "body"] = "span", window: SourceSpan | None = None) -> Coverage:
        """Skipped extents exclude delimiters and have no separate body part."""
        if (kind not in ("literal", "definition", "skipped") or part not in ("span", "body")
                or (kind == "skipped" and part != "span")):
            raise ValueError("Expected literal/definition span/body coverage or skipped span coverage")
        window = self.basis.whole if window is None else window
        self.basis.require(window)
        records = {"literal": self.literal_regions, "definition": self.stored_definitions,
                   "skipped": self.skipped_regions}[kind]
        matches = SpanSet(self.basis, (getattr(record, part) for record in records)).clip(window).difference(self.unknown)
        return Coverage(window, matches, self.unknown.clip(window))
