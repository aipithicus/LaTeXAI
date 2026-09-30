"""
Policy Engine and Configuration Loader for LaTeX Extractor.

Loads declarative YAML specifications from the `policy/` directory and exposes
structured, typed configurations to the preflight, pruner, inliner, and emitter pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Union
import yaml


POLICY_DIR = Path(__file__).resolve().parent / "policy"


@dataclass(frozen=True, slots=True)
class SpanActionConfig:
    category: str
    action: str
    strip_comments: bool = False
    normalize_whitespace: bool = False
    emit_tombstone: bool = False
    tombstone_category: str = "PRUNED_SPAN"
    destination_sidecar: Optional[str] = None
    preserve_in_source: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class LexicalCommentPolicy:
    full_line_action: str = "drop_line"
    full_line_emit_tombstone: bool = True
    full_line_tombstone_category: str = "STRIPPED_COMMENT"
    preserve_patterns: tuple[str, ...] = ()
    inline_action: str = "strip_payload_preserve_boundary"
    boundary_preservation: str = "preserve_trailing_space"
    line_continuation_action: str = "preserve_continuation_marker"
    magic_comments_action: str = "parse_metadata_then_drop"
    magic_directives: tuple[str, ...] = (
        "!TeX root", "!TEX root", "!TeX TS-program", "!TEX TS-program", "!TeX spellcheck"
    )

    def should_preserve_full_line(self, line_text: str) -> bool:
        """Evaluates whether a full-line comment should be preserved under filter patterns."""
        if self.full_line_action == "preserve_line":
            return True
        if self.full_line_action == "drop_line":
            return False
        if self.full_line_action == "filter_by_pattern":
            for pat in self.preserve_patterns:
                if re.search(pat, line_text, re.IGNORECASE):
                    return True
            return False
        return False


@dataclass(frozen=True, slots=True)
class WhitespacePolicy:
    max_consecutive_blank_lines: Optional[int] = 1
    strip_trailing_spaces: bool = True
    swallow_first_verbatim_newline: bool = True
    enforce_newline_at_eof: bool = True
    output_line_ending: str = "\n"


@dataclass(frozen=True, slots=True)
class MacroPruningPolicy:
    drop_commands: frozenset[str] = field(default_factory=frozenset)
    unwrap_commands: frozenset[str] = field(default_factory=frozenset)

    def should_drop(self, macro_name: str) -> bool:
        clean = macro_name.lstrip("\\")
        return clean in self.drop_commands

    def should_unwrap(self, macro_name: str) -> bool:
        clean = macro_name.lstrip("\\")
        return clean in self.unwrap_commands


@dataclass(frozen=True, slots=True)
class ConditionalPolicy:
    simplify_static_branches: bool = True
    unknown_conditionals: str = "preserve"


@dataclass(frozen=True, slots=True)
class ProvenancePolicy:
    emit_ledger: bool = True
    rle_compression: bool = True
    track_tombstones: bool = True


@dataclass(frozen=True, slots=True)
class ExtractionPolicy:
    name: str
    version: str
    target_pipeline: str
    description: str
    span_actions: Dict[str, SpanActionConfig]
    lexical_comments: LexicalCommentPolicy
    whitespace: WhitespacePolicy
    macro_pruning: MacroPruningPolicy
    conditionals: ConditionalPolicy
    provenance: ProvenancePolicy
    raw_config: Dict[str, Any] = field(default_factory=dict, repr=False)

    def get_span_action(self, category: str) -> SpanActionConfig:
        """Retrieves action configuration for a given span classification category."""
        if category in self.span_actions:
            return self.span_actions[category]
        # Default fallback: preserve immutable to protect unknown structures
        return SpanActionConfig(category=category, action="preserve_immutable")

    def should_drop_macro(self, macro_name: str) -> bool:
        return self.macro_pruning.should_drop(macro_name)

    def should_unwrap_macro(self, macro_name: str) -> bool:
        return self.macro_pruning.should_unwrap(macro_name)

    def should_preserve_full_line_comment(self, line_text: str) -> bool:
        return self.lexical_comments.should_preserve_full_line(line_text)


def load_policy(policy_identifier_or_path: Union[str, Path]) -> ExtractionPolicy:
    """
    Loads and validates an ExtractionPolicy from a named preset (e.g. 'compact', 'lossless')
    or from an explicit file path.
    """
    path = Path(policy_identifier_or_path)
    if not path.is_file():
        # Check standard policy directory
        candidate = POLICY_DIR / f"{policy_identifier_or_path}.yaml"
        if candidate.is_file():
            path = candidate
        elif str(policy_identifier_or_path) == "compact" and (POLICY_DIR / "preflight.yaml").is_file():
            path = POLICY_DIR / "preflight.yaml"
        else:
            raise FileNotFoundError(f"Policy not found: {policy_identifier_or_path} (searched {candidate})")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Invalid policy schema in {path}: root must be a mapping")

    ident = raw.get("identity", {})
    name = ident.get("name", path.stem)
    version = ident.get("version", "1.0.0")
    target_pipeline = ident.get("target_pipeline", "unknown")
    desc = ident.get("description", "")

    # 1. Span Actions
    span_actions: Dict[str, SpanActionConfig] = {}
    for cat, cfg in raw.get("span_actions", {}).items():
        if isinstance(cfg, dict):
            span_actions[cat] = SpanActionConfig(
                category=cat,
                action=cfg.get("action", "preserve_immutable"),
                strip_comments=cfg.get("strip_comments", False),
                normalize_whitespace=cfg.get("normalize_whitespace", False),
                emit_tombstone=cfg.get("emit_tombstone", False),
                tombstone_category=cfg.get("tombstone_category", "PRUNED_SPAN"),
                destination_sidecar=cfg.get("destination_sidecar"),
                preserve_in_source=cfg.get("preserve_in_source", False),
                description=cfg.get("description", ""),
            )

    # 2. Lexical Comments
    lex_cfg = raw.get("lexical_comments", {})
    fl_cfg = lex_cfg.get("full_line_comment", {})
    il_cfg = lex_cfg.get("inline_comment", {})
    lc_cfg = lex_cfg.get("line_continuation", {})
    mg_cfg = lex_cfg.get("magic_comments", {})

    lexical_comments = LexicalCommentPolicy(
        full_line_action=fl_cfg.get("action", "drop_line"),
        full_line_emit_tombstone=fl_cfg.get("emit_tombstone", True),
        full_line_tombstone_category=fl_cfg.get("tombstone_category", "STRIPPED_COMMENT"),
        preserve_patterns=tuple(fl_cfg.get("preserve_patterns", [])),
        inline_action=il_cfg.get("action", "strip_payload_preserve_boundary"),
        boundary_preservation=il_cfg.get("boundary_preservation", "preserve_trailing_space"),
        line_continuation_action=lc_cfg.get("action", "preserve_continuation_marker"),
        magic_comments_action=mg_cfg.get("action", "parse_metadata_then_drop"),
        magic_directives=tuple(mg_cfg.get("directives", [
            "!TeX root", "!TEX root", "!TeX TS-program", "!TEX TS-program", "!TeX spellcheck"
        ])),
    )

    # 3. Whitespace Rules
    ws_cfg = raw.get("whitespace_rules", {})
    whitespace = WhitespacePolicy(
        max_consecutive_blank_lines=ws_cfg.get("max_consecutive_blank_lines", 1),
        strip_trailing_spaces=ws_cfg.get("strip_trailing_spaces", True),
        swallow_first_verbatim_newline=ws_cfg.get("swallow_first_verbatim_newline", True),
        enforce_newline_at_eof=ws_cfg.get("enforce_newline_at_eof", True),
        output_line_ending=ws_cfg.get("output_line_ending", "\n"),
    )

    # 4. Macro Pruning
    mp_cfg = raw.get("macro_pruning", {})
    macro_pruning = MacroPruningPolicy(
        drop_commands=frozenset(c.lstrip("\\") for c in mp_cfg.get("drop_commands", [])),
        unwrap_commands=frozenset(c.lstrip("\\") for c in mp_cfg.get("unwrap_commands", [])),
    )

    # 5. Conditionals
    cond_cfg = raw.get("conditional_evaluation", {})
    conditionals = ConditionalPolicy(
        simplify_static_branches=cond_cfg.get("simplify_static_branches", True),
        unknown_conditionals=cond_cfg.get("unknown_conditionals", "preserve"),
    )

    # 6. Provenance
    prov_cfg = raw.get("provenance", {})
    provenance = ProvenancePolicy(
        emit_ledger=prov_cfg.get("emit_ledger", True),
        rle_compression=prov_cfg.get("rle_compression", True),
        track_tombstones=prov_cfg.get("track_tombstones", True),
    )

    return ExtractionPolicy(
        name=name,
        version=version,
        target_pipeline=target_pipeline,
        description=desc,
        span_actions=span_actions,
        lexical_comments=lexical_comments,
        whitespace=whitespace,
        macro_pruning=macro_pruning,
        conditionals=conditionals,
        provenance=provenance,
        raw_config=raw,
    )
