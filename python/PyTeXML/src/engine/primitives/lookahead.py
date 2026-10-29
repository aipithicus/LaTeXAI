"""Raw futurelet over a frozen continuation: two tokens stay available."""
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..transactions import atomic, assignment_global
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.contracts import BoundMeaning, ReadingIssue, SourceCommand, UncertainMeaning
from ...reading.tex_reader import TokenKind
from ...reading.token_cursor import TokenCursor


@atomic
def futurelet(host, opening, meaning):
    if not isinstance(host.reader, TokenCursor):
        raise ReadingIssue("lookahead_continuation", "Physical futurelet requires frozen lookahead across the next execution")
    target = AssignmentScanner(host.reader, host.context).target()
    saved = host.reader.checkpoint()
    first, second = host.reader.next_token(), host.reader.next_token()
    host.reader.restore(saved)
    if first is None or second is None:
        raise ReadingIssue("argument_lookahead", "futurelet needs two continuation tokens")
    donor = host.context.resolve_meaning(host.knowledge, second.value, second.kind)
    if second.kind == TokenKind.CHARACTER:
        donor = BoundMeaning(second.span, token=second)
    if donor is None:
        donor = UncertainMeaning(second.span)
    host.context.record_meaning(target.value, donor, target.kind, global_=assignment_global(host))
    return SourceCommand(host.reader.source_span(opening.span.start, host.reader.position), opening.token.value,
        "meaning_assignment", metadata={"donor_resolved": not isinstance(donor, UncertainMeaning)})


FUTURELET = PrimitiveOperation("meaning.futurelet", ExpansionKind.UNEXPANDABLE, futurelet,
    operand_type=type(None), accepted_prefixes=frozenset({"global"}))
FAMILY = OperationFamily((FUTURELET,), (FUTURELET.declare("futurelet", None),))
