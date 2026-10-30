"""Live, finite halign templates and cells; no column measurement or repetition."""
from ..content import Frame
from ..dimensions import Glue, dimension
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from .content import owner, result
from .conversions import is_opening_group
from ...reading.contracts import ReadingIssue
from ...reading.tex_reader import CatCode, TokenKind


def command(host, token):
    meaning = host.context.resolve_meaning(host.knowledge, token.value, token.kind)
    if isinstance(meaning, PrimitiveMeaning) and meaning.uncertain is None and meaning.operation == "content.alignment":
        return meaning.operand
    return None


def start(host, opening):
    content, scanner = owner(host), IntegerScanner(host)
    content.paragraph(host, opening.span)
    if content.frame.mode != "v":
        raise ReadingIssue("content_mode", "This alignment consumer requires vertical mode")
    spec = "to" if scanner.keyword("to") else "spread" if scanner.keyword("spread") else None
    size = dimension(scanner)[0] if spec else None
    if not is_opening_group(scanner.reader, scanner._nonspace()):
        raise ReadingIssue("alignment_preamble", "halign requires an opening group")
    scanner.finish()
    # TeX scans unexpanded templates before executing cells. This finite form
    # requires one # per column and rejects assignments/repetition in a preamble.
    columns, parts, depth = [], [], 0
    while (token := host.reader.next_token()) is not None:
        if depth == 0 and (token.catcode == CatCode.ALIGNMENT_TAB or command(host, token) == "cr"):
            slots = [n for n, t in enumerate(parts) if t.catcode == CatCode.PARAMETER]
            if len(slots) != 1:
                raise ReadingIssue("alignment_preamble", "Each finite template requires exactly one parameter marker")
            n = slots[0]
            columns.append((tuple(parts[:n]), tuple(parts[n + 1:])))
            parts = []
            if command(host, token) == "cr":
                break
            continue
        if token.kind != TokenKind.CHARACTER:
            meaning = host.context.resolve_meaning(host.knowledge, token.value, token.kind)
            if isinstance(meaning, PrimitiveMeaning) and (meaning.operation == "register.assign" and meaning.operand.parameter == "tabskip" or command(host, token) == "span"):
                raise ReadingIssue("alignment_preamble", "Preamble tabskip assignments and span expansion require a richer preamble scanner")
        depth += (token.catcode == CatCode.BEGIN_GROUP) - (token.catcode == CatCode.END_GROUP)
        if depth < 0:
            raise ReadingIssue("alignment_preamble", "Alignment closed before its preamble terminator")
        parts.append(token)
    else:
        raise ReadingIssue("alignment_preamble", "EOF in alignment preamble")
    cells = host.context.state_cells
    tabskip = cells.read("tabskip") if "tabskip" in cells.values else cells.initial(Glue())
    host.begin_group("content:alignment", opening.span)
    content.frames.append(Frame("alignment", "a", opening.span,
        info={"columns": tuple(columns), "spec": spec, "size": size, "tabskip": tabskip}))
    content.hook(host, "everycr", opening.span)


def before_event(host, event):
    """Called before meaning dispatch when an alignment awaits its next row/cell."""
    content, token = owner(host), event.token
    if content.frame.kind not in {"alignment", "row"}:
        return False
    if token.catcode == CatCode.SPACE:
        return True
    name = command(host, token)
    if content.frame.kind == "alignment":
        if token.catcode == CatCode.END_GROUP:
            content.close(host, event.span)
            return True
        if name in {"noalign", "crcr"}:
            return False
        content.frames.append(Frame("row", "a", event.span))
    alignment = content.frames[-2]
    column = len(content.frame.nodes)
    if column >= len(alignment.info["columns"]):
        raise ReadingIssue("alignment_columns", "Row exceeds the finite preamble")
    template = alignment.info["columns"][column]
    host.begin_group("content:cell", event.span)
    content.frames.append(Frame("cell", "h", event.span, info={"after": () if name == "omit" else template[1], "omit": name == "omit"}))
    if name != "omit" and template[0]:
        host.insert_tokens(template[0], event.span)
    return name == "omit"


def end_cell(host, span, *, row):
    content = owner(host)
    cells = [f for f in content.frames if f.kind == "cell"]
    groups = [i for i, g in enumerate(host._groups) if g.kind == "content:cell"]
    if not cells or not groups or any(g.kind not in {"content:math", "content:left", "semi_simple"}
                                     for g in host._groups[groups[-1] + 1:]):
        raise ReadingIssue("alignment_cell", "Alignment delimiter inside an unfinished cell group")
    tail = cells[-1].info["after"]
    if tail:
        host.insert_tokens(tail, span)
    if content.frame.kind != "cell" or host._groups[-1].kind != "content:cell":
        raise ReadingIssue("alignment_template", "Template did not settle its cell content")
    after = host.end_group("content:cell", deliver=False)
    cell = content.frames.pop()
    content.emit(content.node(host, "cell", cell.span, cell.nodes, omit=cell.info["omit"], width=None))
    if row:
        frame = content.frames.pop()
        content.emit(content.node(host, "row", frame.span, frame.nodes))
        content.hook(host, "everycr", span)
    if after:
        host.insert_tokens(after, span)


def execute(host, opening, meaning):
    content, name = owner(host), meaning.operand
    if name == "halign":
        start(host, opening)
    elif name in {"cr", "crcr"}:
        if not (name == "crcr" and content.frame.kind == "alignment"):
            end_cell(host, opening.span, row=True)
    elif name == "noalign":
        if content.frame.kind != "alignment":
            raise ReadingIssue("alignment_noalign", "noalign must appear between rows")
        scanner = IntegerScanner(host)
        if not is_opening_group(scanner.reader, scanner._nonspace()):
            raise ReadingIssue("alignment_noalign", "noalign requires an opening group")
        scanner.finish()
        host.begin_group("content:noalign", opening.span)
        content.frames.append(Frame("noalign", "v", opening.span))
    else:
        raise ReadingIssue("alignment_context", "omit/span is unsupported at this alignment position")
    return result(host, opening)


ALIGN = PrimitiveOperation("content.alignment", ExpansionKind.UNEXPANDABLE, execute, operand_type=str)
FAMILY = OperationFamily((ALIGN,), tuple(ALIGN.declare(k, k) for k in "halign cr crcr noalign omit span".split()))
