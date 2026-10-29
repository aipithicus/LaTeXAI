"""Preparation inventory and output manifest records."""
from __future__ import annotations
import dataclasses
from dataclasses import dataclass, field
import json
from collections.abc import Callable, Iterable, Iterator
from itertools import chain
from typing import Any, Dict, List, Optional
from ..assets import ImageAssetInfo
from ..reading.spans import SourceSpan
from ..reading.units import ReadingUnit
from .records import (LocationRecord, RequirementRecord, WorkRecord,
                      assign_locations, pending_location, work_record)


@dataclass
class BibliographyInfo:
    kind: str  # "CLASSIC_BIBTEX", "BIBLATEX", "EMBEDDED", "NONE"
    backend: Optional[str]  # "bibtex", "biber", or None
    bbl_path: Optional[str]
    bbl_exists: bool
    bbl_needed: bool
    bib_files: List[str] = field(default_factory=list)
    missing_bib_files: List[str] = field(default_factory=list)
    citations_count: int = 0
    prepared_bbl: Optional[str] = None
    canonical_bib: Optional[str] = None
    preparation_backend: Optional[str] = None
    preparation_warnings: List[str] = field(default_factory=list)
    # Completeness of source-visible key observation, not macro expansion or
    # package execution. Pending activation never requests every database entry.
    citation_discovery: str = "not_run"
    citation_discovery_scope: str = "source_visible_no_expansion"
    citation_keys: List[str] = field(default_factory=list)
    citation_gaps: List[Dict[str, Any]] = field(default_factory=list)
    # Locations already live in requirements; do not duplicate every opaque
    # expression as a second full diagnostic merely because it might cite.
    citation_deferred_contexts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class StyleFileInfo:
    rel_path: str
    abs_path: str
    is_active: bool
    size_bytes: int
    declared_commands: List[str] = field(default_factory=list)
    declared_environments: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class PackageUsage:
    name: str
    options: List[str] = field(default_factory=list)
    is_local: bool = False
    local_path: Optional[str] = None
    unit_id: Optional[str] = None
    activity: str = "reached"
    binding_available: bool = False
    binding_activated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ImplicitGraphicInfo:
    kind: str  # "assetless_float", "morphism_grid", "tikzcd", "amscd", "xymatrix", "tikzpicture", "picture", etc.
    category: str  # "ASSETLESS_FLOAT", "COMMUTATIVE_DIAGRAM", "PROGRAMMATIC_DRAWING", "SPECIALIZED_CANVAS"
    file: str  # relative path of .tex file
    line_number: int  # 1-indexed
    is_floating: bool
    is_math_mode: bool
    preview: str
    environment_name: Optional[str] = None
    package_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class PreflightManifest:
    root_file: str
    base_name: str
    project_dir: str
    engine: str

    # Bibliography
    bibliography: BibliographyInfo
    engine_profile: Dict[str, Any] = field(default_factory=dict)

    # Canonical package entrypoint; root_file above records source discovery.
    entrypoint: Optional[str] = None
    preparation_status: str = "pending"  # pending, complete, partial, failed
    materialization_status: str = "pending"  # pending, complete, partial, failed; original resources
    activity_scope: str = "source_visible_under_reading_assumptions"
    dependency_closure: str = "unresolved"
    source_dependency_closure: str = "unresolved"
    requirements: list[RequirementRecord] = field(default_factory=list)
    units: List[Dict[str, Any]] = field(default_factory=list)
    uncertainty_causes: List[Dict[str, Any]] = field(default_factory=list)
    conditional_decisions: List[Dict[str, Any]] = field(default_factory=list)
    remaining_work: Dict[str, int] = field(default_factory=dict)
    prepared_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    location_contract: Dict[str, Any] = field(default_factory=dict)
    source_survey: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    recovery_contexts: List[Dict[str, Any]] = field(default_factory=list)
    recovery_status: str = "not_needed"
    original_resource_status: str = "unresolved"
    acceptance_status: str = "pending"
    source_metadata: List[Dict[str, Any]] = field(default_factory=list)
    reading_assumptions: List[str] = field(default_factory=list)
    input_occurrences: List[Dict[str, Any]] = field(default_factory=list)
    file_events: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: List[Dict[str, Any]] = field(default_factory=list)
    candidate_dependencies: List[Dict[str, Any]] = field(default_factory=list)
    unresolved: list[WorkRecord] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    preserved_source_spans: List[Dict[str, Any]] = field(default_factory=list)
    unclassified_files: List[str] = field(default_factory=list)
    source_reads: List[str] = field(default_factory=list)
    lint: Dict[str, Any] = field(default_factory=dict)

    # Assets
    active_images: List[ImageAssetInfo] = field(default_factory=list)
    candidate_images: List[ImageAssetInfo] = field(default_factory=list)
    dormant_images: List[str] = field(default_factory=list)

    # TeX and Code Source Topology
    active_tex_files: List[str] = field(default_factory=list)
    candidate_tex_files: List[str] = field(default_factory=list)
    dormant_tex_files: List[str] = field(default_factory=list)

    # Package & Style Architecture
    packages_declared: List[PackageUsage] = field(default_factory=list)
    local_styles: List[StyleFileInfo] = field(default_factory=list)
    dormant_styles: List[str] = field(default_factory=list)
    code_inputs: List[str] = field(default_factory=list)

    # Implicit / Programmatic Graphics
    implicit_graphics: List[ImplicitGraphicInfo] = field(default_factory=list)
    implicit_graphics_count: int = 0
    has_implicit_graphics: bool = False
    has_commutative_diagrams: bool = False

    # Environment flags
    has_tikz: bool = False
    has_tikz_external: bool = False
    has_minted: bool = False
    has_listings: bool = False

    def add_diagnostic(self, unit: ReadingUnit, line: int, reason: str, detail: str,
                       *, dependency="none", materialization=None) -> WorkRecord:
        record = work_record(unit, line, reason, detail, "preparation",
                             dependency=dependency, materialization=materialization)
        self.unresolved.append(record)
        return record

    def add_requirement(self, unit: ReadingUnit, line: int, reason: str, detail: str,
                        *, stage="interpretation", dependency=None, materialization=None,
                        next_step=None) -> RequirementRecord:
        record: RequirementRecord = {"id": f"requirement-{len(self.requirements) + 1}", "stage": stage,
            **work_record(unit, line, reason, detail, stage,
                dependency=dependency or ("required" if materialization == "pending" else "none"),
                materialization=materialization, next_step=next_step)}
        self.requirements.append(record)
        return record

    def _unit_records(self) -> Iterator[dict]:
        """All records whose prepared address comes from an explicit unit link."""
        yield from chain(self.requirements, self.unresolved, self.dependencies,
                         self.candidate_dependencies, self.resources, self.source_metadata, self.uncertainty_causes,
                         self.recovery_contexts)
        for finding in self.lint.get("findings", []):
            yield finding
            yield from finding["evidence"].get("related", [])

    def reset_locations(self, units: Iterable[ReadingUnit] | None = None) -> None:
        """Return to unlocated inventory without losing identities or source evidence."""
        self.prepared_artifacts = []
        self.location_contract = {}
        if units is not None:
            self.units = [{**unit.to_dict(), **pending_location()} for unit in units]
        for record in chain(self.units, self._unit_records(), self.warnings):
            # Some inventory records acquire location fields only at finalization.
            if "locations" in record:
                record.update(pending_location())

    def finalize_locations(self, units: Iterable[ReadingUnit],
                           project: Callable[[SourceSpan], LocationRecord], artifacts: Iterable[dict]) -> None:
        """Attach staged addresses; publication failure invalidates them together."""
        records = {unit.id: {**unit.to_dict(), **project(unit.span)} for unit in units}
        self.units = list(records.values())
        for target in self._unit_records():
            assign_locations(target, records[target["unit_id"]])
        self.prepared_artifacts = list(artifacts)
        self.location_contract = {"version": 1, "coordinate_domain": "decoded_unicode_codepoints",
            "intervals": "zero_based_half_open", "encoding": "utf-8", "newline_translation": "none",
            "id_scope": "preparation_run"}

    def mark_failed(self) -> None:
        """Failure diagnostics must not advertise unpublished artifact addresses."""
        self.reset_locations()
        self.entrypoint = None
        self.preparation_status = "failed"
        self.materialization_status = "failed"
        self.dependency_closure = "unresolved"
        for finding in self.lint.get("findings", []):
            if finding["repair"]["status"] in {"applied", "applied_in_memory"}:
                finding["repair"]["status"] = "not_published"

    def record_asset_payloads(self, mapping: dict[str, str]) -> None:
        """Materialization completes a file request, not its deferred interpretation."""
        for candidate in self.candidate_dependencies:
            if candidate.get("unit_id") in mapping:
                candidate.update(payload=mapping[candidate["unit_id"]], status="prepared")
        prepared = {c["unit_id"] for c in self.candidate_dependencies if c["status"] == "prepared"}
        for requirement in self.requirements:
            if requirement["reason"] == "observed_asset" and requirement["unit_id"] in prepared:
                requirement.update(materialization="prepared", next_step="interpretation")

    def refresh_status(self):
        """Keep payload delivery, reading completion and full semantics distinct."""
        pending_payload = any(r.get("materialization") == "pending"
                              for r in (*self.requirements, *self.unresolved))
        unavailable = any(r.get("materialization") == "unavailable" for r in self.requirements)
        self.materialization_status = "partial" if unavailable else "pending" if pending_payload else "complete"
        pending_preparation = bool(self.unresolved) or pending_payload or any(
            r["stage"] == "preparation" or (r.get("dependency") == "possible" and r.get("activity") != "stored")
            for r in self.requirements)
        self.source_dependency_closure = "unresolved" if pending_preparation else "complete"
        self.dependency_closure = "unresolved" if self.unresolved or self.requirements else "complete"
        self.preparation_status = "partial" if pending_preparation else "complete"
        failures = [r for r in self.dependencies if r.get("recovery", {}).get("disposition") == "tombstone"]
        self.original_resource_status = ("unsatisfied" if any(r["recovery"]["original_resource"] == "unsatisfied" for r in failures) else
            "unresolved" if failures else
            "unresolved" if pending_preparation else "satisfied")
        self.recovery_status = ("partial" if any(r["recovery"].get("emission") != "placed" for r in failures)
                               else "complete" if failures else "not_needed")
        if self.acceptance_status != "rejected":
            self.acceptance_status = "recovered" if failures else "accepted"
        from collections import Counter
        self.remaining_work = dict(Counter(r.get("next_step", "unclassified") for r in (*self.requirements, *self.unresolved)))

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
