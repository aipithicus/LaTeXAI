"""Expandable conversions create character tokens without re-tokenizing them."""
from ..conditional_values import integer_scanner
from ..expansion import TokenListInsertion
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ...reading.contracts import ReadingIssue
from ...reading.tex_reader import CatCode, Token, TokenKind
from ..token_text import escape, token_text, meaning_text
from ..quantities import print_scaled


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


def roman_numeral(cursor, token, meaning):
    """TeX's print_roman_int, with allocation charged before constructing output."""
    value = integer_scanner(cursor).integer()
    if value <= 0:
        return
    parts = []
    for magnitude, spelling in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
                                (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
                                (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        count, value = divmod(value, magnitude)
        # characters() charges the final token allocation. Check the bound here
        # so a large legal integer cannot allocate millions of characters first.
        if sum(map(len, parts)) + count * len(spelling) > cursor.remaining:
            raise ReadingIssue("expansion_budget", "Roman conversion exceeds the expansion budget")
        parts.append(spelling * count)
    characters(cursor, "".join(parts), token.span)


def is_opening_group(cursor, token):
    from ...reading.contracts import BoundMeaning
    if token is None:
        return False
    if token.catcode == CatCode.BEGIN_GROUP:
        return True
    if token.kind != TokenKind.CHARACTER:
        value = cursor.context.resolve_meaning(cursor.knowledge, token.value, token.kind)
        return (isinstance(value, BoundMeaning) and value.uncertain is None and value.token is not None
                and value.token.catcode == CatCode.BEGIN_GROUP)
    return False


def group(cursor):
    opening = cursor.next_expanded()
    while opening is not None and opening.catcode == CatCode.SPACE:
        opening = cursor.next_expanded()
    if not is_opening_group(cursor, opening):
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
    quantity = scanner.internal(operand)
    if quantity.kind == "tokens":
        cursor._charge(len(quantity.value))
        return TokenListInsertion(quantity.value)
    if quantity.kind == "font":
        name = cursor.context.fonts.identifiers[quantity.value]
        from ..primitive import PrimitiveMeaning
        selector = cursor.context.resolve_meaning(cursor.knowledge, name)
        if not isinstance(selector, PrimitiveMeaning) or selector.operation != "font.identifier" or selector.operand != quantity.value:
            raise ReadingIssue("font_selector", "The original font selector was redefined; a frozen font token is required")
        return TokenListInsertion((Token(TokenKind.CONTROL_SEQUENCE, name, None, token.span,
                                         transformed=True, control_word=True),))
    if quantity.kind in {"glue", "muglue"}:
        from ..dimensions import glue_text
        text = glue_text(quantity.value, mu=quantity.kind == "muglue")
    else:
        text = print_scaled(quantity.value) if quantity.kind == "dimension" else str(quantity.value)
    return characters(cursor, text, token.span, insertion=True)


STRING = PrimitiveOperation("conversion.string", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=string)
NUMBER = PrimitiveOperation("conversion.number", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=number)
ROMAN = PrimitiveOperation("conversion.roman", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=roman_numeral)
DETOKENIZE = PrimitiveOperation("conversion.detokenize", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=detokenize)
UNEXPANDED = PrimitiveOperation("expansion.unexpanded", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=unexpanded)
MEANING = PrimitiveOperation("conversion.meaning", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=meaning)
THE = PrimitiveOperation("conversion.the", ExpansionKind.EXPANDABLE, operand_type=type(None), expansion=the)
FAMILY = OperationFamily((STRING, NUMBER, ROMAN, DETOKENIZE, UNEXPANDED, MEANING, THE),
    (STRING.declare("string", None), NUMBER.declare("number", None), DETOKENIZE.declare("detokenize", None),
     ROMAN.declare("romannumeral", None), UNEXPANDED.declare("unexpanded", None),
     MEANING.declare("meaning", None), THE.declare("the", None)))
