"""Typed count/dimension cells and register aliases share the scope journal."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ..transactions import atomic, assignment_global
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.contracts import ReadingIssue, SourceCommand
from ...reading.tex_reader import CatCode


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
def assign(host, opening, meaning):
    scanner = IntegerScanner(host)
    key = cell(scanner, meaning.operand)
    scanner.optional_equals()
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
FAMILY = OperationFamily((ASSIGN, DEFINE), tuple(ASSIGN.declare(k, Register(k)) for k in ("count", "dimen")) +
    tuple(DEFINE.declare(k + "def", k) for k in ("count", "dimen")))
