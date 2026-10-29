"""Expansion controls are Python operations with raw operand grammars."""
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ...reading.contracts import ReadingIssue, SourceCommand
from ...reading.tex_reader import CatCode, Token, TokenKind
from ..primitive import PrimitiveMeaning


def noexpand(cursor, token, profile: PrimitiveMeaning[None]):
    """Read one raw token and return it once without resolving its meaning."""
    following = cursor.next_token()
    if following is None:
        raise ReadingIssue("expansion_operand", "No token follows noexpand")
    cursor.suppressed = True
    return following


def relax(host, opening, meaning: PrimitiveMeaning[None]):
    return SourceCommand(opening.span, ("\\" + opening.token.value), "reading_noop")


def prefix(host, opening, meaning: PrimitiveMeaning[str]):
    from dataclasses import replace
    from ..expansion import ExpansionCursor
    from ..continuation import ContinuationReader
    from ..transactions import transaction
    with transaction(host):
        source = host.reader
        cursor = ExpansionCursor(source, host.context, host.knowledge, host.operations, host=host)
        prefixes = {meaning.operand}
        while (token := cursor.next_expanded()) is not None:
            if token.catcode == CatCode.SPACE:
                continue
            target = host.context.resolve_meaning(host.knowledge, token.value, token.kind)
            if isinstance(target, PrimitiveMeaning) and target.operation == "assignment.prefix":
                prefixes.add(target.operand)
                continue
            if isinstance(target, PrimitiveMeaning) and target.operation == "execution.relax":
                continue
            operation = host.operations.get(target.operation) if isinstance(target, PrimitiveMeaning) else None
            if operation is None or not prefixes <= operation.accepted_prefixes:
                raise ReadingIssue("assignment_prefix", "These prefixes do not apply to the following operation")
            break
        else:
            raise ReadingIssue("assignment_prefix", "EOF after assignment prefix")
        previous = getattr(host, "assignment_prefixes", frozenset())
        host.assignment_prefixes = frozenset(prefixes)
        try:
            if host.program:
                from ..programs import frozen_reader
                tail = []
                while (part := cursor.next_token()) is not None:
                    tail.append(part)
                host._set_reader(frozen_reader(host, (token, *tail), opening.span))
                event = host.reader.next_event()
                return operation.execute(host, event, target)
            span = source.source_span(opening.span.start, source.position)
            host._set_reader(ContinuationReader(cursor, opening.span.start))
            result = operation.execute(host, replace(opening, span=span, token=replace(token, span=span)), target)
            if cursor.pending:
                raise ReadingIssue("expansion_continuation", "Prefixed operation leaves replacement input pending")
            return result
        finally:
            host.assignment_prefixes = previous
            if not host.program:
                host._set_reader(source)


def unsupported(host, opening, meaning: PrimitiveMeaning[str]):
    raise ReadingIssue("unsupported_primitive", f"{meaning.operand!r} is exposed but its operation is not implemented")


def expand_after(cursor, token, meaning: PrimitiveMeaning[None]):
    """Defer one raw token; expand the second exactly once, then reinsert first."""
    first, second = cursor.next_token(), cursor.next_token()
    if first is None or second is None:
        raise ReadingIssue("expansion_operand", "expandafter requires two tokens")
    result = cursor.expand_once(second)
    if result is not None:
        if cursor.suppressed:
            from dataclasses import replace
            result = replace(result, expansion_suppressed=True)
            cursor.suppressed = False
        cursor.push((result,))
    cursor.push((first,))


