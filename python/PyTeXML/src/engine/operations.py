"""Executable operation contract and explicit, immutable catalog assembly.

Execution and internal integer values are separate roles. Both use the reader's
live state; requesting a value never executes an assignment.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from .expansion import ExpansionCursor
    from .integers import IntegerScanner

from ..reading.context import ExecutionMode, ReaderContext
from ..reading.contracts import (ConditionalRegion, ConditionalRule, EffectiveReadingProfile, EnvironmentDefinition,
                                 ReadingIssue, ReadingKnowledge, SourceCommand, StoredDefinition)
from ..reading.spans import SourceSpan
from ..reading.tex_reader import ReadEvent, TexReader, Token
from ..reading.token_cursor import TokenCursor
from ..reading.units import UnitRegistry
from .primitive import AssignmentTarget, PrimitiveMeaning


Identified = TypeVar("Identified", StoredDefinition, EnvironmentDefinition)
OperationResult = ReadEvent | SourceCommand | StoredDefinition | EnvironmentDefinition | ConditionalRegion
CaptureResult = SourceCommand | StoredDefinition | AssignmentTarget | None

type ExecutionHandler[M] = Callable[[OperationHost, ReadEvent, M], OperationResult]
type IntegerValueHandler[M] = Callable[[IntegerScanner, M], int]
type ExpansionHandler[M] = Callable[[ExpansionCursor, Token, M], Token | None]
type CaptureHandler[M] = Callable[[TexReader | TokenCursor, ReaderContext, Token, M], CaptureResult]


class ExpansionKind(Enum):
    UNEXPANDABLE = "unexpandable"
    EXPANDABLE = "expandable"
    # Temporary kernel bridges have no native primitive expansion classification.
    INTERNAL = "internal"


class OperationHost(Protocol):
    """Services supplied by the current execution, without a second state store."""
    reader: TexReader | TokenCursor
    context: ReaderContext
    knowledge: ReadingKnowledge
    units: UnitRegistry
    operations: Mapping[str, ExecutableOperation]
    preparation: bool

    def identify(self, item: Identified) -> Identified: ...
    def begin_group(self, kind: str, span: SourceSpan) -> None: ...
    def end_group(self, kind: str) -> None: ...
    def route_conditional(self, rule: ConditionalRule, span: SourceSpan, *, metadata=None) -> str | None: ...
    def capture_conditional(self, token: Token, rule: ConditionalRule, *, causes=()) -> ConditionalRegion: ...


@dataclass(frozen=True, slots=True)
class ExecutableOperation[Meaning]:
    identity: str
    expansion_kind: ExpansionKind
    handler: ExecutionHandler[Meaning] | None = None
    integer_value: IntegerValueHandler[Meaning] | None = None
    expansion: ExpansionHandler[Meaning] | None = None
    capture: CaptureHandler[Meaning] | None = None
    continuation: bool = False
    expansion_unavailable: bool = False

    def __post_init__(self):
        if not isinstance(self.identity, str) or not self.identity:
            raise ValueError("Operation requires a nonempty identity")
        if not isinstance(self.expansion_kind, ExpansionKind):
            raise ValueError(f"{self.identity}: explicit expansion classification required")
        for name in ("handler", "integer_value", "expansion", "capture"):
            callback = getattr(self, name)
            if callback is not None and not callable(callback):
                raise TypeError(f"{self.identity}: {name} must be callable")
        if type(self.continuation) is not bool or type(self.expansion_unavailable) is not bool:
            raise TypeError(f"{self.identity}: capability flags must be booleans")
        if self.expansion_kind == ExpansionKind.EXPANDABLE:
            if (self.expansion is None) != self.expansion_unavailable:
                raise ValueError(f"{self.identity}: expandable operation needs a callback or explicit unavailability")
            if self.integer_value is not None:
                raise ValueError(f"{self.identity}: expandable operation cannot supply an internal integer")
        else:
            if self.expansion is not None or self.expansion_unavailable:
                raise ValueError(f"{self.identity}: expansion capability conflicts with classification")
            if self.handler is None:
                raise ValueError(f"{self.identity}: execution handler required")
        if self.expansion_kind == ExpansionKind.INTERNAL and (
                self.integer_value is not None or self.capture is not None):
            raise ValueError(f"{self.identity}: kernel bridge cannot declare native capabilities")
        if self.continuation and self.handler is None:
            raise ValueError(f"{self.identity}: continuation requires an execution handler")

    @property
    def unexpandable(self) -> bool:
        return self.expansion_kind == ExpansionKind.UNEXPANDABLE

    def execute(self, host: OperationHost, opening: ReadEvent,
                profile: Meaning) -> OperationResult:
        """Execute after the opener was read, using the caller's live cursor."""
        if self.handler is None:
            raise ReadingIssue("expansion_required", "This operation requires an expansion consumer")
        if host.context.mode != ExecutionMode.ACTIVE_EXECUTION:
            raise ReadingIssue("inactive_context", "Operation requires active execution")
        if host.reader.catcodes is not host.context.catcodes or host.reader.endline_char != host.context.endlinechar:
            raise ReadingIssue("context_changed", "Operation requires a shared reader state")
        return self.handler(host, opening, profile)


