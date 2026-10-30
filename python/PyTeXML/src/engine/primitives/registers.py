"""Typed registers and parameters share scanning, arithmetic and scoped writes."""
from dataclasses import dataclass
from ..integers import IntegerScanner
from ..dimensions import Glue, checked, dimension as scan_dimension, glue, trunc_div
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ..quantities import InternalQuantity
from ..transactions import atomic, assignment_global
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.contracts import ReadingIssue, SourceCommand


@dataclass(frozen=True)
class Register:
    kind: str
    index: int | None = None
    parameter: str | None = None


def cell(scanner, operand):
    if operand.parameter is not None:
        return operand.parameter
    index = scanner.integer() if operand.index is None else operand.index
    if not 0 <= index <= 32767:
        raise ReadingIssue("register_index", "Register index is outside the e-TeX range")
    return f"{operand.kind}:{index}"


def read_cell(scanner, key, kind="count"):
    context = scanner.host.context
    if kind == "toks":
        return context.token_registers.read(key)
    store = context.state_cells if kind in {"skip", "muskip"} else context.integer_parameters
    if key not in store.values:
        if not context.primitive_initial_state:
            raise ReadingIssue("unavailable_integer", "Register has no established initial value")
        return store.initial(Glue()) if kind in {"skip", "muskip"} else 0
    return store.read(key)


def value(scanner, meaning):
    kind = meaning.operand.kind
    return InternalQuantity({"count": "integer", "dimen": "dimension", "skip": "glue",
                             "muskip": "muglue", "toks": "tokens"}[kind],
                            read_cell(scanner, cell(scanner, meaning.operand), kind))


def dimension(scanner):
    return scan_dimension(scanner)[0]


def scan_value(scanner, kind):
    if kind == "count":
        return scanner.integer()
    if kind == "dimen":
        return dimension(scanner)
    if kind in {"skip", "muskip"}:
        return glue(scanner, mu=kind == "muskip")
    from .conversions import group, is_opening_group
    token = scanner._nonspace()
    if is_opening_group(scanner.reader, token):
        scanner.reader.unread_token(token)
        return tuple(group(scanner.reader))
    if token is not None:
        quantity = scanner.internal(token)
        if quantity.kind == "tokens":
            return quantity.value
    raise ReadingIssue("token_register_assignment", "Expected a group or token register")


def publish(host, opening, scanner, key, kind, result):
    scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    store = (host.context.token_registers if kind == "toks" else
             host.context.state_cells if kind in {"skip", "muskip"} else host.context.integer_parameters)
    store.assign(key, result, span, global_=assignment_global(host))
    if key == "endlinechar":
        host.context.assign_endlinechar(result, global_=assignment_global(host))
        host.reader.endline_char = result
    return SourceCommand(span, opening.token.value,
                         "token_register_assignment" if kind == "toks" else "integer_parameter_assignment",
                         metadata={"parameter": key, "value": result,
                                   "trailing_control_word": scanner.ends_control_word})


@atomic
def arithmetic(host, opening, meaning):
    scanner = IntegerScanner(host)
    token = scanner._nonspace()
    resolved = scanner._meaning(token) if token is not None else None
    if not isinstance(resolved, tuple):
        raise ReadingIssue("arithmetic_target", "Arithmetic requires an assignable register")
    target = resolved[1]
    if target.operation == "register.assign" and target.operand.kind != "toks":
        key, kind = cell(scanner, target.operand), target.operand.kind
        previous = read_cell(scanner, key, kind)
    elif target.operation == "parameter.assign_integer":
        key, kind = target.operand, "count"
        from .parameters import internal_value
        previous = internal_value(scanner, target).value
    else:
        raise ReadingIssue("arithmetic_target", "Arithmetic requires a numeric register or parameter")
    scanner.keyword("by")
    if meaning.operand == "advance":
        amount = scan_value(scanner, kind)
        result = previous.plus(amount) if isinstance(previous, Glue) else previous + amount
    else:
        amount = scanner.integer()
        if isinstance(previous, Glue):
            result = previous.scaled(amount, divide=meaning.operand == "divide")
        else:
            result = trunc_div(previous, amount) if meaning.operand == "divide" else previous * amount
    if not isinstance(result, Glue):
        checked(result, 2147483647 if kind == "count" else 1073741823)
    return publish(host, opening, scanner, key, kind, result)


@atomic
def assign(host, opening, meaning):
    scanner = IntegerScanner(host)
    key = cell(scanner, meaning.operand)
    scanner.optional_equals()
    return publish(host, opening, scanner, key, meaning.operand.kind, scan_value(scanner, meaning.operand.kind))


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


DIMENSIONS = "parindent mathsurround lineskiplimit hsize vsize maxdepth splitmaxdepth boxmaxdepth hfuzz vfuzz delimitershortfall nulldelimiterspace scriptspace predisplaysize displaywidth displayindent overfullrule hangindent hoffset voffset emergencystretch".split()
GLUES = "lineskip baselineskip parskip abovedisplayskip belowdisplayskip abovedisplayshortskip belowdisplayshortskip leftskip rightskip topskip splittopskip tabskip spaceskip xspaceskip parfillskip".split()
MUGLUES = "thinmuskip medmuskip thickmuskip".split()
TOKENS = "output everypar everymath everydisplay everyhbox everyvbox everyjob everycr errhelp".split()

ASSIGN = PrimitiveOperation("register.assign", ExpansionKind.UNEXPANDABLE, assign, value,
    operand_type=Register, accepted_prefixes=frozenset({"global"}))
DEFINE = PrimitiveOperation("register.define", ExpansionKind.UNEXPANDABLE, define,
    operand_type=str, accepted_prefixes=frozenset({"global"}))
ARITHMETIC = PrimitiveOperation("register.arithmetic", ExpansionKind.UNEXPANDABLE, arithmetic,
    operand_type=str, accepted_prefixes=frozenset({"global"}))
KINDS = ("count", "dimen", "skip", "muskip", "toks")
FAMILY = OperationFamily((ASSIGN, DEFINE, ARITHMETIC), tuple(ASSIGN.declare(k, Register(k)) for k in KINDS) +
    tuple(DEFINE.declare(k + "def", k) for k in KINDS) +
    tuple(ARITHMETIC.declare(name, name) for name in ("advance", "multiply", "divide")) +
    tuple(ASSIGN.declare(name, Register(kind, parameter=name)) for kind, names in
          (("dimen", DIMENSIONS), ("skip", GLUES), ("muskip", MUGLUES), ("toks", TOKENS)) for name in names))
