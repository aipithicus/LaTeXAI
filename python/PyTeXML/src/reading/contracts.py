"""Reading baselines, resolved effects, grammar metadata, and unresolved results."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol
from .character_rules import CatcodeLayer
from .spans import SourceSpan
from .tex_reader import CatcodeTable, Token


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
class ConditionalRule:
    """Nesting meaning is independent of whether its predicate can be evaluated."""
    role: str
    evaluation: str | None = None


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
    conditional: ConditionalRule | None = None


class ReadingKnowledge(Protocol):
    """Already loaded knowledge; package activation and loading stay outside."""
    def resolve_command(self, name: str) -> EffectiveReadingProfile | UnresolvedBindingResult: ...
    def resolve_environment(self, name: str, options: dict[str, Any] | None = None) -> EffectiveReadingProfile | UnresolvedBindingResult: ...
    def resolve_group(self, catcode: int) -> EffectiveReadingProfile | UnresolvedBindingResult: ...
    def resolve_conditional(self, name: str) -> ConditionalRule | None: ...


@dataclass(frozen=True, slots=True)
class EnvironmentDeclaration:
    """A scoped author declaration selecting existing reading machinery."""
    name: str
    base: str
    options: dict[str, Any]
    exact_terminator: str
    regex_terminator: str
    binding_id: str
    span: SourceSpan
    classification: SpanClassification | None = None


@dataclass(frozen=True, slots=True)
class ReadingBoundary:
    # Diagnostic anchor; at EOF this can identify an earlier unclosed group.
    span: SourceSpan
    # Source not covered by preceding emitted items; empty for an EOF diagnostic.
    remainder: SourceSpan
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class DeferredRegion:
    """Source captured for later interpretation, without executing its contents.

    Adjacent groups on an unknown command are a protective envelope, not a claim
    about its argument signature. Tokens are observations under the entry catcodes.
    """
    span: SourceSpan
    reason: str
    detail: str
    tokens: tuple[Token, ...] = ()


@dataclass(frozen=True, slots=True)
class LiteralRegion:
    span: SourceSpan
    opening: SourceSpan
    body: SourceSpan
    closing: SourceSpan
    name: str
    binding_id: str
    classification: SpanClassification | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkippedRegion:
    """Unexecuted source, excluding the separately emitted branch delimiters.

    Nested conditional tokens belong to this extent. ``conditional`` identifies
    the owning executed opener; it is provenance, not a contained subspan.
    Empty branches retain a zero-width record.
    """
    span: SourceSpan
    conditional: SourceSpan
    branch: str


@dataclass(frozen=True, slots=True)
class StoredDefinition:
    """A lexical capture, not an expanded or compiled replacement list.

    Tokens retain definition-time categories and source occurrences. In particular,
    doubled parameter markers remain two tokens. ``hash_brace`` records TeX's
    special parameter-ending marker plus opening brace; a later compiler must
    account for that brace in both the delimiter and replacement list.
    opening/body/closing partition span; parameter_text lies within opening.
    """
    span: SourceSpan
    opening: SourceSpan
    parameter_text: SourceSpan
    body: SourceSpan
    closing: SourceSpan
    target: Token
    parameter_tokens: tuple[Token, ...]
    body_tokens: tuple[Token, ...]
    parameter_count: int
    hash_brace: Token | None
    binding_id: str


@dataclass(frozen=True, slots=True)
class ScannedArgument:
    name: str
    span: SourceSpan
    tokens: tuple[Token, ...]

    def literal(self) -> str:
        from .tex_reader import TokenKind, CatCode
        if any(t.kind != TokenKind.CHARACTER or t.catcode not in
               (CatCode.LETTER, CatCode.OTHER, CatCode.SPACE, CatCode.SUBSCRIPT, CatCode.SUPERSCRIPT) for t in self.tokens):
            raise ReadingIssue("computed_argument", f"{self.name} requires interpretation")
        return "".join(t.value for t in self.tokens).strip()


@dataclass(frozen=True, slots=True)
class SourceCommand:
    """An established active command; the preparation owner resolves resources."""
    span: SourceSpan
    name: str
    action: str
    arguments: tuple[ScannedArgument, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def argument(self, name: str) -> ScannedArgument | None:
        return next((arg for arg in self.arguments if arg.name == name), None)

    def value(self, name: str, default: str = "") -> str:
        arg = self.argument(name)
        return arg.literal() if arg is not None else default


@dataclass(frozen=True, slots=True)
class SourceEnd:
    """Completion of an input occurrence, with any deliberately unread suffix."""
    span: SourceSpan
    reason: str = "eof"


class ReadingIssue(Exception):
    """A scanner cannot establish further reading; routing locates the boundary."""
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason, self.detail = reason, detail


def require_resolved(result: EffectiveReadingProfile | UnresolvedBindingResult) -> EffectiveReadingProfile:
    if isinstance(result, UnresolvedBindingResult):
        raise ReadingIssue(result.reason.value, result.detail)
    return result