@dataclass(frozen=True, slots=True)
class PrimitiveOperation[Operand](ExecutableOperation[PrimitiveMeaning[Operand]]):
    """A native operation owns the operand contract used by its declarations."""
    operand_type: type[Operand] = field(kw_only=True)

    def __post_init__(self):
        ExecutableOperation.__post_init__(self)
        if self.expansion_kind == ExpansionKind.INTERNAL:
            raise ValueError(f"{self.identity}: native operation needs a primitive classification")
        if not isinstance(self.operand_type, type):
            raise TypeError(f"{self.identity}: operand_type must be a concrete type")

    def declare(self, name: str, operand: Operand, *, extension: bool = False) -> PrimitiveDeclaration[Operand]:
        return PrimitiveDeclaration(name, self, operand, extension=extension)


@dataclass(frozen=True, slots=True)
class PrimitiveDeclaration[Operand]:
    name: str
    operation: PrimitiveOperation[Operand]
    operand: Operand
    extension: bool = False

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or self.name.startswith("\\"):
            raise ValueError("Primitive declaration requires a name without the escape character")
        if not isinstance(self.operation, PrimitiveOperation):
            raise TypeError(f"{self.name}: declaration requires a native operation")
        if not isinstance(self.operand, self.operation.operand_type):
            raise TypeError(f"{self.name}: expected {self.operation.operand_type.__name__} operand")
        # Meaning operands are immutable keys, independent of handler identity.
        try:
            hash(self.operand)
        except TypeError as error:
            raise TypeError(f"{self.name}: operand must be immutable and hashable") from error
        if type(self.extension) is not bool:
            raise TypeError(f"{self.name}: extension flag must be boolean")

    def meaning(self) -> PrimitiveMeaning[Operand]:
        return PrimitiveMeaning(self.operation.identity, self.operand)


@dataclass(frozen=True, slots=True)
class OperationFamily:
    operations: tuple[ExecutableOperation, ...]
    primitives: tuple[PrimitiveDeclaration, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationCatalog:
    operations: Mapping[str, ExecutableOperation]
    common_primitives: Mapping[str, PrimitiveMeaning]
    extensions: Mapping[str, PrimitiveMeaning]


def build_catalog(*families: OperationFamily) -> OperationCatalog:
    operations = {}
    for family in families:
        for operation in family.operations:
            if operation.identity in operations:
                raise ValueError(f"Duplicate operation identity: {operation.identity}")
            operations[operation.identity] = operation
    common: dict[str, PrimitiveMeaning] = {}
    extensions: dict[str, PrimitiveMeaning] = {}
    for family in families:
        for declaration in family.primitives:
            if operations.get(declaration.operation.identity) is not declaration.operation:
                raise ValueError(f"Dangling operation reference: {declaration.name}")
            if declaration.name in common or declaration.name in extensions:
                raise ValueError(f"Conflicting primitive declaration: {declaration.name}")
            target = extensions if declaration.extension else common
            target[declaration.name] = declaration.meaning()
    return OperationCatalog(MappingProxyType(operations), MappingProxyType(common), MappingProxyType(extensions))
