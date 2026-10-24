"""Preparation inventory and output manifest records."""
from __future__ import annotations
import dataclasses
from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional
from ..assets import ImageAssetInfo


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

    # Canonical package entrypoint; root_file above records source discovery.
    entrypoint: Optional[str] = None
    preparation_status: str = "pending"  # pending, complete, partial, failed
    dependency_closure: str = "unresolved"
    source_dependency_closure: str = "unresolved"
    requirements: List[Dict[str, Any]] = field(default_factory=list)
    units: List[Dict[str, Any]] = field(default_factory=list)
    prepared_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    location_contract: Dict[str, Any] = field(default_factory=dict)
    source_survey: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    reading_assumptions: List[str] = field(default_factory=list)
    input_occurrences: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: List[Dict[str, Any]] = field(default_factory=list)
    candidate_dependencies: List[Dict[str, Any]] = field(default_factory=list)
    unresolved: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    preserved_source_spans: List[Dict[str, Any]] = field(default_factory=list)
    unclassified_files: List[str] = field(default_factory=list)
    source_reads: List[str] = field(default_factory=list)

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

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
