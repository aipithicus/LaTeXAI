"""Nonexecuting primitive capture, shared with dependency and effect readers."""
from .catalog import CORE_OPERATIONS
from .primitive import PrimitiveMeaning
from ..reading.contracts import ReadingIssue


def capture_primitive(reader, context, token, meaning):
    if meaning.uncertain is not None:
        raise ReadingIssue("uncertain_meaning", "Cannot observe an uncertain primitive", causes=(meaning.uncertain,))
    operation = CORE_OPERATIONS[meaning.operation]
    if operation.capture is not None:
        return operation.capture(reader, context, token, meaning)
    if operation.expansion is not None:
        raise ReadingIssue("expansion_continuation", "Observed expansion does not authorize later raw-token execution")
    return None
