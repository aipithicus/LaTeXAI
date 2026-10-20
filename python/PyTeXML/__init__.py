"""
LaTeX-Extractor: Preflight discovery, inlining, pruning, Knuth normalization,
SVG asset conversion, provenance tracking, and replication package generator.
"""

from .preflight import (
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
from .pruner import (
    prune_latex,
    prune_latex_provenance,
    simplify_conditionals,
    strip_macro_with_args,
    strip_environment,
)
from .inliner import (
    inline_latex_tree,
    inline_latex_tree_provenance,
)
from .normalizer import (
    knuth_normalize,
    knuth_normalize_provenance,
)
from .converter import (
    pdf_to_svg,
    raster_to_svg_wrapper,
    convert_asset_to_svg,
    batch_convert_assets_to_svg,
    rewrite_tex_image_references,
    rewrite_lines_image_references,
)
from .provenance import (
    ProvenanceLedger,
    ProvenanceRun,
    SourceLine,
    Tombstone,
)
from .policy_loader import (
    ExtractionPolicy,
    RoleAction,
    EventAction,
    LexicalEventsPolicy,
    StructuralNormalizationPolicy,
    ProvenancePolicy,
    load_policy,
)
from .binding_resolver import (
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
from .pipeline import preprocess_paper
from .character_rules import CharacterRule, CatcodeLayer, ProfileError
from .mouth_profiles import MouthProfiles, MouthBaseline

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
