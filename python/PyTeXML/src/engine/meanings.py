"""Non-expanding TeX meaning identity, independent of source coordinates.

TeX82 tex.web, sections 506-507: compare command/operand pairs, or macro
flags and compiled token lists. Reading recipes alone are not TeX meanings.
Unsupported wrappers and absent knowledge have no comparison key.
"""
from functools import singledispatch
from .primitive import PrimitiveMeaning

from ..reading.contracts import (BooleanMeaning, BoundMeaning, CharacterCodeMeaning,
    CommandDefinition, EffectiveReadingProfile, EnvironmentDefinition, StoredDefinition,
    TokenListMeaning, UncertainMeaning, UndefinedMeaning)
from ..reading.tex_reader import CatCode, TokenKind


def token_key(token):
    # Control-sequence identity includes the active/control-sequence distinction,
    # but not current meaning, source spelling width, or definition location.
    if token.kind == TokenKind.CHARACTER:
        return ("character", token.catcode, token.value)
    return ("control", token.kind, token.value)


@singledispatch
def meaning_key(meaning, operations):
    return None


@meaning_key.register
def _(meaning: UndefinedMeaning, operations):
    return ("undefined",)


@meaning_key.register
def _(meaning: CharacterCodeMeaning, operations):
    return ("primitive", "char_given", meaning.value)


@meaning_key.register
def _(meaning: TokenListMeaning, operations):
    return ("macro", False, (), tuple(map(token_key, meaning.replacement_tokens)))


@meaning_key.register
def _(meaning: BooleanMeaning, operations):
    if meaning.target is None:
        from ..reading.contracts import ConditionalRule
        return ("primitive", "conditional.route",
                ConditionalRule("opener", "always_true" if meaning.truth else "always_false", 0))
    # The captured setter recipe is not its compiled TeX replacement list.
    return None


@meaning_key.register
def _(meaning: BoundMeaning, operations):
    return token_key(meaning.token) if meaning.token is not None else meaning_key(meaning.profile, operations)


@meaning_key.register
def _(meaning: PrimitiveMeaning, operations):
    return ("primitive", *meaning.identity)


def replacement_key(tokens):
    """Compile raw replacement markers; never expand referenced commands."""
    result, iterator = [], iter(tokens)
    for token in iterator:
        if token.catcode == CatCode.PARAMETER:
            following = next(iterator)
            result.append(token_key(following) if following.catcode == CatCode.PARAMETER
                          else ("out_parameter", int(following.value)))
        else:
            result.append(token_key(token))
    return tuple(result)


@meaning_key.register
def _(meaning: StoredDefinition, operations):
    long = False
    if isinstance(meaning, CommandDefinition):
        if meaning.optional_default is not None:
            return None  # The optional-argument wrapper has not been compiled.
        long = not meaning.starred
        parameters = tuple(("match", "#") for _ in range(meaning.parameter_count))
    else:
        parameters, iterator = [], iter(meaning.parameter_tokens)
        for token in iterator:
            if token.catcode == CatCode.PARAMETER:
                following = next(iterator, None)
                if following is None:
                    parameters.append(token_key(meaning.hash_brace))
                else:
                    parameters.append(("match", token.value))
            else:
                parameters.append(token_key(token))
        parameters = tuple(parameters)
    replacement = replacement_key(meaning.replacement_tokens)
    if meaning.hash_brace is not None:
        replacement += (token_key(meaning.hash_brace),)
    return ("macro", long, parameters, replacement)


def compare_tokens(left, right, context, knowledge, operations):
    """Return known truth or None. No expansion, assignment or symbol creation."""
    if token_key(left) == token_key(right):
        return True  # The identical token has identical meaning, even if unknown.

    def resolve(token):
        if token.kind == TokenKind.CHARACTER:
            return None, token_key(token)
        meaning = context.resolve_meaning(knowledge, token.value, token.kind)
        if isinstance(meaning, UncertainMeaning) or getattr(meaning, "uncertain", None) is not None:
            return None, None
        return meaning, meaning_key(meaning, operations)

    a, a_key = resolve(left)
    b, b_key = resolve(right)
    if a is not None and a is b and not isinstance(a, EnvironmentDefinition):
        return True  # A known copied meaning, including an uncompiled wrapper.
    if a_key is None or b_key is None:
        return None
    return a_key == b_key
