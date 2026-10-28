"""Executable operation contract and explicit, immutable catalog assembly.

Execution and internal integer values are separate roles. Both use the reader's
live state; requesting a value never executes an assignment.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from .integers import IntegerScanner

from ..reading.context import ExecutionMode, ReaderContext
from ..reading.contracts import (ConditionalRegion, ConditionalRule, EffectiveReadingProfile, EnvironmentDefinition,
                                 ReadingIssue, ReadingKnowledge, SourceCommand, StoredDefinition)
from ..reading.spans import SourceSpan
from ..reading.tex_reader import ReadEvent, TexReader, Token
from ..reading.token_cursor import TokenCursor
from ..reading.units import UnitRegistry
from .primitive import PrimitiveMeaning


Identified = TypeVar("Identified", StoredDefinition, EnvironmentDefinition)
OperationResult = ReadEvent | SourceCommand | StoredDefinition | EnvironmentDefinition | ConditionalRegion
# Kernel operations still receive temporary reader profiles until their migration.
OperationMeaning = PrimitiveMeaning | EffectiveReadingProfile


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
class ExecutableOperation:
    identity: str
    handler: Callable[[OperationHost, ReadEvent, OperationMeaning], OperationResult] | None = None
    integer_value: Callable[[IntegerScanner, PrimitiveMeaning], int] | None = None
    unexpandable: bool = False
    expansion: Callable | None = None
    capture: Callable | None = None
    continuation: bool = False

    def execute(self, host: OperationHost, opening: ReadEvent,
                profile: OperationMeaning) -> OperationResult:
        """Execute after the opener was read, using the caller's live cursor."""
        if self.handler is None:
            raise ReadingIssue("expansion_required", "This operation requires an expansion consumer")
        if host.context.mode != ExecutionMode.ACTIVE_EXECUTION:
            raise ReadingIssue("inactive_context", "Operation requires active execution")
        if host.reader.catcodes is not host.context.catcodes or host.reader.endline_char != host.context.endlinechar:
            raise ReadingIssue("context_changed", "Operation requires a shared reader state")
        return self.handler(host, opening, profile)


def build_catalog(*families: Iterable[ExecutableOperation]) -> Mapping[str, ExecutableOperation]:
    operations = {}
    for family in families:
        for operation in family:
            if operation.identity in operations:
                raise ValueError(f"Duplicate operation identity: {operation.identity}")
            operations[operation.identity] = operation
    return MappingProxyType(operations)
