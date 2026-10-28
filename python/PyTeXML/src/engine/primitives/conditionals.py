"""Raw meaning comparison and conditional routing over the shared frame owner.

ifx consumes exactly two unexpanded tokens (including explicit spaces/groups).
It writes only a conditional frame/decision. Unsupported comparisons restore the
cursor so preparation can preserve both branches with the existing scanner.
"""
from dataclasses import replace
from types import MappingProxyType

from ..meanings import compare_tokens
from ..operations import ExecutableOperation
from ...reading.contracts import ConditionalRule, ReadingIssue, ScannedArgument, SourceCommand
from ...reading.predicates import compare_characters
from ...reading.tex_reader import TokenKind


def compare_meanings(host, opening, rule):
    reader = host.reader
    saved = reader.checkpoint()
    left, right = reader.next_token(), reader.next_token()
    if left is None or right is None:
        reader.restore(saved)
        return None
    truth = compare_tokens(left, right, host.context, host.knowledge, host.operations)
    if truth is None:
        reader.restore(saved)
        return None
    definitions = []
    for token in (left, right):
        identifier = getattr(host.context.lookup_meaning(token.value, token.kind), "unit_id", None)
        if identifier is not None and identifier not in definitions:
            definitions.append(identifier)
    return SourceCommand(reader.source_span(opening.span.start, right.span.end), opening.value,
        "conditional_test", (ScannedArgument("left", left.span, (left,)), ScannedArgument("right", right.span, (right,))),
        {"predicate": "meaning_equal", "truth": truth, "definition_unit_ids": definitions,
         "trailing_control_word": right.kind == TokenKind.CONTROL_SEQUENCE and right.control_word})


def character_predicate(host, opening, rule):
    return compare_characters(host.reader, host.context, opening, rule)


PREDICATES = MappingProxyType({
    "character_equal": character_predicate,
    "category_equal": character_predicate,
    "meaning_equal": compare_meanings,
})


def execute_legacy(host, opening, profile):
    if not (profile.conditional is not None and profile.action is None
            and not profile.grammar and not profile.catcode_overrides
            and not profile.catcode_layers and not profile.reader_parameters
            and not profile.interpolations and not profile.active_options
            and profile.terminator is None and profile.state_management is None):
        raise ReadingIssue("unsupported_conditional", "Conditional requires a standalone nesting/evaluation rule")
    return route(host, opening, profile.conditional)


def execute(host, opening, meaning):
    return route(host, opening, meaning.operand)


def route(host, opening, rule):
    predicate = PREDICATES.get(rule.predicate)
    command = predicate(host, opening.token, rule) if predicate is not None else None
    if command is not None:
        identifier = host.route_conditional(ConditionalRule("opener", "always_true" if command.metadata["truth"] else "always_false"),
                                       command.span, metadata=command.metadata)
        return replace(command, unit_id=identifier)
    if host.preparation and rule.role == "opener" and rule.evaluation == "deferred":
        return host.capture_conditional(opening.token, rule)
    host.route_conditional(rule, opening.span)
    return opening


OPERATIONS = (ExecutableOperation("conditional.route", execute, continuation=True),
              ExecutableOperation("reading.conditional", execute_legacy))
