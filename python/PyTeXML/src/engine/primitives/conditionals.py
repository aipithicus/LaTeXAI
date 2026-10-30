"""Raw meaning comparison and conditional routing over the shared frame owner.

ifx consumes exactly two unexpanded tokens (including explicit spaces/groups).
It writes only a conditional frame/decision. Unsupported comparisons restore the
cursor so preparation can preserve both branches with the existing scanner.
"""
from dataclasses import replace
from types import MappingProxyType

from ..meanings import compare_tokens
from ..operations import ExecutableOperation, ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ...reading.contracts import ConditionalRule, EffectiveReadingProfile, ReadingIssue, ScannedArgument, SourceCommand
from ...reading.predicates import compare_characters
from ...reading.tex_reader import TokenKind
from ..expansion import ExpansionCursor
from ..conditional_values import test, skip
from ..transactions import atomic, transaction


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
    if host.program:
        return expansion_predicate(host, opening, rule)
    return compare_characters(host.reader, host.context, opening, rule)


PREDICATES = MappingProxyType({
    "character_equal": character_predicate,
    "category_equal": character_predicate,
    "meaning_equal": compare_meanings,
})


def expansion_predicate(host, opening, rule):
    try:
        with transaction(host):
            cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations, host=host)
            result = test(cursor, rule)
            if result is None:
                raise _UnresolvedPredicate
            truth = result == 0 if rule.predicate == "integer_case" else result
            if cursor.pending:
                raise ReadingIssue("conditional_continuation", "Predicate leaves replacement input pending")
            last = cursor.source_tokens[-1] if cursor.source_tokens else opening
            return SourceCommand(host.reader.source_span(opening.span.start, host.reader.position), opening.value,
                "conditional_test", metadata={"predicate": rule.predicate, "truth": truth, "definition_unit_ids": [],
                    **({"case_index": result} if rule.predicate == "integer_case" else {}),
                    "trailing_control_word": last.control_word and last.span.end == host.reader.position})
    except _UnresolvedPredicate:
        return None


class _UnresolvedPredicate(Exception):
    """Rollback a speculative predicate before its raw capture is attempted."""


def expand_route(cursor, token, meaning):
    host, rule = cursor.host, meaning.operand
    if host is None:
        raise ReadingIssue("conditional_context", "Conditional expansion requires its execution owner")
    metadata = None
    if rule.role == "opener":
        result = test(cursor, rule)
        if result is None:
            raise ReadingIssue("unsupported_conditional", "Conditional predicate is not established")
        truth = result == 0 if rule.predicate == "integer_case" else result
        metadata = {"case_index": result} if rule.predicate == "integer_case" else None
        rule = ConditionalRule("opener", "always_true" if truth else "always_false")
    host.route_conditional(rule, token.span, metadata=metadata)
    while host._skip_start is not None:
        host._skip_start = None
        delimiter, end_rule = skip(cursor, alternative=not host._conditionals[-1].in_alternative)
        host.route_conditional(end_rule, delimiter.span)


def execute_legacy(host, opening, profile):
    if not (profile.conditional is not None and profile.action is None
            and not profile.grammar and not profile.catcode_overrides
            and not profile.catcode_layers and not profile.reader_parameters
            and not profile.interpolations and not profile.active_options
            and profile.terminator is None and profile.state_management is None):
        raise ReadingIssue("unsupported_conditional", "Conditional requires a standalone nesting/evaluation rule")
    return route(host, opening, profile.conditional)


@atomic
def execute(host, opening, meaning: PrimitiveMeaning[ConditionalRule]):
    return route(host, opening, meaning.operand)


def capture_header(reader, context, token, meaning):
    """Consume only the declared raw header; never choose a branch."""
    rule = meaning.operand
    count = rule.capture_operands if rule.role == "opener" else 0
    if count is None:
        raise ReadingIssue("conditional_header", "Predicate has no raw operand grammar")
    operands = []
    for index in range(count):
        operand = reader.next_token()
        if operand is None:
            raise ReadingIssue("conditional_header", "EOF in conditional operands")
        operands.append(ScannedArgument(str(index), operand.span, (operand,)))
    last = operands[-1].tokens[-1] if operands else token
    return SourceCommand(reader.source_span(token.span.start, reader.position), token.value,
                         "conditional_test", tuple(operands), metadata={
                             "trailing_control_word": last.control_word and last.span.end == reader.position})


def route(host, opening, rule):
    predicate = PREDICATES.get(rule.predicate)
    command = predicate(host, opening.token, rule) if predicate is not None else (
        expansion_predicate(host, opening.token, rule) if rule.predicate is not None else None)
    if command is not None:
        identifier = host.route_conditional(ConditionalRule("opener", "always_true" if command.metadata["truth"] else "always_false"),
                                       command.span, metadata=command.metadata)
        return replace(command, unit_id=identifier)
    if host.preparation and rule.role == "opener" and rule.evaluation == "deferred":
        return host.capture_conditional(opening.token, rule)
    host.route_conditional(rule, opening.span)
    return opening


ROUTE = PrimitiveOperation("conditional.route", ExpansionKind.EXPANDABLE, execute,
                           operand_type=ConditionalRule, continuation=True, expansion=expand_route,
                           capture=capture_header)

FAMILY = OperationFamily(
    operations=(ROUTE, ExecutableOperation[EffectiveReadingProfile](
        "reading.conditional", ExpansionKind.INTERNAL, execute_legacy)),
    primitives=(
        ROUTE.declare("iftrue", ConditionalRule("opener", "always_true", 0)),
        ROUTE.declare("iffalse", ConditionalRule("opener", "always_false", 0)),
        *(ROUTE.declare(name, ConditionalRule("opener", "deferred", 2, predicate)) for name, predicate in
          (("if", "character_equal"), ("ifcat", "category_equal"), ("ifx", "meaning_equal"))),
        ROUTE.declare("ifdefined", ConditionalRule("opener", "deferred", 1, "defined")),
        ROUTE.declare("ifcsname", ConditionalRule("opener", "deferred", None, "name_defined")),
        ROUTE.declare("ifnum", ConditionalRule("opener", "deferred", None, "integer_compare")),
        ROUTE.declare("ifodd", ConditionalRule("opener", "deferred", None, "integer_odd")),
        ROUTE.declare("ifcase", ConditionalRule("opener", "deferred", None, "integer_case")),
        ROUTE.declare("ifeof", ConditionalRule("opener", "deferred", None, "stream_eof")),
        ROUTE.declare("ifpdfabsnum", ConditionalRule("opener", "deferred", None, "integer_abs_compare"), extension=True),
        *(ROUTE.declare(name, ConditionalRule("opener", "deferred")) for name in
          ("ifdim", "ifvoid", "ifhbox", "ifvbox")),
        *(ROUTE.declare(name, ConditionalRule("opener", "deferred", 0)) for name in
          ("ifvmode", "ifhmode", "ifmmode", "ifinner")),
        ROUTE.declare("else", ConditionalRule("alternative")),
        ROUTE.declare("or", ConditionalRule("case_alternative")),
        ROUTE.declare("fi", ConditionalRule("terminator"))),
)
