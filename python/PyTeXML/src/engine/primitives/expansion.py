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
    raise ReadingIssue("assignment_prefix", "Prefixed assignments require explicit scope and prefix resolution")


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
            raise ReadingIssue("expansion_continuation", "A deferred noexpand marker needs a persistent token flag")
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
    span = cursor.source.source_span(token.span.start, cursor.source.position)
    current = cursor.context.resolve_meaning(cursor.knowledge, name)
    if isinstance(current, UndefinedMeaning) and current.uncertain is None:
        # This changes TeX state. Consumers without an execution transaction
        # must not publish it while merely attempting an expanded value.
        if getattr(cursor, "allow_name_assignment", False):
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
                cursor._charge(len(result))
                cursor.push(result)
                return
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
                UNSUPPORTED.declare("globaldefs", "globaldefs")),
)
