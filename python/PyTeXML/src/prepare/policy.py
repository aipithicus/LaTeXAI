"""
Policy Engine and Configuration Loader for LaTeX Extractor.

Loads declarative, role-based YAML specifications from the `policy/` directory
and exposes structured, typed configurations to the preflight, pruner, inliner,
and emitter pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union
import yaml




POLICY_DIR = Path(__file__).resolve().parents[2] / "policy"


class RoleAction(str, Enum):
    ELIMINATE = "eliminate"
    PRESERVE = "preserve"
    ROUTE_TO_SIDECAR = "route_to_sidecar"
    UNWRAP = "unwrap"
    INLINE = "inline"
    CONVERT_TO_MARKDOWN = "convert_to_markdown"


class EventAction(str, Enum):
    ELIMINATE = "eliminate"
    PRESERVE = "preserve"
    STRIP_PAYLOAD = "strip_payload"
    EXTRACT_METADATA = "extract_metadata"
    ROUTE_TO_SIDECAR = "route_to_sidecar"


@dataclass(frozen=True, slots=True)
class LexicalEventsPolicy:
    comment_line: str = "eliminate"
    comment_inline: str = "strip_payload"
    line_continuation: str = "preserve"
    magic_directive: str = "extract_metadata"


@dataclass(frozen=True, slots=True)
class StructuralNormalizationPolicy:
    paragraph_breaks: str = "coalesce"
    trailing_whitespace: str = "strip"


@dataclass(frozen=True, slots=True)
class ProvenancePolicy:
    emit_ledger: bool = True
    rle_compression: bool = True


@dataclass(frozen=True, slots=True)
class ExtractionPolicy:
    name: str
    target: str
    description: str
    role_actions: Dict[str, str]
    lexical_events: LexicalEventsPolicy
    normalization: StructuralNormalizationPolicy
    provenance: ProvenancePolicy
    raw_config: Dict[str, Any] = field(default_factory=dict, repr=False)

    def get_role_action(self, role: str) -> str:
        """Returns the configured action for a semantic role, defaulting to 'preserve'."""
        return self.role_actions.get(role, RoleAction.PRESERVE.value)

    def should_eliminate_role(self, role: str) -> bool:
        return self.get_role_action(role) == RoleAction.ELIMINATE.value

    def should_unwrap_role(self, role: str) -> bool:
        return self.get_role_action(role) == RoleAction.UNWRAP.value

    def should_eliminate_comment_line(self) -> bool:
        return self.lexical_events.comment_line == EventAction.ELIMINATE.value

    def should_strip_comment_inline(self) -> bool:
        return self.lexical_events.comment_inline == EventAction.STRIP_PAYLOAD.value

    def should_preserve_line_continuation(self) -> bool:
        return self.lexical_events.line_continuation == EventAction.PRESERVE.value

    def should_coalesce_paragraphs(self) -> bool:
        return self.normalization.paragraph_breaks == "coalesce"

    def should_strip_trailing_whitespace(self) -> bool:
        return self.normalization.trailing_whitespace == "strip"


def load_policy(policy_identifier_or_path: Union[str, Path]) -> ExtractionPolicy:
    """
    Loads and validates an ExtractionPolicy from a named preset (e.g. 'preflight', 'lossless')
    or from an explicit file path.
    """
    path = Path(policy_identifier_or_path)
    if not path.is_file():
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
    target = ident.get("target", "unknown")
    desc = ident.get("description", "")

    # 1. Role Actions
    role_actions: Dict[str, str] = dict(raw.get("role_actions", {}))

    # 2. Lexical Events
    lex_cfg = raw.get("lexical_events", {})
    lexical_events = LexicalEventsPolicy(
        comment_line=lex_cfg.get("comment_line", "eliminate"),
        comment_inline=lex_cfg.get("comment_inline", "strip_payload"),
        line_continuation=lex_cfg.get("line_continuation", "preserve"),
        magic_directive=lex_cfg.get("magic_directive", "extract_metadata"),
    )

    # 3. Structural Normalization
    norm_cfg = raw.get("structural_normalization", {})
    normalization = StructuralNormalizationPolicy(
        paragraph_breaks=norm_cfg.get("paragraph_breaks", "coalesce"),
        trailing_whitespace=norm_cfg.get("trailing_whitespace", "strip"),
    )

    # 4. Provenance
    prov_cfg = raw.get("provenance", {})
    provenance = ProvenancePolicy(
        emit_ledger=prov_cfg.get("emit_ledger", True),
        rle_compression=prov_cfg.get("rle_compression", True),
    )

    return ExtractionPolicy(
        name=name,
        target=target,
        description=desc,
        role_actions=role_actions,
        lexical_events=lexical_events,
        normalization=normalization,
        provenance=provenance,
        raw_config=raw,
    )
