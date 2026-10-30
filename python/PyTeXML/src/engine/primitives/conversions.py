"""Expandable conversions create character tokens without re-tokenizing them."""
from ..conditional_values import integer_scanner
from ..expansion import TokenListInsertion
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ...reading.contracts import ReadingIssue
from ...reading.tex_reader import CatCode, Token, TokenKind
from ..token_text import escape, token_text, meaning_text


def characters(cursor, text, span, *, insertion=False):
    cursor._charge(len(text))
    tokens = tuple(Token(TokenKind.CHARACTER, c, CatCode.SPACE if c == " " else CatCode.OTHER,
                         span, transformed=True) for c in text)
    if insertion:
        return TokenListInsertion(tokens)
    cursor.push(tokens)


def string(cursor, token, meaning):
    operand = cursor.next_token()
    if operand is None:
        raise ReadingIssue("expansion_operand", "string requires one raw token")
    text = (escape(cursor.context) if operand.kind == TokenKind.CONTROL_SEQUENCE else "") + operand.value
    characters(cursor, text, operand.span)


def number(cursor, token, meaning):
    scanner = integer_scanner(cursor)
    characters(cursor, str(scanner.integer()), token.span)


def group(cursor):
    opening = cursor.next_expanded()
    while opening is not None and opening.catcode == CatCode.SPACE:
        opening = cursor.next_expanded()
    if opening is None or opening.catcode != CatCode.BEGIN_GROUP:
        raise ReadingIssue("conversion_argument", "Expected an opening group")
    tokens, depth = [], 1
    while (token := cursor.next_token()) is not None:
        depth += (token.catcode == CatCode.BEGIN_GROUP) - (token.catcode == CatCode.END_GROUP)
        if depth == 0:
            return tokens
        tokens.append(token)
    raise ReadingIssue("conversion_argument", "EOF in conversion argument")


def detokenize(cursor, token, meaning):
    text = "".join(token_text(t, cursor.context, double_parameters=True) for t in group(cursor))
    return characters(cursor, text, token.span, insertion=True)


def unexpanded(cursor, token, meaning):
    return TokenListInsertion(tuple(group(cursor)))


def meaning(cursor, token, profile):
    operand = cursor.next_token()
    if operand is None:
        raise ReadingIssue("conversion_argument", "meaning requires one raw token")
    from ...reading.contracts import BoundMeaning
    value = (BoundMeaning(operand.span, token=operand) if operand.kind == TokenKind.CHARACTER else
             cursor.context.resolve_meaning(cursor.knowledge, operand.value, operand.kind))
    if getattr(value, "uncertain", None) is not None:
        raise ReadingIssue("uncertain_meaning", "Meaning conversion depends on unresolved state", causes=(value.uncertain,))
    characters(cursor, meaning_text(value, cursor.context), operand.span)


def the(cursor, token, meaning):
    scanner = integer_scanner(cursor)
    operand = cursor.next_expanded()
    if operand is None:
        raise ReadingIssue("conversion_argument", "the requires an internal quantity")
    resolved = scanner._meaning(operand)
    if not isinstance(resolved, tuple) or resolved[0].integer_value is None:
        raise ReadingIssue("conversion_argument", "the requires a supported internal quantity")
    value = resolved[0].integer_value(scanner, resolved[1])
    if resolved[1].operation == "register.assign" and resolved[1].operand.kind == "dimen":
        raise ReadingIssue("dimension_display", "Dimension display conversion is not established")
    return characters(cursor, str(value), token.span, insertion=True)


STRING = PrimitiveOperation("conversion.string", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=string)
NUMBER = PrimitiveOperation("conversion.number", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=number)
DETOKENIZE = PrimitiveOperation("conversion.detokenize", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=detokenize)
UNEXPANDED = PrimitiveOperation("expansion.unexpanded", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=unexpanded)
MEANING = PrimitiveOperation("conversion.meaning", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=meaning)
THE = PrimitiveOperation("conversion.the", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=the)
FAMILY = OperationFamily((STRING, NUMBER, DETOKENIZE, UNEXPANDED, MEANING, THE),
    (STRING.declare("string", None), NUMBER.declare("number", None), DETOKENIZE.declare("detokenize", None),
     UNEXPANDED.declare("unexpanded", None), MEANING.declare("meaning", None), THE.declare("the", None)))
