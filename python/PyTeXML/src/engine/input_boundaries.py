"""Return continuations known by the source owner, not guessed from EOF."""
from dataclasses import dataclass
from .primitive import PrimitiveMeaning
from ..reading.contracts import ReadingIssue
from ..reading.tex_reader import CatCode


@dataclass(frozen=True)
class InputReturn:
    name: str
    next_token_is_control_sequence: bool
    source_reference: str


LATEX_BRACED_INPUT = InputReturn("latex_braced_input", True,
    "LaTeX2e 2026-06-01 latex.ltx:19935-19964; file-return hook/context continuation")


def require_inert_barrier(context, knowledge):
    meaning = context.resolve_meaning(knowledge, "relax")
    lexical = (context.catcodes['\\'] == CatCode.ESCAPE and context.catcodes[' '] == CatCode.SPACE
               and all(context.catcodes[c] == CatCode.LETTER for c in 'relax'))
    if (not lexical or not isinstance(meaning, PrimitiveMeaning)
            or meaning.operation != "execution.relax" or meaning.uncertain is not None):
        raise ReadingIssue("input_return_barrier", "Inlining cannot establish an inert lookahead barrier")
