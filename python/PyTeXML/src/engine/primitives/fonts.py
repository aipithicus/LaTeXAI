"""Font-dimension array access through established font identities (TeX82)."""
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..quantities import InternalQuantity
from ..transactions import atomic
from .registers import dimension
from ...reading.contracts import ReadingIssue, SourceCommand


def font_value(scanner, meaning):
    scanner.host.context.fonts.parameters(meaning.operand)
    return InternalQuantity("font", meaning.operand)


def select(host, opening, meaning):
    # Selection belongs to the later list-building stage; the identifier can
    # already be consumed by fontdimen without executing a selection.
    raise ReadingIssue("font_selection", "Font selection requires the list-building state")


def font_identifier(scanner):
    token = scanner._nonspace()
    if token is None:
        raise ReadingIssue("font_identifier", "Expected an established font identifier")
    quantity = scanner.internal(token)
    if quantity.kind != "font":
        raise ReadingIssue("font_identifier", "Expected an established font identifier")
    return quantity.value


def address(scanner, *, writing=False):
    index = scanner.integer()
    identity = font_identifier(scanner)
    values = scanner.host.context.fonts.cell(identity, index, writing=writing)
    return identity, index, values


def value(scanner, meaning):
    identity, index, values = address(scanner)
    return InternalQuantity("dimension", values[index - 1])


@atomic
def assign(host, opening, meaning):
    scanner = IntegerScanner(host)
    identity, index, _ = address(scanner, writing=True)
    scanner.optional_equals()
    result = dimension(scanner)
    scanner.finish()
    host.context.fonts.assign(identity, index, result)
    span = host.reader.source_span(opening.span.start, host.reader.position)
    return SourceCommand(span, opening.token.value, "font_parameter_assignment",
                         metadata={"font": identity, "index": index, "value": result,
                                   "trailing_control_word": scanner.ends_control_word})


IDENTIFIER = PrimitiveOperation("font.identifier", ExpansionKind.UNEXPANDABLE, select, font_value, operand_type=str)
ASSIGN = PrimitiveOperation("font.dimension", ExpansionKind.UNEXPANDABLE, assign, value,
    operand_type=type(None), accepted_prefixes=frozenset({"global"}))
FAMILY = OperationFamily((IDENTIFIER, ASSIGN),
    (IDENTIFIER.declare("nullfont", "nullfont"), ASSIGN.declare("fontdimen", None)))
