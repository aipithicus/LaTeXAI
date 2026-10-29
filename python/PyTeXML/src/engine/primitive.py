"""Native primitive meanings and immutable operands, independent of bindings."""
from dataclasses import dataclass

from ..reading.spans import SourceSpan
from ..reading.tex_reader import Token


@dataclass(frozen=True, slots=True)
class PrimitiveMeaning[Operand = object]:
    operation: str
    operand: Operand
    span: SourceSpan | None = None
    uncertain: SourceSpan | None = None

    @property
    def identity(self):
        # Assignment locations and uncertainty evidence are not TeX meaning.
        return self.operation, self.operand


@dataclass(frozen=True, slots=True)
class AssignmentTarget:
    """Observed raw target only; no claim about an expansion-dependent RHS."""
    target: Token
