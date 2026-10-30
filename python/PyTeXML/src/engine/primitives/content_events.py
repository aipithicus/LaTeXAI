"""Capture issued insertions, marks and writes without running an output routine."""
from ..content import Frame
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from .content import owner, result
from .conversions import group, is_opening_group
from .format_state import expanded_group
from ...reading.contracts import ReadingIssue
from ..transactions import atomic


def token_nodes(content, host, tokens):
    return tuple(content.node(host, "token", t.span, value=t.value, token_kind=t.kind.value,
                              catcode=int(t.catcode) if t.catcode is not None else None) for t in tokens)


def write(host, opening, meaning):
    content, scanner = owner(host), IntegerScanner(host)
    number = scanner.integer()
    if number == 18:
        raise ReadingIssue("shell_write", "This content consumer does not execute shell-write requests")
    scanner.finish()
    immediate = getattr(host, "immediate_write", False)
    if immediate:
        tokens = expanded_group(host)
    else:
        scanner = IntegerScanner(host)
        tokens = group(scanner.reader)
        scanner.finish()
    node = content.node(host, "write", opening.span, token_nodes(content, host, tokens), stream=number,
                              payload=tokens, write_id=content.lifecycle.identifier(),
                              timing="immediate" if immediate else "shipout",
                              execution="issued", expansion="captured" if immediate else "deferred")
    content.emit(node)
    if immediate:
        content.lifecycle.write(content, host, node)
    return result(host, opening)


@atomic
def output_stream(host, opening, meaning):
    from .read_streams import filename
    from pathlib import PurePosixPath
    content, scanner = owner(host), IntegerScanner(host)
    number = scanner.integer()
    if not 0 <= number <= 15:
        raise ReadingIssue("output_stream_index", "Output stream number must lie in 0..15")
    name = None
    if meaning.operand == "open":
        scanner.optional_equals()
        name = filename(scanner)
        if not PurePosixPath(name).suffix:
            name += ".tex"
    scanner.finish()
    immediate = getattr(host, "immediate_write", False)
    node = content.node(host, "output_stream", opening.span, stream=number, filename=name,
                        operation=meaning.operand, timing="immediate" if immediate else "shipout")
    content.emit(node)
    if immediate:
        content.lifecycle.stream(node)
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
STREAM = PrimitiveOperation("content.output_stream", ExpansionKind.UNEXPANDABLE, output_stream, operand_type=str)
FAMILY = OperationFamily((EFFECT, STREAM), tuple(EFFECT.declare(k, k) for k in "insert vadjust mark marks special".split()) +
                        (STREAM.declare("openout", "open"), STREAM.declare("closeout", "close")))
