"""
Preparation policy configuration for PyTeXML.

Loads declarative role/event actions from resources/policies. Syntax validation
also permits experimental sketches; executable consumers validate capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Union
from ..yaml_io import load_mapping, validate_resource_identity


POLICY_DIR = Path(__file__).resolve().parents[2] / "resources" / "policies"


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
    paragraph_breaks: str = "preserve"
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
    source: str = "<policy>"

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
    Load the named 'prepare' preset or an explicit policy file.

    Experimental policies require an explicit path and are never searched as
    presets. A matching identity.name is required; omitted action/settings fields
    use the dataclass defaults and supplied fields are strict.
    """
    if isinstance(policy_identifier_or_path, str) and policy_identifier_or_path == "prepare":
        path = POLICY_DIR / "prepare.yaml"
    else:
        path = Path(policy_identifier_or_path)
    if not path.is_file():
        raise FileNotFoundError(f"Policy not found: {path}; use 'prepare' or an explicit file path")

    raw = load_mapping(path)
    _validate_policy(raw, path)

    name = validate_resource_identity(raw, path)
    ident = raw["identity"]
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
        paragraph_breaks=norm_cfg.get("paragraph_breaks", "preserve"),
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
        source=str(path),
    )


def _validate_policy(raw: Dict[str, Any], path: Path) -> None:
    """Validate current policy fields without defining future rewrite semantics."""
    allowed = {"identity", "role_actions", "lexical_events", "structural_normalization", "provenance"}
    def fail(message: str) -> None:
        raise ValueError(f"{path}: {message}")

    if set(raw) - allowed:
        fail(f"unknown policy sections: {list(set(raw) - allowed)!r}")
    for section in allowed:
        if not isinstance(raw.get(section, {}), dict):
            fail(f"{section} must be a mapping")
    identity = raw.get("identity", {})
    if set(identity) - {"name", "target", "description"}:
        fail("unknown identity fields")
    for key, value in identity.items():
        if not isinstance(value, str) or (key != "description" and not value):
            fail(f"identity.{key} must be a string" + ("" if key == "description" else " with a value"))
    for role, action in raw.get("role_actions", {}).items():
        if not isinstance(role, str) or not role:
            fail("role_actions keys must be nonempty role names")
        if not isinstance(action, str) or action not in {a.value for a in RoleAction}:
            fail(f"unknown action {action!r} for role {role!r}")
    choices = {
        "lexical_events": {
            "comment_line": {"eliminate", "preserve", "route_to_sidecar"},
            "comment_inline": {"strip_payload", "preserve"},
            "line_continuation": {"preserve", "eliminate"},
            "magic_directive": {"extract_metadata", "preserve", "eliminate"},
        },
        "structural_normalization": {
            "paragraph_breaks": {"coalesce", "preserve"},
            "trailing_whitespace": {"strip", "preserve"},
        },
    }
    for section, fields in choices.items():
        for key, value in raw.get(section, {}).items():
            if key not in fields or not isinstance(value, str) or value not in fields[key]:
                fail(f"invalid {section}.{key}: {value!r}")
    for key, value in raw.get("provenance", {}).items():
        if key not in {"emit_ledger", "rle_compression"} or type(value) is not bool:
            fail(f"provenance.{key} must be a known boolean field")
