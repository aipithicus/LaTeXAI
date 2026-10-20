"""
LaTeX-Extractor: Preflight discovery, inlining, pruning, Knuth normalization,
SVG asset conversion, provenance tracking, and replication package generator.
"""

from .src.preflight import (
    preflight_inventory,
    find_root_tex,
    check_toolchain,
    detect_implicit_graphics,
    PreflightManifest,
    ImageAssetInfo,
    ImplicitGraphicInfo,
    BibliographyInfo,
    StyleFileInfo,
    PackageUsage,
    ToolchainInfo,
)
from .src.pruner import (
    prune_latex,
    prune_latex_provenance,
    simplify_conditionals,
    strip_macro_with_args,
    strip_environment,
)
from .src.inliner import (
    inline_latex_tree,
    inline_latex_tree_provenance,
)
from .src.normalizer import (
    knuth_normalize,
    knuth_normalize_provenance,
)
from .src.converter import (
    pdf_to_svg,
    raster_to_svg_wrapper,
    convert_asset_to_svg,
    batch_convert_assets_to_svg,
    rewrite_tex_image_references,
    rewrite_lines_image_references,
)
from .src.provenance import (
    ProvenanceLedger,
    ProvenanceRun,
    SourceLine,
    Tombstone,
)
from .src.policy_loader import (
    ExtractionPolicy,
    RoleAction,
    EventAction,
    LexicalEventsPolicy,
    StructuralNormalizationPolicy,
    ProvenancePolicy,
    load_policy,
)
from .src.binding_resolver import (
    BindingResolver,
    ReaderContext,
    ExecutionMode,
    EffectiveReadingProfile,
    UnresolvedBindingResult,
    UnresolvedReason,
    TerminatorRule,
    StateManagementRule,
    SpanClassification,
    InterpolationRule,
)
from .src.pipeline import preprocess_paper
from .src.character_rules import CharacterRule, CatcodeLayer, ProfileError
from .src.mouth_profiles import MouthProfiles, MouthBaseline

__all__ = [
    "preflight_inventory",
    "find_root_tex",
    "check_toolchain",
    "detect_implicit_graphics",
    "PreflightManifest",
    "ImageAssetInfo",
    "ImplicitGraphicInfo",
    "BibliographyInfo",
    "StyleFileInfo",
    "PackageUsage",
    "ToolchainInfo",
    "prune_latex",
    "prune_latex_provenance",
    "simplify_conditionals",
    "strip_macro_with_args",
    "strip_environment",
    "inline_latex_tree",
    "inline_latex_tree_provenance",
    "knuth_normalize",
    "knuth_normalize_provenance",
    "pdf_to_svg",
    "raster_to_svg_wrapper",
    "convert_asset_to_svg",
    "batch_convert_assets_to_svg",
    "rewrite_tex_image_references",
    "rewrite_lines_image_references",
    "ProvenanceLedger",
    "ProvenanceRun",
    "SourceLine",
    "Tombstone",
    "ExtractionPolicy",
    "RoleAction",
    "EventAction",
    "LexicalEventsPolicy",
    "StructuralNormalizationPolicy",
    "ProvenancePolicy",
    "load_policy",
    "BindingResolver",
    "ReaderContext",
    "ExecutionMode",
    "EffectiveReadingProfile",
    "UnresolvedBindingResult",
    "UnresolvedReason",
    "TerminatorRule",
    "StateManagementRule",
    "SpanClassification",
    "InterpolationRule",
    "preprocess_paper",
    "CharacterRule",
    "CatcodeLayer",
    "ProfileError",
    "MouthProfiles",
    "MouthBaseline",
]
