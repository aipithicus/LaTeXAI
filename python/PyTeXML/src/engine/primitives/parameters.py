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
from ...reading.assignment_scanner import AssignmentScanner
from ..transactions import atomic, assignment_global


def parameter_key(profile: PrimitiveMeaning[str]) -> str:
    return profile.operand


def integer_value(scanner, profile: PrimitiveMeaning[str]):
    if profile.operand == "endlinechar":
        return scanner.host.context.endlinechar
    return scanner.host.context.integer_parameters.read(parameter_key(profile))


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
                            integer_value, operand_type=str, capture=capture,
                            accepted_prefixes=frozenset({"global"}))

FAMILY = OperationFamily(
    operations=(ASSIGN,),
    primitives=(*(ASSIGN.declare(name, name) for name in ("widowpenalty", "clubpenalty", "escapechar", "newlinechar", "endlinechar", "globaldefs")),
                ASSIGN.declare("pdfoutput", "pdfoutput", extension=True)),
)
