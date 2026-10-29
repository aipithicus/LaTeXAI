"""Mode effects admitted by the explicit primitive initialization boundary."""
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ...reading.contracts import ReadingIssue, SourceCommand


def paragraph(host, opening, meaning):
    if host.preparation and not host.program:
        return SourceCommand(opening.span, opening.token.value, "opaque", metadata={"execution": "deferred_layout"})
    policy = getattr(host, "program_policy", None)
    if not host.context.primitive_initial_state or policy is None or policy.content:
        raise ReadingIssue("paragraph_mode", "Paragraph execution requires an established typesetting mode")
    # The setup-only initial-state program starts vertical and cannot admit text,
    # boxes or another operation that starts a paragraph. TeX ignores par here.
    return SourceCommand(opening.span, opening.token.value, "reading_noop")


def capture_paragraph(reader, context, token, meaning):
    return SourceCommand(token.span, token.value, "opaque", metadata={"execution": "deferred_layout"})


PAR = PrimitiveOperation("mode.paragraph", ExpansionKind.UNEXPANDABLE, paragraph,
                         operand_type=type(None), capture=capture_paragraph)
FAMILY = OperationFamily((PAR,), (PAR.declare("par", None),))
