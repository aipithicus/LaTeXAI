"""Piecewise source correspondence through edits, without text or filesystem I/O.

Copy runs are affine. Replacements relate whole extents; a query strictly inside
a replacement receives an enclosing range, never invented character offsets.
Zero-source runs are insertions; zero-output runs are deletions. Edits use the
current output coordinate system and compose without a text diff.
"""
from dataclasses import dataclass

from .spans import SourceSpan


@dataclass(frozen=True, slots=True)
class MappingRun:
    source: SourceSpan
    start: int
    end: int
    kind: str = "copy"

    def __post_init__(self):
        if self.kind not in {"copy", "replace", "insert"} or not 0 <= self.start <= self.end:
            raise ValueError("Invalid mapping run")
        if self.kind == "copy" and self.end - self.start != self.source.end - self.source.start:
            raise ValueError("Copy correspondence must preserve length")
        if self.kind == "insert" and self.source.start != self.source.end:
            raise ValueError("Insertions require a zero-width source anchor")

    def shifted(self, amount):
        return MappingRun(self.source, self.start + amount, self.end + amount, self.kind)


@dataclass(frozen=True, slots=True)
class ProjectedRange:
    start: int
    end: int
    relation: str


def project_run(run: MappingRun, span: SourceSpan) -> ProjectedRange | None:
    """Project an interest onto one run, excluding insertions at its boundaries."""
    source = run.source
    if source.basis is not span.basis:
        return None
    if span.start == span.end:
        # A cursor inside copied text is precise; a point in a replacement is not.
        if source.start <= span.start <= source.end and run.kind == "copy":
            point = run.start + span.start - source.start
            return ProjectedRange(point, point, "copy")
        if source.start < span.start < source.end:
            return ProjectedRange(run.start, run.end, "enclosing")
        return None
    if run.kind == "insert":
        if span.start < source.start < span.end:
            return ProjectedRange(run.start, run.end, "insert")
        return None
    start, end = max(span.start, source.start), min(span.end, source.end)
    if start >= end:
        return None
    if run.kind == "copy":
        return ProjectedRange(run.start + start - source.start,
                              run.start + end - source.start, "copy")
    relation = "replace" if span.start <= source.start and source.end <= span.end else "enclosing"
    return ProjectedRange(run.start, run.end, relation)


@dataclass(frozen=True, slots=True)
class EditMap:
    length: int
    runs: tuple[MappingRun, ...]

    def __post_init__(self):
        if self.length < 0 or any(r.end > self.length for r in self.runs):
            raise ValueError("Mapping extends outside output")

    @classmethod
    def copied(cls, span: SourceSpan):
        length = span.end - span.start
        return cls(length, (MappingRun(span, 0, length),))

    @classmethod
    def replaced(cls, span: SourceSpan, length: int):
        return cls(length, (MappingRun(span, 0, length, "insert" if span.start == span.end else "replace"),))

    def project(self, span: SourceSpan) -> tuple[ProjectedRange, ...]:
        return tuple(p for run in self.runs if (p := project_run(run, span)) is not None)

    def edit(self, start: int, end: int, length: int) -> "EditMap":
        """Apply one replacement. Overlap with an earlier replacement stays coarse.

        A later edit cannot recover correspondence that an earlier edit discarded.
        The surviving envelope of such a run is retained, including deletion anchors.
        """
        if not 0 <= start <= end <= self.length or length < 0:
            raise ValueError("Edit is outside current output")
        delta = length - (end - start)
        runs = []
        insertion_anchor = None
        insertion_origin = None
        for run in self.runs:
            source = run.source
            if run.start <= start <= run.end:
                insertion_origin = source
            if run.kind == "copy" and run.start <= start <= run.end:
                point = source.start + start - run.start
                insertion_anchor = source.basis.span(point, point)
            if run.end <= start:
                runs.append(run)
            elif run.start >= end:
                runs.append(run.shifted(delta))
            elif run.kind == "copy":
                a, b = max(run.start, start), min(run.end, end)
                left = source.start + a - run.start
                right = source.start + b - run.start
                if run.start < a:
                    runs.append(MappingRun(source.basis.span(source.start, left), run.start, a))
                if a < b:
                    runs.append(MappingRun(source.basis.span(left, right), start, start + length, "replace"))
                if b < run.end:
                    runs.append(MappingRun(source.basis.span(right, source.end), b + delta, run.end + delta))
            else:
                runs.append(MappingRun(source, min(run.start, start),
                    max(start + length, run.end + delta), run.kind))
        if start == end and length:
            if insertion_anchor is not None:
                runs.append(MappingRun(insertion_anchor, start, start + length, "insert"))
            elif not any(r.start <= start and start + length <= r.end for r in runs):
                if insertion_origin is None:
                    raise ValueError("Insertion has no source anchor")
                # An insertion at a prior replacement/deletion has no precise
                # interior source point. Relate it to that extent as a whole.
                runs.append(MappingRun(insertion_origin, start, start + length,
                    "insert" if insertion_origin.start == insertion_origin.end else "replace"))
        return EditMap(self.length + delta, tuple(sorted(runs, key=lambda r: (r.start, r.end))))
