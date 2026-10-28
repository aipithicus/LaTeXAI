"""Native primitive meanings and immutable operands, independent of bindings."""
from dataclasses import dataclass
from typing import Any

from ..reading.spans import SourceSpan


@dataclass(frozen=True, slots=True)
class DefinitionSpec:
    global_: bool = False
    expanded: bool = False


@dataclass(frozen=True, slots=True)
class PrimitiveMeaning:
    operation: str
    operand: Any = None
    span: SourceSpan | None = None
    uncertain: SourceSpan | None = None

    @property
    def identity(self):
        # Assignment locations and uncertainty evidence are not TeX meaning.
        return self.operation, self.operand


@dataclass(frozen=True, slots=True)
class AssignmentTarget:
    """Observed raw target only; no claim about an expansion-dependent RHS."""
    target: Any
