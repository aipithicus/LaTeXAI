"""Expansion controls are Python operations with raw operand grammars."""
from ..operations import ExecutableOperation
from ...reading.contracts import ReadingIssue, SourceCommand
from ...reading.tex_reader import CatCode, Token, TokenKind
from ..primitive import PrimitiveMeaning


def noexpand(cursor, token, profile):
    """Read one raw token and return it once without resolving its meaning."""
    following = cursor.next_token()
    if following is None:
        raise ReadingIssue("expansion_operand", "No token follows noexpand")
    cursor.suppressed = True
    return following


def relax(host, opening, meaning):
    return SourceCommand(opening.span, ("\\" + opening.token.value), "reading_noop")


def prefix(host, opening, meaning):
    raise ReadingIssue("assignment_prefix", "Prefixed assignments require explicit scope and prefix resolution")


def unsupported(host, opening, meaning):
    raise ReadingIssue("unsupported_primitive", f"{meaning.operand!r} is exposed but its operation is not implemented")


def expand_after(cursor, token, meaning):
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


def csname(cursor, token, meaning):
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
            cursor.context.record_meaning(name, PrimitiveMeaning("execution.relax", span=span))
        else:
            raise ReadingIssue("expansion_effect", "csname requires a scoped meaning assignment")
    # If existence is unavailable, both an existing meaning and a newly created
    # relax remain possible. Keep that uncertainty; a following def can overwrite
    # the slot without relying on either possibility.
    cursor.push((Token(TokenKind.CONTROL_SEQUENCE, name, None, span, transformed=True),))


def end_name(host, opening, meaning):
    raise ReadingIssue("unexpected_endcsname", "endcsname requires a name-construction consumer")


def expanded(cursor, token, meaning):
    """Collect a balanced fully expanded list and put it back as ordinary tokens."""
    opening = cursor.next_expanded()
    while opening is not None and opening.catcode == CatCode.SPACE:
        opening = cursor.next_expanded()
    if opening is None or opening.catcode != CatCode.BEGIN_GROUP:
        raise ReadingIssue("expanded_argument", "expanded requires a balanced group")
    result, depth = [], 1
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


OPERATIONS = (ExecutableOperation("expansion.noexpand", expansion=noexpand),
              ExecutableOperation("expansion.expand_after", expansion=expand_after),
              ExecutableOperation("expansion.expanded", expansion=expanded),
              ExecutableOperation("name.construct", expansion=csname),
              ExecutableOperation("name.end", end_name, unexpandable=True),
              ExecutableOperation("assignment.prefix", prefix, unexpandable=True),
              ExecutableOperation("execution.unsupported", unsupported, unexpandable=True),
              ExecutableOperation("expansion.unsupported", unsupported),
              ExecutableOperation("execution.relax", relax, unexpandable=True,
                                  capture=lambda reader, context, token, meaning:
                                      SourceCommand(token.span, token.value, "reading_noop")))
