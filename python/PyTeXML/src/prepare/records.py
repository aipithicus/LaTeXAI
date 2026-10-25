"""Shared manifest record shapes; reader units remain the identity authority.

These are JSON-facing dictionaries, not a second set of runtime domain objects.
Builders derive source coordinates from a ReadingUnit so the identity and span
cannot disagree. Preparation-specific fields stay with their semantic producer.
"""
from typing import Any, TypedDict

from ..reading.units import ReadingUnit


class SourceReference(TypedDict):
    unit_id: str
    source: str
    occurrence: int
    start: int
    end: int


class ArtifactLocation(TypedDict):
    artifact: str
    start: int
    end: int
    precision: str


class LocationRecord(TypedDict):
    location_status: str
    locations: list[ArtifactLocation]


class WorkClassification(TypedDict):
    dependency: str
    materialization: str
    next_step: str


class WorkRecord(SourceReference, LocationRecord, WorkClassification):
    line: int
    reason: str
    detail: str
    activity: str
    activity_evidence: dict[str, Any]


class RequirementRecord(WorkRecord):
    id: str
    stage: str


def source_reference(unit: ReadingUnit) -> SourceReference:
    span = unit.span
    return {"unit_id": unit.id, "source": span.basis.source_id,
            "occurrence": span.basis.occurrence_id, "start": span.start, "end": span.end}


def pending_location() -> LocationRecord:
    return {"location_status": "pending", "locations": []}


def assign_locations(record: dict, location: LocationRecord) -> None:
    """Records own their mutable address lists, even when they refer to one unit."""
    record.update(location_status=location["location_status"],
                  locations=[dict(address) for address in location["locations"]])


def work_record(unit: ReadingUnit, line: int, reason: str, detail: str, stage: str,
                *, dependency="none", materialization=None, next_step=None) -> WorkRecord:
    return {**source_reference(unit), "line": line, "reason": reason, "detail": detail,
            "activity": unit.activity, "activity_evidence": dict(unit.activity_evidence),
            **work_classification(stage, dependency=dependency,
                materialization=materialization, next_step=next_step), **pending_location()}


def work_classification(stage, *, dependency="none", materialization=None, next_step=None) -> WorkClassification:
    if dependency not in {"none", "possible", "required"}:
        raise ValueError("Unknown dependency certainty")
    if materialization is None:
        materialization = {"none": "not_required", "possible": "undetermined", "required": "pending"}[dependency]
    if materialization not in {"not_required", "undetermined", "pending", "prepared"}:
        raise ValueError("Unknown materialization state")
    if dependency == "possible" and materialization == "pending":
        raise ValueError("A possible dependency is not an established payload request")
    if next_step is None:
        next_step = ("binding_knowledge" if stage == "binding" else
            "dependency_context" if dependency == "possible" else
            "resource_resolution" if materialization == "pending" else
            "reading_resolution" if stage == "preparation" else "interpretation")
    return {"dependency": dependency, "materialization": materialization, "next_step": next_step}
