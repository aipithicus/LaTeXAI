"""Capture issued insertions, marks and writes without running an output routine."""
from ..content import Frame
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from .content import owner, result
from .conversions import group, is_opening_group
from .format_state import expanded_group
from ...reading.contracts import ReadingIssue


def token_nodes(content, host, tokens):
    return tuple(content.node(host, "token", t.span, value=t.value, token_kind=t.kind.value,
                              catcode=int(t.catcode) if t.catcode is not None else None) for t in tokens)


def write(host, opening, meaning):
    content, scanner = owner(host), IntegerScanner(host)
    number = scanner.integer()
    scanner.finish()
    immediate = getattr(host, "immediate_write", False)
    if immediate:
        tokens = expanded_group(host)
    else:
        scanner = IntegerScanner(host)
        tokens = group(scanner.reader)
        scanner.finish()
    content.emit(content.node(host, "write", opening.span, token_nodes(content, host, tokens), stream=number,
                              timing="immediate" if immediate else "shipout",
                              execution="issued", expansion="captured" if immediate else "deferred"))
    return result(host, opening)


def execute(host, opening, meaning):
    content, command, span = owner(host), meaning.operand, opening.span
    scanner = IntegerScanner(host)
    if command in {"insert", "vadjust"}:
        if command == "vadjust" and content.frame.mode == "v":
            raise ReadingIssue("content_mode", "vadjust requires horizontal or math mode")
        number = scanner.integer() if command == "insert" else None
        if number is not None and not 0 <= number <= 254:
            raise ReadingIssue("insert_class", "Insertion class must lie in 0..254")
        if not is_opening_group(scanner.reader, scanner._nonspace()):
            raise ReadingIssue("content_group", "Insertion requires an opening group")
        scanner.finish()
        host.begin_group("content:" + command, span)
        content.frames.append(Frame(command, "v", span, info={"class_": number, "execution": "issued"}))
    else:
        number = scanner.integer() if command == "marks" else 0
        if not 0 <= number <= 32767:
            raise ReadingIssue("mark_class", "Mark class is outside the e-TeX range")
        scanner.finish()
        tokens = expanded_group(host)
        content.emit(content.node(host, "special" if command == "special" else "mark", span,
                                  token_nodes(content, host, tokens), class_=number, execution="issued"))
    return result(host, opening)


EFFECT = PrimitiveOperation("content.effect", ExpansionKind.UNEXPANDABLE, execute, operand_type=str)
FAMILY = OperationFamily((EFFECT,), tuple(EFFECT.declare(k, k) for k in "insert vadjust mark marks special".split()))
