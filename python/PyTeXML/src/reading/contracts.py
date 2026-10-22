"""Reading baselines, resolved effects, grammar metadata, and unresolved results."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol
from .character_rules import CatcodeLayer
from .tex_reader import CatcodeTable, SourceSpan


@dataclass(frozen=True, slots=True)
class MouthBaseline:
    name: str
    default: int
    endlinechar: int
    layers: tuple[CatcodeLayer, ...]

    def new_catcodes(self) -> CatcodeTable:
        return CatcodeTable(default=self.default, layers=self.layers)


class UnresolvedReason(str, Enum):
    UNKNOWN_CONSTRUCT = "unknown_construct"
    PACKAGE_NOT_LOADED = "package_not_loaded"
    UNSUPPORTED_READING_OPTION = "unsupported_reading_option"
    ARGUMENTS_REQUIRED = "arguments_required"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    CONFLICTING_DEFINITIONS = "conflicting_definitions"


@dataclass(frozen=True, slots=True)
class UnresolvedBindingResult:
    occurrence_name: str
    reason: UnresolvedReason
    detail: str
    raw_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerminatorRule:
    exact_string: str
    regex_pattern: str
    matching_domain: str = "stream"
    requires_column_zero: bool = False
    trailing_content_allowed: bool = True
    trailing_line_behavior: str = "preserve_trailing_content"
    boundary_mode: str = "raw_delimiter"


@dataclass(frozen=True, slots=True)
class StateManagementRule:
    guard_variable: str | None = None
    repeated_call_behavior: str = "normal"
    saved_parameters: dict[str, list[str]] = field(default_factory=dict)
    restores_parameters: dict[str, list[str]] = field(default_factory=dict)
    exit_behavior: str = "normal"
    scope: str = "local"
    group_kind: str | None = None


@dataclass(frozen=True, slots=True)
class SpanClassification:
    category: str
    semantic_role: str


@dataclass(frozen=True, slots=True)
class InterpolationRule:
    """A delimiter pair consumed by a literal dispatcher, not a global catcode change."""
    opening: str
    closing: str
    mode: str = "tex"


@dataclass(frozen=True, slots=True)
class EffectiveReadingProfile:
    """Resolved data for one occurrence; applying it is not argument/body execution."""
    name: str
    family: str
    catcode_overrides: dict[str, int] = field(default_factory=dict)
    catcode_layers: tuple[CatcodeLayer, ...] = ()
    reader_parameters: dict[str, Any] = field(default_factory=dict)
    tex_mechanics: dict[str, Any] = field(default_factory=dict)
    terminator: TerminatorRule | None = None
    state_management: StateManagementRule | None = None
    span_classification: SpanClassification | None = None
    source_capture: dict[str, Any] = field(default_factory=dict)
    active_options: dict[str, Any] = field(default_factory=dict)
    grammar: dict[str, Any] = field(default_factory=dict)
    interpolations: tuple[InterpolationRule, ...] = ()
    action: str | None = None
    binding_id: str = ""


class ReadingKnowledge(Protocol):
    """Already loaded knowledge; package activation and loading stay outside."""
    def resolve_command(self, name: str) -> EffectiveReadingProfile | UnresolvedBindingResult: ...
    def resolve_environment(self, name: str) -> EffectiveReadingProfile | UnresolvedBindingResult: ...
    def resolve_group(self, catcode: int) -> EffectiveReadingProfile | UnresolvedBindingResult: ...


@dataclass(frozen=True, slots=True)
class ReadingBoundary:
    # Diagnostic anchor; at EOF this can identify an earlier unclosed group.
    span: SourceSpan
    # Source not covered by preceding emitted items; empty for an EOF diagnostic.
    remainder: SourceSpan
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class LiteralRegion:
    span: SourceSpan
    opening: SourceSpan
    body: SourceSpan
    closing: SourceSpan
    name: str
    binding_id: str


class ReadingIssue(Exception):
    """A scanner cannot establish further reading; routing locates the boundary."""
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason, self.detail = reason, detail


def require_resolved(result: EffectiveReadingProfile | UnresolvedBindingResult) -> EffectiveReadingProfile:
    if isinstance(result, UnresolvedBindingResult):
        raise ReadingIssue(result.reason.value, result.detail)
    return result
