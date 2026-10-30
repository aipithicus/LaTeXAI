"""Typed count/dimension cells and register aliases share the scope journal."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ..quantities import InternalQuantity
from ..transactions import atomic, assignment_global
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.contracts import ReadingIssue, SourceCommand
from ...reading.tex_reader import CatCode, TokenKind


@dataclass(frozen=True)
class Register:
    kind: str
    index: int | None = None


def cell(scanner, operand):
    index = scanner.integer() if operand.index is None else operand.index
    if not 0 <= index <= 32767:
        raise ReadingIssue("register_index", "Register index is outside the e-TeX range")
    return f"{operand.kind}:{index}"


def value(scanner, meaning):
    key = cell(scanner, meaning.operand)
    if meaning.operand.kind == "toks":
        return InternalQuantity("tokens", scanner.host.context.token_registers.read(key))
    return InternalQuantity("dimension" if meaning.operand.kind == "dimen" else "integer", read_cell(scanner, key))


def read_cell(scanner, key):
    if key not in scanner.host.context.integer_parameters.values:
        # A bounded primitive initial state initializes register cells to zero.
        if not getattr(scanner.host.context, "primitive_initial_state", False):
            raise ReadingIssue("unavailable_integer", "Register has no established initial value")
        return 0
    return scanner.host.context.integer_parameters.read(key)


def dimension(scanner):
    # Unit scanning is deliberately capability-scoped; layout/font-relative units
    # require services outside this source-bootstrap boundary.
    parts, sign = [], 1
    token = scanner.reader.next_expanded()
    while token is not None:
        if token.catcode == CatCode.SPACE:
            pass
        elif token.catcode == CatCode.OTHER and token.value in "+-":
            if token.value == "-":
                sign = -sign
        else:
            break
        token = scanner.reader.next_expanded()
    if token is not None and token.kind != TokenKind.CHARACTER:
        quantity = scanner.internal(token)
        if quantity.kind == "dimension":
            return sign * quantity.value
        if quantity.kind != "integer":
            raise ReadingIssue("dimension_value", "Dimension requires a numeric internal quantity")
        parts.append(str(quantity.value))
        token = scanner.reader.next_expanded()
    if not parts:
        while token is not None and token.value in "0123456789.," and token.catcode == CatCode.OTHER:
            parts.append(token.value)
            token = scanner.reader.next_expanded()
    while token is not None and token.catcode == CatCode.SPACE:
        token = scanner.reader.next_expanded()
    unit = ""
    for _ in range(2):
        if token is None or token.catcode not in {CatCode.LETTER, CatCode.OTHER} or len(token.value) != 1:
            raise ReadingIssue("dimension_unit", "Missing dimension unit")
        unit += token.value.lower()
        token = scanner.reader.next_expanded()
    if token is not None and token.catcode != CatCode.SPACE:
        scanner.reader.unread_token(token)
    if unit not in {"pt", "sp"}:
        raise ReadingIssue("dimension_unit", "Only explicit pt and sp units are established")
    try:
        number = Decimal("".join(parts).replace(",", "."))
        scaled = sign * (int(number) if unit == "sp" else
                         int((number * 65536).to_integral_value(rounding=ROUND_HALF_UP)))
    except Exception as error:
        raise ReadingIssue("dimension_value", "Invalid explicit dimension") from error
    if abs(scaled) > 1073741823:
        raise ReadingIssue("dimension_value", "Dimension exceeds TeX's range")
    return scaled


@atomic
def advance(host, opening, meaning):
    scanner = IntegerScanner(host)
    token = scanner._nonspace()
    if token is None:
        raise ReadingIssue("arithmetic_target", "Advance requires an assignable register")
    resolved = scanner._meaning(token)
    if not isinstance(resolved, tuple):
        raise ReadingIssue("arithmetic_target", "Advance requires an assignable register")
    target = resolved[1]
    if target.operation == "register.assign":
        if target.operand.kind == "toks":
            raise ReadingIssue("arithmetic_target", "Token registers do not support arithmetic")
        key = cell(scanner, target.operand)
        kind = target.operand.kind
        previous = read_cell(scanner, key)
    elif target.operation == "parameter.assign_integer":
        key, kind = target.operand, "count"
        previous = (host.context.endlinechar if key == "endlinechar" else
                    host.context.integer_parameters.read(key))
    else:
        raise ReadingIssue("arithmetic_target", "Advance requires an integer or dimension register")
    scanner.keyword("by")
    increment = scanner.integer() if kind == "count" else dimension(scanner)
    result = previous + increment
    if abs(result) > (2147483647 if kind == "count" else 1073741823):
        raise ReadingIssue("arithmetic_overflow", "Advance exceeds the register range")
    scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    global_ = assignment_global(host)
    host.context.integer_parameters.assign(key, result, span, global_=global_)
    if key == "endlinechar":
        host.context.assign_endlinechar(result, global_=global_)
        host.reader.endline_char = result
    return SourceCommand(span, opening.token.value, "integer_parameter_assignment",
                         metadata={"parameter": key, "value": result,
                                   "trailing_control_word": scanner.ends_control_word})


@atomic
def assign(host, opening, meaning):
    scanner = IntegerScanner(host)
    key = cell(scanner, meaning.operand)
    scanner.optional_equals()
    if meaning.operand.kind == "toks":
        from .conversions import group, is_opening_group
        token = scanner._nonspace()
        if is_opening_group(scanner.reader, token):
            scanner.reader.unread_token(token)
            result = tuple(group(scanner.reader))
        elif token is not None:
            quantity = scanner.internal(token)
            if quantity.kind != "tokens":
                raise ReadingIssue("token_register_assignment", "Expected a group or token register")
            result = quantity.value
        else:
            raise ReadingIssue("token_register_assignment", "Missing token register contents")
        scanner.finish()
        span = host.reader.source_span(opening.span.start, host.reader.position)
        host.context.token_registers.assign(key, result, span, global_=assignment_global(host))
        return SourceCommand(span, opening.token.value, "token_register_assignment",
                             metadata={"register": key, "trailing_control_word": scanner.ends_control_word})
    result = scanner.integer() if meaning.operand.kind == "count" else dimension(scanner)
    scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.integer_parameters.assign(key, result, span, global_=assignment_global(host))
    return SourceCommand(span, opening.token.value, "integer_parameter_assignment",
                         metadata={"parameter": key, "value": result,
                                   "trailing_control_word": scanner.ends_control_word})


@atomic
def define(host, opening, meaning):
    target = AssignmentScanner(host.reader, host.context).target()
    scanner = IntegerScanner(host)
    scanner.optional_equals()
    index = scanner.integer()
    if not 0 <= index <= 32767:
        raise ReadingIssue("register_index", "Register index is outside the e-TeX range")
    scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.record_meaning(target.value, PrimitiveMeaning("register.assign", Register(meaning.operand, index), span),
                                target.kind, global_=assignment_global(host))
    return SourceCommand(span, opening.token.value, "meaning_assignment",
                         metadata={"donor_resolved": True, "trailing_control_word": scanner.ends_control_word})


ASSIGN = PrimitiveOperation("register.assign", ExpansionKind.UNEXPANDABLE, assign, value,
    operand_type=Register, accepted_prefixes=frozenset({"global"}))
DEFINE = PrimitiveOperation("register.define", ExpansionKind.UNEXPANDABLE, define,
    operand_type=str, accepted_prefixes=frozenset({"global"}))
ADVANCE = PrimitiveOperation("register.advance", ExpansionKind.UNEXPANDABLE, advance,
    operand_type=type(None), accepted_prefixes=frozenset({"global"}))
FAMILY = OperationFamily((ASSIGN, DEFINE, ADVANCE), tuple(ASSIGN.declare(k, Register(k)) for k in ("count", "dimen", "toks")) +
    tuple(DEFINE.declare(k + "def", k) for k in ("count", "dimen", "toks")) + (ADVANCE.declare("advance", None),))
