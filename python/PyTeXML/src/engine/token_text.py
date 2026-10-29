"""TeX token-display conversions; these strings are not an ordinary input path."""
from .primitive import PrimitiveMeaning
from ..reading.contracts import (BoundMeaning, CharacterCodeMeaning, CommandDefinition, ReadingIssue,
                                StoredDefinition, TokenListMeaning, UndefinedMeaning)
from ..reading.tex_reader import CatCode, TokenKind


def escape(context):
    value = context.integer_parameters.read("escapechar")
    return chr(value) if 0 <= value <= 255 else ""


def token_text(token, context, *, double_parameters=False):
    if token.kind == TokenKind.CONTROL_SEQUENCE:
        trailing = len(token.value) > 1 or (bool(token.value) and context.catcodes[token.value] == CatCode.LETTER)
        return escape(context) + token.value + (" " if trailing else "")
    return token.value * (2 if double_parameters and token.catcode == CatCode.PARAMETER else 1)


def meaning_text(meaning, context):
    if isinstance(meaning, UndefinedMeaning):
        return "undefined"
    if isinstance(meaning, CommandDefinition):
        raise ReadingIssue("meaning_wrapper", "A captured declaration does not establish the kernel wrapper")
    if isinstance(meaning, StoredDefinition):
        flags = "".join(escape(context) + name for name in ("protected", "long", "outer") if getattr(meaning, name))
        parameters = meaning.parameter_tokens[:-1] if meaning.hash_brace else meaning.parameter_tokens
        parameter_text = "".join(token_text(t, context) for t in parameters)
        if meaning.hash_brace:
            parameter_text += token_text(meaning.hash_brace, context)
        replacement = "".join(token_text(t, context) for t in meaning.replacement_tokens)
        if meaning.hash_brace:
            replacement += token_text(meaning.hash_brace, context)
        return flags + (" " if flags else "") + "macro:" + parameter_text + "->" + replacement
    if isinstance(meaning, TokenListMeaning):
        return "macro:->" + "".join(token_text(t, context, double_parameters=True) for t in meaning.replacement_tokens)
    if isinstance(meaning, CharacterCodeMeaning):
        return escape(context) + 'char"' + format(meaning.value, "X")
    if isinstance(meaning, PrimitiveMeaning):
        if meaning.operation == "register.assign" and meaning.operand.index is not None:
            return escape(context) + meaning.operand.kind + str(meaning.operand.index)
        from .catalog import COMMON_PRIMITIVES, EXTENSIONS
        for name, primitive in (*COMMON_PRIMITIVES.items(), *EXTENSIONS.items()):
            if primitive.identity == meaning.identity:
                return escape(context) + name
    if isinstance(meaning, BoundMeaning) and meaning.token is not None:
        descriptions = {CatCode.SPACE: "blank space ", CatCode.LETTER: "the letter ", CatCode.OTHER: "the character "}
        if meaning.token.catcode in descriptions:
            return descriptions[meaning.token.catcode] + meaning.token.value
    raise ReadingIssue("meaning_unavailable", "This meaning has no established TeX display conversion")