def csname(cursor, token, meaning: PrimitiveMeaning[None]):
    """Expand character tokens to endcsname; unknown name state stays unknown."""
    from ...reading.contracts import UndefinedMeaning
    parts = []
    while (part := cursor.next_expanded()) is not None:
        if part.kind != TokenKind.CHARACTER:
            end = cursor.context.resolve_meaning(cursor.knowledge, part.value, part.kind)
            if isinstance(end, PrimitiveMeaning) and end.operation == "name.end":
                break
            raise ReadingIssue("csname_character", "A control sequence remains inside csname")
        parts.append(part.value)
    else:
        raise ReadingIssue("csname_terminator", "EOF before endcsname")
    name = "".join(parts)
    span = (cursor.source.source_span(token.span.start, cursor.source.position)
            if token.span.basis == cursor.source.basis and token.span.start <= cursor.source.position else token.span)
    current = cursor.context.resolve_meaning(cursor.knowledge, name)
    if isinstance(current, UndefinedMeaning) and current.uncertain is None:
        # This changes TeX state. Consumers without an execution transaction
        # must not publish it while merely attempting an expanded value.
        if getattr(cursor, "allow_name_assignment", False):
            from ...reading.context import ExecutionMode
            with cursor.context.execution_mode(ExecutionMode.ACTIVE_EXECUTION):
                cursor.context.record_meaning(name, PrimitiveMeaning("execution.relax", None, span=span))
        else:
            raise ReadingIssue("expansion_effect", "csname requires a scoped meaning assignment")
    # If existence is unavailable, both an existing meaning and a newly created
    # relax remain possible. Keep that uncertainty; a following def can overwrite
    # the slot without relying on either possibility.
    cursor.push((Token(TokenKind.CONTROL_SEQUENCE, name, None, span, transformed=True),))


def end_name(host, opening, meaning: PrimitiveMeaning[None]):
    raise ReadingIssue("unexpected_endcsname", "endcsname requires a name-construction consumer")


def expanded(cursor, token, meaning: PrimitiveMeaning[None]):
    """Collect a balanced fully expanded list and put it back as ordinary tokens."""
    previous = cursor.protect_macros
    cursor.protect_macros = True
    try:
        result = expanded_list(cursor)
    finally:
        cursor.protect_macros = previous
    cursor._charge(len(result))
    cursor.push(result)


def expanded_list(cursor):
    opening = cursor.next_expanded()
    while opening is not None and opening.catcode == CatCode.SPACE:
        opening = cursor.next_expanded()
    if opening is None or opening.catcode != CatCode.BEGIN_GROUP:
        raise ReadingIssue("expanded_argument", "expanded requires a balanced group")
    result: list[Token] = []
    depth = 1
    while (part := cursor.next_expanded()) is not None:
        if part.catcode == CatCode.BEGIN_GROUP:
            depth += 1
        elif part.catcode == CatCode.END_GROUP:
            depth -= 1
            if depth == 0:
                return result
        result.append(part)
    raise ReadingIssue("expanded_argument", "EOF before expanded's closing group")


def capture_relax(reader, context, token, meaning: PrimitiveMeaning[None]):
    return SourceCommand(token.span, token.value, "reading_noop")


NOEXPAND = PrimitiveOperation("expansion.noexpand", ExpansionKind.EXPANDABLE,
                              operand_type=type(None), expansion=noexpand)
EXPAND_AFTER = PrimitiveOperation("expansion.expand_after", ExpansionKind.EXPANDABLE,
                                  operand_type=type(None), expansion=expand_after)
EXPANDED = PrimitiveOperation("expansion.expanded", ExpansionKind.EXPANDABLE,
                              operand_type=type(None), expansion=expanded)
CSNAME = PrimitiveOperation("name.construct", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=csname)
END_NAME = PrimitiveOperation("name.end", ExpansionKind.UNEXPANDABLE, end_name, operand_type=type(None))
PREFIX = PrimitiveOperation("assignment.prefix", ExpansionKind.UNEXPANDABLE, prefix, operand_type=str)
UNSUPPORTED = PrimitiveOperation("execution.unsupported", ExpansionKind.UNEXPANDABLE, unsupported, operand_type=str)
UNSUPPORTED_EXPANSION = PrimitiveOperation("expansion.unsupported", ExpansionKind.EXPANDABLE, unsupported,
                                          operand_type=str, expansion_unavailable=True)
RELAX = PrimitiveOperation("execution.relax", ExpansionKind.UNEXPANDABLE, relax,
                           operand_type=type(None), capture=capture_relax)

FAMILY = OperationFamily(
    operations=(NOEXPAND, EXPAND_AFTER, EXPANDED, CSNAME, END_NAME, PREFIX,
                UNSUPPORTED, UNSUPPORTED_EXPANSION, RELAX),
    primitives=(NOEXPAND.declare("noexpand", None), EXPAND_AFTER.declare("expandafter", None),
                EXPANDED.declare("expanded", None, extension=True), CSNAME.declare("csname", None),
                END_NAME.declare("endcsname", None), RELAX.declare("relax", None),
                *(PREFIX.declare(name, name) for name in ("global", "long", "outer", "protected")),
                UNSUPPORTED.declare("numexpr", "numexpr"),
                ),
)
