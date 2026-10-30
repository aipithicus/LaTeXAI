"""Integer parameters: optional expanded equals, expanded integer, local write.

The internal-value role reads the same cell without assigning it. The operation
returns an authored source command; preparation preserves it for later layout or
backend execution. Output mode is not selected by this evaluator.

References: TeX82 tex.web and pdftexdir/pdftex.web, assign_int/word_define.
"""
from ...reading.contracts import ReadingIssue, SourceCommand
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ..quantities import InternalQuantity
from ...reading.assignment_scanner import AssignmentScanner
from ..transactions import atomic, assignment_global


def parameter_key(profile: PrimitiveMeaning[str]) -> str:
    return profile.operand


def internal_value(scanner, profile: PrimitiveMeaning[str]):
    if profile.operand == "endlinechar":
        return InternalQuantity("integer", scanner.host.context.endlinechar)
    key = parameter_key(profile)
    if (scanner.host.context.primitive_initial_state and key not in CLOCK_PARAMETERS
            and key not in scanner.host.context.integer_parameters.values):
        return InternalQuantity("integer", INITIAL.get(key, 0))
    return InternalQuantity("integer", scanner.host.context.integer_parameters.read(key))


@atomic
def assign_integer(host, opening, profile: PrimitiveMeaning[str]):
    key = parameter_key(profile)
    scanner = IntegerScanner(host)
    with host.context.argument_scanning():
        scanner.optional_equals()
        value = scanner.integer()
        scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    global_ = assignment_global(host)
    host.context.integer_parameters.assign(key, value, span, global_=global_)
    if key == "endlinechar":
        host.context.assign_endlinechar(value, global_=global_)
        host.reader.endline_char = value
    return SourceCommand(span, ("\\" + opening.token.value), "integer_parameter_assignment",
                         metadata={"parameter": key, "value": value,
                                   "trailing_control_word": scanner.ends_control_word,
                                   "source_reference": "TeX assign_int / word_define"})


def capture(reader, context, token, meaning: PrimitiveMeaning[str]):
    value = AssignmentScanner(reader, context).literal_integer_assignment()
    return SourceCommand(reader.source_span(token.span.start, reader.position), token.value,
                         "integer_parameter_assignment", metadata={"parameter": meaning.operand, "value": value})


ASSIGN = PrimitiveOperation("parameter.assign_integer", ExpansionKind.UNEXPANDABLE, assign_integer,
                            internal_value, operand_type=str, capture=capture,
                            accepted_prefixes=frozenset({"global"}))

INITIAL = {"mag": 1000, "tolerance": 10000, "hangafter": 1, "maxdeadcycles": 25,
           "defaulthyphenchar": 45, "defaultskewchar": -1}
CLOCK_PARAMETERS = frozenset({"time", "day", "month", "year"})
INTEGERS = "pretolerance tolerance linepenalty hyphenpenalty exhyphenpenalty clubpenalty widowpenalty displaywidowpenalty brokenpenalty binoppenalty relpenalty predisplaypenalty postdisplaypenalty interlinepenalty doublehyphendemerits finalhyphendemerits adjdemerits mag delimiterfactor looseness time day month year showboxbreadth showboxdepth hbadness vbadness pausing tracingonline tracingmacros tracingstats tracingparagraphs tracingpages tracingoutput tracinglostchars tracingcommands tracingrestores uchyph outputpenalty maxdeadcycles hangafter floatingpenalty globaldefs fam escapechar defaulthyphenchar defaultskewchar endlinechar newlinechar language lefthyphenmin righthyphenmin holdinginserts errorcontextlines".split()

FAMILY = OperationFamily(
    operations=(ASSIGN,),
    primitives=(*(ASSIGN.declare(name, name) for name in INTEGERS),
                ASSIGN.declare("pdfoutput", "pdfoutput", extension=True)),
)
