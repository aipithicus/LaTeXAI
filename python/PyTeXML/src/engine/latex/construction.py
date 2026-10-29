"""Construct native macro state with explicit token origins and diagnostics."""
from dataclasses import replace

from ..programs import frozen_reader
from ...reading.definition_scanner import DefinitionScanner
from ...reading.tex_reader import Token, TokenKind, CatCode


def control(name, anchor):
    return Token(TokenKind.CONTROL_SEQUENCE, name, None, anchor, transformed=True, control_word=True)


def character(value, anchor, catcode=CatCode.OTHER):
    return Token(TokenKind.CHARACTER, value, catcode, anchor, transformed=True)


def group(tokens, anchor):
    return (character('{', anchor, CatCode.BEGIN_GROUP), *tokens,
            character('}', anchor, CatCode.END_GROUP))


def parameter(number, anchor):
    return (character('#', anchor, CatCode.PARAMETER), character(str(number), anchor))


def definition(host, target, parameters, body, anchor, *, long=False, protected=False):
    """Compile a token construction through the ordinary primitive scanner.

    The generated coordinate basis is diagnostic. Authored body/argument tokens
    retain their origin relation; no constructed span claims to be manuscript text.
    """
    tokens = (control('def', anchor), target, *parameters, *group(body, anchor))
    reader = frozen_reader(host, tokens, anchor)
    host.program_sources[-1] = replace(host.program_sources[-1], kind='constructed_definition')
    opening = reader.next_token()
    result = DefinitionScanner(reader, host.context).primitive(opening.span.start)
    return replace(result, long=long, protected=protected, binding_id='latex-python/2026-06-01')
