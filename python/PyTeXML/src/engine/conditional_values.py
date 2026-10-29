"""Conditional operands and pass_text over the shared expansion input."""
from .meanings import compare_tokens
from .primitive import PrimitiveMeaning
from .resolution import conditional_rule
from ..reading.contracts import BoundMeaning, ReadingIssue, UncertainMeaning, UndefinedMeaning
from ..reading.tex_reader import CatCode, TokenKind


def defined(cursor, token):
    if token is None:
        raise ReadingIssue("conditional_operand", "Missing definedness operand")
    if token.kind == TokenKind.CHARACTER:
        return True
    meaning = cursor.context.resolve_meaning(cursor.knowledge, token.value, token.kind)
    if meaning is None or isinstance(meaning, UncertainMeaning) or getattr(meaning, "uncertain", None):
        return None
    return not isinstance(meaning, UndefinedMeaning)


def name_tokens(cursor):
    parts = []
    while (token := cursor.next_expanded()) is not None:
        if token.kind != TokenKind.CHARACTER:
            meaning = cursor.context.resolve_meaning(cursor.knowledge, token.value, token.kind)
            if isinstance(meaning, PrimitiveMeaning) and meaning.operation == "name.end":
                return "".join(parts)
            raise ReadingIssue("csname_character", "A control sequence remains inside a name")
        parts.append(token.value)
    raise ReadingIssue("csname_terminator", "EOF before endcsname")


def integer_scanner(cursor):
    from .integers import IntegerScanner
    if cursor.host is None:
        raise ReadingIssue("conditional_context", "Numeric expansion needs an execution owner")
    scanner = IntegerScanner(cursor.host)
    scanner.reader = cursor
    return scanner


def test(cursor, rule):
    if rule.evaluation in {"always_true", "always_false"}:
        return rule.evaluation == "always_true"
    predicate = rule.predicate
    if predicate in {"character_equal", "category_equal"}:
        def character():
            token = cursor.next_expanded()
            if token is None:
                raise ReadingIssue("conditional_operand", "Character test requires two expanded tokens")
            if cursor.suppressed and token.kind == TokenKind.ACTIVE_CHARACTER:
                return CatCode.ACTIVE, ord(token.value)
            if token.kind == TokenKind.CHARACTER:
                return token.catcode, ord(token.value)
            meaning = cursor.context.resolve_meaning(cursor.knowledge, token.value, token.kind)
            if not cursor.suppressed and isinstance(meaning, BoundMeaning) and meaning.token is not None:
                return meaning.token.catcode, ord(meaning.token.value)
            return 16, 256
        left, right = character(), character()
        return left[1 if predicate == "character_equal" else 0] == right[1 if predicate == "character_equal" else 0]
    if predicate == "defined":
        return defined(cursor, cursor.next_token())
    if predicate == "name_defined":
        name = name_tokens(cursor)
        from ..reading.tex_reader import Token
        return defined(cursor, Token(TokenKind.CONTROL_SEQUENCE, name, None, cursor.source.basis.whole))
    if predicate == "meaning_equal":
        left, right = cursor.next_token(), cursor.next_token()
        if left is None or right is None:
            raise ReadingIssue("conditional_operand", "ifx requires two raw tokens")
        return compare_tokens(left, right, cursor.context, cursor.knowledge, cursor.operations)
    if predicate in {"integer_compare", "integer_odd"}:
        scanner = integer_scanner(cursor)
        left = scanner.integer()
        if predicate == "integer_odd":
            return bool(left % 2)
        relation = cursor.next_expanded()
        while relation is not None and relation.catcode == CatCode.SPACE:
            relation = cursor.next_expanded()
        if relation is None or relation.catcode != CatCode.OTHER or relation.value not in "<=>":
            raise ReadingIssue("conditional_relation", "Integer test requires <, = or >")
        right = scanner.integer()
        return {"<": left < right, "=": left == right, ">": left > right}[relation.value]
    return None


def skip(cursor, *, alternative):
    """TeX pass_text: resolve nesting tokens without expanding or scanning args."""
    depth = 0
    while (token := cursor.next_token()) is not None:
        meaning = cursor.context.resolve_meaning(cursor.knowledge, token.value, token.kind)
        rule = conditional_rule(meaning)
        if rule is None:
            continue
        if getattr(meaning, "uncertain", None) is not None:
            raise ReadingIssue("conditional_nesting", "Skipped conditional meaning is uncertain")
        if rule.role == "opener":
            depth += 1
        elif rule.role == "terminator":
            if depth == 0:
                return token, rule
            depth -= 1
        elif depth == 0 and alternative and rule.role == "alternative":
            return token, rule
    raise ReadingIssue("unclosed_conditional", "EOF in skipped conditional text")
