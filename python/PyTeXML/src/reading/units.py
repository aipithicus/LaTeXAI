"""Read-local identities, independent of filenames and emission segmentation."""
from dataclasses import dataclass

from .spans import SourceSpan


@dataclass(frozen=True, slots=True)
class ReadingUnit:
    id: str
    span: SourceSpan
    kind: str
    parent_id: str | None = None
    activity: str = "unresolved"

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "parent_id": self.parent_id, "activity": self.activity,
                "origin": {"source": self.span.basis.source_id, "occurrence": self.span.basis.occurrence_id,
                           "start": self.span.start, "end": self.span.end}}


class UnitRegistry:
    """One namespace per traversal; callers may share it across input readers.

    IDs deliberately do not claim stability across artifact revisions. Explicit
    parent links describe observations inside envelopes, not execution order.
    """
    def __init__(self):
        self.records: dict[str, ReadingUnit] = {}

    def add(self, span: SourceSpan, kind: str, parent_id: str | None = None, *, activity: str | None = None) -> str:
        if parent_id is not None and parent_id not in self.records:
            raise ValueError("Unknown parent unit")
        if activity is None:
            activity = self.records[parent_id].activity if parent_id else "unresolved"
        if activity not in {"reached", "skipped", "unresolved"}:
            raise ValueError("Unknown source activity")
        identifier = f"unit-{len(self.records) + 1}"
        self.records[identifier] = ReadingUnit(identifier, span, kind, parent_id, activity)
        return identifier

    def require(self, identifier: str, span: SourceSpan) -> None:
        if identifier not in self.records or self.records[identifier].span != span:
            raise ValueError("Unit does not identify this source span")
