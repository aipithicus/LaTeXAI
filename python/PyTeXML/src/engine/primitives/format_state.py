"""Format-owner requests and store-only initialization data.

No filesystem writes or terminal interactions occur in primitive handlers.
The format owner records diagnostics, resolves input and publishes a dump.
"""
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..expansion import ExpansionCursor, TokenListInsertion
from ..integers import IntegerScanner
from ..transactions import atomic
from ..token_text import token_text
from ...reading.contracts import ReadingIssue, SourceCommand, ScannedArgument
from ...reading.token_cursor import TokenCursor
from .conversions import group, characters


def expanded_group(host):
    cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations, host=host)
    tokens = tuple(group(cursor))
    if cursor.pending:
        raise ReadingIssue("expansion_continuation", "Group leaves pending expansion input")
    anchor = host.reader.source_span(host.reader.position, host.reader.position)
    source = TokenCursor(ScannedArgument("message", anchor, ()), "", host.context)
    cursor = ExpansionCursor(source, host.context, host.knowledge, host.operations, host=host)
    cursor.push(tokens)
    result = []
    while (token := cursor.next_expanded(copy_token_lists=True)) is not None:
        result.extend(token.tokens if isinstance(token, TokenListInsertion) else (token,))
    return tuple(result)


@atomic
def message(host, opening, meaning):
    tokens = expanded_group(host)
    text = "".join(token_text(t, host.context, double_parameters=True) for t in tokens)
    # Diagnostics are transactional data until an owning runner publishes them.
    cells = host.context.state_cells
    previous = cells.read("format_messages") if "format_messages" in cells.values else ()
    cells.assign("format_messages", (*previous, text), opening.span, global_=True)
    return SourceCommand(host.reader.source_span(opening.span.start, host.reader.position), opening.token.value,
                         "format_message", metadata={"text": text, "stream": None})


@atomic
def write(host, opening, meaning):
    if getattr(host, "content", None) is not None:
        from .content_events import write as content_write
        return content_write(host, opening, meaning)
    if not getattr(host, "immediate_write", False):
        raise ReadingIssue("deferred_write", "Deferred write requires a shipout consumer")
    scanner = IntegerScanner(host)
    index = scanner.integer()
    scanner.finish()
    if index not in {-1, 16, 17}:
        raise ReadingIssue("output_stream", "Only terminal/log diagnostic writes are owned here")
    command = message(host, opening, meaning)
    command.metadata["stream"] = index
    return command


def immediate(host, opening, meaning):
    scanner = IntegerScanner(host)
    token = scanner._nonspace()
    resolved = scanner._meaning(token) if token is not None else None
    if not isinstance(resolved, tuple) or resolved[1].operation != "format.write":
        raise ReadingIssue("immediate_operation", "This consumer supports immediate write diagnostics")
    scanner.finish()
    host.immediate_write = True
    try:
        return write(host, opening, resolved[1])
    finally:
        host.immediate_write = False


def jobname(cursor, token, meaning):
    characters(cursor, cursor.context.state_cells.read("jobname"), token.span)


@atomic
def store_data(host, opening, meaning):
    tokens = expanded_group(host)
    language = host.context.integer_parameters.read("language")
    key = f"{meaning.operand}:{language}"
    previous = host.context.state_cells.read(key) if key in host.context.state_cells.values else ()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.state_cells.assign(key, (*previous, tokens), span, global_=True)
    return SourceCommand(span, opening.token.value, "format_data")


def dump(host, opening, meaning):
    if host.context.scope_depth or host._conditionals or host.context.after_assignment is not None:
        raise ReadingIssue("format_dump_state", "Dump requires balanced scopes and settled token scheduling")
    return SourceCommand(opening.span, opening.token.value, "format_dump")


def end(host, opening, meaning):
    if host.context.scope_depth or host._conditionals:
        raise ReadingIssue("format_end_state", "End requires settled scopes and conditionals")
    return SourceCommand(opening.span, opening.token.value, "format_end")


@atomic
def input_file(host, opening, meaning):
    from .read_streams import filename
    scanner = IntegerScanner(host)
    name = filename(scanner)
    scanner.finish()
    return SourceCommand(host.reader.source_span(opening.span.start, host.reader.position), opening.token.value,
                         "format_input", metadata={"filename": name})


MESSAGE = PrimitiveOperation("format.message", ExpansionKind.UNEXPANDABLE, message, operand_type=type(None))
WRITE = PrimitiveOperation("format.write", ExpansionKind.UNEXPANDABLE, write, operand_type=type(None))
IMMEDIATE = PrimitiveOperation("format.immediate", ExpansionKind.UNEXPANDABLE, immediate, operand_type=type(None))
JOB = PrimitiveOperation("format.jobname", ExpansionKind.EXPANDABLE, expansion=jobname, operand_type=type(None))
DATA = PrimitiveOperation("format.data", ExpansionKind.UNEXPANDABLE, store_data, operand_type=str)
DUMP = PrimitiveOperation("format.dump", ExpansionKind.UNEXPANDABLE, dump, operand_type=type(None))
# The format owner installs native input. The document baseline has a LaTeX
# input wrapper whose braced-file/return protocol remains owned by preparation.
INPUT = PrimitiveOperation("format.input", ExpansionKind.EXPANDABLE, input_file, operand_type=type(None),
                           expansion_unavailable=True)
END = PrimitiveOperation("format.end", ExpansionKind.UNEXPANDABLE, end, operand_type=type(None))
FAMILY = OperationFamily((MESSAGE, WRITE, IMMEDIATE, JOB, DATA, DUMP, INPUT, END),
    (MESSAGE.declare("message", None), WRITE.declare("write", None), IMMEDIATE.declare("immediate", None),
     JOB.declare("jobname", None), DUMP.declare("dump", None),
     DATA.declare("patterns", "patterns"), DATA.declare("hyphenation", "hyphenation")))
