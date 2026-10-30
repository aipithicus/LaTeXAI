"""TeX82 code tables and case conversion; categories survive case mapping."""
from dataclasses import replace
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..quantities import InternalQuantity
from ..transactions import atomic, assignment_global
from ...reading.contracts import ReadingIssue, SourceCommand
from ...reading.tex_reader import TokenKind


LIMITS = {"lccode": 255, "uccode": 255, "sfcode": 32767, "mathcode": 32768, "delcode": 16777215}


def initial(table, char):
    if table == "lccode":
        return char + 32 if 65 <= char <= 90 else char if 97 <= char <= 122 else 0
    if table == "uccode":
        return char - 32 if 97 <= char <= 122 else char if 65 <= char <= 90 else 0
    if table == "sfcode":
        return 999 if 65 <= char <= 90 else 1000
    if table == "mathcode":
        return char + (0x7100 if 65 <= char <= 90 or 97 <= char <= 122 else 0x7000 if 48 <= char <= 57 else 0)
    return 0 if char == 46 else -1


def index(scanner):
    char = scanner.integer()
    if not 0 <= char <= 255:
        raise ReadingIssue("code_table_index", "This engine profile uses byte character codes")
    return char


def read(context, table, char):
    key = f"{table}:{char}"
    if key not in context.integer_parameters.values and context.primitive_initial_state:
        return initial(table, char)
    return context.integer_parameters.read(key)


def value(scanner, meaning):
    return InternalQuantity("integer", read(scanner.host.context, meaning.operand, index(scanner)))


@atomic
def assign(host, opening, meaning):
    scanner = IntegerScanner(host)
    char = index(scanner)
    scanner.optional_equals()
    result = scanner.integer()
    if result > LIMITS[meaning.operand] or (result < 0 and meaning.operand != "delcode"):
        raise ReadingIssue("code_table_value", "Code table value is outside TeX's range")
    scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    key = f"{meaning.operand}:{char}"
    host.context.integer_parameters.assign(key, result, span, global_=assignment_global(host))
    return SourceCommand(span, opening.token.value, "integer_parameter_assignment",
                         metadata={"parameter": key, "value": result, "trailing_control_word": scanner.ends_control_word})


@atomic
def change_case(host, opening, meaning):
    from .conversions import group
    from ..expansion import ExpansionCursor
    from ..programs import evaluate, SETUP
    cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations, host=host)
    tokens = group(cursor)
    converted = []
    for token in tokens:
        if token.kind != TokenKind.CONTROL_SEQUENCE:
            char = ord(token.value)
            if char > 255:
                raise ReadingIssue("code_table_index", "Case conversion requires byte character codes")
            replacement = read(host.context, meaning.operand, char)
            if replacement:
                token = replace(token, value=chr(replacement), transformed=True)
        converted.append(token)
    span = host.reader.source_span(opening.span.start, host.reader.position)
    if hasattr(host, "insert_tokens"):
        host.insert_tokens(tuple(converted), span)
    else:
        evaluate(host, tuple(converted), span, policy=SETUP)
    return SourceCommand(span, opening.token.value, "state_transformation")


ASSIGN = PrimitiveOperation("code_table.assign", ExpansionKind.UNEXPANDABLE, assign, value,
    operand_type=str, accepted_prefixes=frozenset({"global"}))
CASE = PrimitiveOperation("code_table.case", ExpansionKind.UNEXPANDABLE, change_case, operand_type=str)
FAMILY = OperationFamily((ASSIGN, CASE), tuple(ASSIGN.declare(k, k) for k in LIMITS) +
    (CASE.declare("lowercase", "lccode"), CASE.declare("uppercase", "uccode")))
