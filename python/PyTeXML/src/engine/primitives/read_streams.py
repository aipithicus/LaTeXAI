"""read/ifeof and explicit stream lifecycle, using TeX82 read_toks semantics."""
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..transactions import atomic, assignment_global
from ...reading.contracts import ReadingIssue, SourceCommand, TokenListMeaning
from ...reading.tex_reader import CatCode, TokenKind, InvalidCharacterError


def stream_number(scanner):
    index = scanner.integer()
    if not 0 <= index <= 15:
        raise ReadingIssue("input_stream_index", "Input stream number must be in 0..15")
    return index


def filename(scanner):
    parts, quoted = [], False
    token = scanner._nonspace()
    while token is not None:
        if token.kind != TokenKind.CHARACTER or token.catcode not in {CatCode.LETTER, CatCode.OTHER, CatCode.SPACE}:
            scanner.reader.unread_token(token)
            break
        if token.value == '"':
            quoted = not quoted
        elif token.catcode == CatCode.SPACE and not quoted:
            break
        else:
            parts.append(token.value)
        token = scanner._next()
    if quoted or not parts:
        raise ReadingIssue("input_filename", "Openin requires a complete filename")
    return "".join(parts)


@atomic
def lifecycle(host, opening, meaning):
    scanner = IntegerScanner(host)
    index = stream_number(scanner)
    if meaning.operand == "open":
        scanner.optional_equals()
        name = filename(scanner)
        scanner.finish()
        host.context.read_streams.open(index, name)
    else:
        scanner.finish()
        host.context.read_streams.close(index)
    span = host.reader.source_span(opening.span.start, host.reader.position)
    return SourceCommand(span, opening.token.value, "input_stream_assignment",
                         metadata={"stream": index, "trailing_control_word": scanner.ends_control_word})


@atomic
def read(host, opening, meaning):
    scanner = IntegerScanner(host)
    index = scanner.integer()
    if not scanner.keyword("to"):
        raise ReadingIssue("read_target", "Read requires the keyword to")
    target = scanner.reader.next_token()
    while target is not None and target.catcode == CatCode.SPACE:
        target = scanner.reader.next_token()
    if target is None or target.kind not in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER}:
        raise ReadingIssue("read_target", "Read requires an unexpanded control sequence target")
    scanner.finish()
    if not 0 <= index <= 15:
        raise ReadingIssue("terminal_input", "This read stream number requires terminal input")
    try:
        tokens = host.context.read_streams.read(index, host.context)
    except InvalidCharacterError as error:
        # The command belongs to the caller's source; its failure cause belongs
        # to the supplied file. Do not fabricate a caller span from file offsets.
        raise ReadingIssue("invalid_read_character", str(error), causes=(error.span,)) from error
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.record_meaning(target.value, TokenListMeaning(span, tokens), target.kind,
                                global_=assignment_global(host))
    return SourceCommand(span, opening.token.value, "meaning_assignment",
                         metadata={"donor_resolved": True, "trailing_control_word": target.control_word,
                                   "stream": index})


LIFECYCLE = PrimitiveOperation("input.stream", ExpansionKind.UNEXPANDABLE, lifecycle, operand_type=str)
READ = PrimitiveOperation("input.read", ExpansionKind.UNEXPANDABLE, read, operand_type=type(None),
                          accepted_prefixes=frozenset({"global"}))
FAMILY = OperationFamily((LIFECYCLE, READ), (LIFECYCLE.declare("openin", "open"),
    LIFECYCLE.declare("closein", "close"), READ.declare("read", None)))
