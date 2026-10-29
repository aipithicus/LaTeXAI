"""Physical input termination; replacement tokens do not own a file handle."""
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ...reading.contracts import ReadingIssue, SourceCommand
from ...reading.token_cursor import TokenCursor


def end_input(host, opening, meaning):
    reader = host.reader
    if isinstance(reader, TokenCursor):
        raise ReadingIssue("token_input_boundary", "Endinput needs the physical input owner")
    reader.end_input_after_line()
    return SourceCommand(opening.span, opening.token.value, "end_input")


END_INPUT = PrimitiveOperation("input.end", ExpansionKind.UNEXPANDABLE, end_input,
    operand_type=type(None), continuation=True)
FAMILY = OperationFamily((END_INPUT,), (END_INPUT.declare("endinput", None),))
