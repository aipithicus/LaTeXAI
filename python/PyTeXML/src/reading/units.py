"""Read-local identities, independent of filenames and emission segmentation."""
from dataclasses import dataclass, field, replace

from .spans import SourceSpan


@dataclass(frozen=True, slots=True)
class ReadingUnit:
    id: str
    span: SourceSpan
    kind: str
    parent_id: str | None = None
    activity: str = "unresolved"
    activity_evidence: dict = field(default_factory=dict)

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "parent_id": self.parent_id, "activity": self.activity,
                "activity_evidence": dict(self.activity_evidence),
                "origin": {"source": self.span.basis.source_id, "occurrence": self.span.basis.occurrence_id,
                           "start": self.span.start, "end": self.span.end}}


class UnitRegistry:
    """One namespace per traversal; callers may share it across input readers.

    IDs deliberately do not claim stability across artifact revisions. Explicit
    parent links describe observations inside envelopes, not execution order.
    """
    def __init__(self):
        self.records: dict[str, ReadingUnit] = {}
        self.children: dict[str, list[str]] = {}

    def add(self, span: SourceSpan, kind: str, parent_id: str | None = None, *, activity: str | None = None,
            evidence: dict | None = None) -> str:
        if parent_id is not None and parent_id not in self.records:
            raise ValueError("Unknown parent unit")
        if activity is None:
            activity = self.records[parent_id].activity if parent_id else "unresolved"
        if activity not in {"reached", "skipped", "stored", "data", "unresolved"}:
            raise ValueError("Unknown source activity")
        evidence = dict(evidence or {"reason": "inherited_context" if parent_id else "unspecified_context"})
        if parent_id:
            evidence.setdefault("owner_unit_id", parent_id)
        for key in ("owner_unit_id", "decision_unit_id"):
            if evidence.get(key) is not None and evidence[key] not in self.records:
                raise ValueError("Unknown activity evidence unit")
        identifier = f"unit-{len(self.records) + 1}"
        self.records[identifier] = ReadingUnit(identifier, span, kind, parent_id, activity, evidence)
        if parent_id:
            self.children.setdefault(parent_id, []).append(identifier)
        return identifier

    def require(self, identifier: str, span: SourceSpan) -> None:
        if identifier not in self.records or self.records[identifier].span != span:
            raise ValueError("Unit does not identify this source span")

    def decide(self, identifier, activity, evidence):
        if activity not in {"reached", "skipped", "stored", "data", "unresolved"}:
            raise ValueError("Unknown source activity")
        for key in ("owner_unit_id", "decision_unit_id"):
            if evidence.get(key) is not None and evidence[key] not in self.records:
                raise ValueError("Unknown activity evidence unit")
        old = self.records[identifier]
        self.records[identifier] = replace(old, activity=activity,
            activity_evidence={**old.activity_evidence, **evidence})
