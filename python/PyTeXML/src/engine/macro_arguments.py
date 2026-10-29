"""TeX macro-call matching over raw tokens, independent of input frame layout.

Definition capture has already validated consecutive parameter numbers. Matching
uses token identity, never current meaning or reconstructed source spelling.
"""
from ..reading.argument_scanner import undelimited_tokens
from ..reading.contracts import ReadingIssue
from ..reading.tex_reader import CatCode, TokenKind
from .meanings import token_key


def signature(definition):
    prefix, delimiters = [], []
    current = prefix
    iterator = iter(definition.parameter_tokens)
    for token in iterator:
        if token.catcode != CatCode.PARAMETER:
            current.append(token)
            continue
        digit = next(iterator, None)
        if digit is None:
            current.append(definition.hash_brace)
            break
        current = []
        delimiters.append(current)
    return tuple(prefix), tuple(tuple(d) for d in delimiters)


def _strip_group(tokens):
    if not tokens or tokens[0].catcode != CatCode.BEGIN_GROUP:
        return tuple(tokens)
    depth = 0
    for index, token in enumerate(tokens):
        depth += (token.catcode == CatCode.BEGIN_GROUP) - (token.catcode == CatCode.END_GROUP)
        if depth == 0:
            return tuple(tokens[1:-1]) if index == len(tokens) - 1 else tuple(tokens)
    return tuple(tokens)


def delimited(cursor, delimiter, name, *, long):
    result, keys, depth = [], [], 0
    expected = tuple(map(token_key, delimiter))
    while (token := cursor.next_token()) is not None:
        if not long and token.kind == TokenKind.CONTROL_SEQUENCE and token.value == "par":
            raise ReadingIssue("short_macro_paragraph", f"Paragraph in argument to {name!r}")
        result.append(token)
        keys.append(token_key(token))
        if depth == 0:
            cursor._charge(min(len(keys), len(expected)))
            if tuple(keys[-len(expected):]) == expected:
                return _strip_group(result[:-len(expected)])
        depth += (token.catcode == CatCode.BEGIN_GROUP) - (token.catcode == CatCode.END_GROUP)
        if depth < 0:
            raise ReadingIssue("macro_argument_group", f"Extra closing group in argument to {name!r}")
    raise ReadingIssue("macro_argument_delimiter", f"EOF before the argument delimiter for {name!r}")


def arguments(cursor, token, definition):
    prefix, delimiters = signature(definition)
    for expected in prefix:
        actual = cursor.next_token()
        if actual is None or token_key(actual) != token_key(expected):
            raise ReadingIssue("macro_argument_prefix", f"Invocation of {token.value!r} does not match its prefix")
    long = definition.long
    return tuple(delimited(cursor, delimiter, token.value, long=long) if delimiter else
                 undelimited_tokens(cursor, token.value, long=long)[0] for delimiter in delimiters)
