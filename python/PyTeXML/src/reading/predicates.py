"""Bounded operand resolution for reading predicates, never body expansion.

Only a single character token, or an argument-free single-token definition chain
ending in one, is admitted. The captured definition-time catcode is authoritative.
Failed attempts restore the cursor, including mouth state and pending lookahead.
"""
from .contracts import SourceCommand, ScannedArgument, StoredDefinition
from .tex_reader import CatCode, TokenKind


def compare_characters(reader, context, opening, rule):
    if rule.predicate not in {"character_equal", "category_equal"}:
        return None
    checkpoint = reader.checkpoint()
    operands, resolved, definitions, definition_ids = [], [], [], set()
    for name in ("left", "right"):
        token = reader.next_token()
        if token is None:
            reader.restore(checkpoint)
            return None
        operands.append(ScannedArgument(name, token.span, (token,)))
        seen = set()
        while token.kind == TokenKind.CONTROL_SEQUENCE:
            key = (token.kind, token.value)
            definition = context.lookup_meaning(token.value, token.kind)
            if (key in seen or not isinstance(definition, StoredDefinition)
                    or definition.parameter_count or definition.parameter_tokens
                    or definition.hash_brace is not None or len(definition.body_tokens) != 1):
                reader.restore(checkpoint)
                return None
            seen.add(key)
            if definition.unit_id is not None and definition.unit_id not in definition_ids:
                definition_ids.add(definition.unit_id)
                definitions.append(definition.unit_id)
            token = definition.body_tokens[0]
        if token.kind != TokenKind.CHARACTER:
            reader.restore(checkpoint)
            return None
        resolved.append(token)
    left, right = resolved
    truth = left.value == right.value if rule.predicate == "character_equal" else left.catcode == right.catcode
    last = operands[-1].tokens[0]
    return SourceCommand(reader.source_span(opening.span.start, last.span.end), opening.value,
        "conditional_test", tuple(operands), {"predicate": rule.predicate, "truth": truth,
            "definition_unit_ids": definitions,
            "trailing_control_word": last.kind == TokenKind.CONTROL_SEQUENCE
                and all(context.catcodes[c] == CatCode.LETTER for c in last.value)})
