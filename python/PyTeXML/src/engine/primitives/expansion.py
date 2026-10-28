"""Expansion controls are Python operations with raw operand grammars."""
from ..operations import ExecutableOperation
from ...reading.contracts import ReadingIssue


def noexpand(cursor, token, profile):
    """Read one raw token and return it once without resolving its meaning."""
    following = cursor.next_token()
    if following is None:
        raise ReadingIssue("expansion_operand", "No token follows noexpand")
    cursor.suppressed = True
    return following


OPERATIONS = (ExecutableOperation("expansion.noexpand", expansion=noexpand),)
