"""Native content operations. Without a list consumer they remain boundaries."""
from dataclasses import replace

from ..content import Frame
from ..dimensions import Glue, dimension, glue
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ..state_cells import Cell
from ..quantities import InternalQuantity
from ..transactions import assignment_global
from .conversions import is_opening_group, group
from ...reading.contracts import ReadingIssue, SourceCommand
from ...reading.tex_reader import CatCode, TokenKind


def owner(host):
    content = getattr(host, "content", None)
    if content is None:
        raise ReadingIssue("content_consumer", "This operation requires a content list consumer")
    return content


def result(host, opening):
    return SourceCommand(host.reader.source_span(opening.span.start, host.reader.position),
                         opening.token.value, "content")


def index(scanner):
    value = scanner.integer()
    if not 0 <= value <= 32767:
        raise ReadingIssue("register_index", "Box register index is outside the e-TeX range")
    return value


def box_operand(host, scanner, span, target):
    token = scanner._nonspace()
    while token is not None:
        meaning = host.context.resolve_meaning(host.knowledge, token.value, token.kind)
        if isinstance(meaning, PrimitiveMeaning) and meaning.uncertain is None:
            if meaning.operation == "content.box":
                return make_box(host, scanner, span, meaning.operand, target)
            if meaning.operation == "expansion.relax":
                token = scanner._nonspace()
                continue
        break
    raise ReadingIssue("box_operand", "Expected an implemented box constructor or register")


def make_box(host, scanner, span, kind, target):
    content = owner(host)
    if kind in {"box", "copy"}:
        number = index(scanner)
        scanner.finish()
        content.deliver_box(host, content.read_box(host, number, take=kind == "box"), target, span)
        return
    if kind == "lastbox":
        scanner.finish()
        if content.frame.mode == "m" or content.frame.kind == "document":
            raise ReadingIssue("content_mode", "lastbox requires an internal non-math list")
        nodes = content.frame.nodes
        box = nodes.pop() if nodes and nodes[-1].kind in {"hbox", "vbox", "vtop"} else None
        if box is not None and box.get("shift") is not None:
            box = box.with_value("shift", 0)
        content.deliver_box(host, box, target, span)
        return
    spec = "to" if scanner.keyword("to") else "spread" if scanner.keyword("spread") else None
    size = dimension(scanner)[0] if spec else None
    if not is_opening_group(scanner.reader, scanner._nonspace()):
        raise ReadingIssue("box_group", "A box constructor requires an opening group")
    scanner.finish()
    host.begin_group("content:" + kind, span)
    content.frames.append(Frame(kind, "h" if kind == "hbox" else "v", span,
                                info={"spec": spec, "size": size, "target": target}))
    # TeX inserts afterassignment ahead of everyhbox/everyvbox, at entry to
    # the newly opened box, rather than after its eventual register publication.
    after = ()
    if target[0] == "register" and host.context.after_assignment is not None:
        token, host.context.after_assignment = host.context.after_assignment, None
        after = (token,)
    hook = host.context.token_registers.read("everyhbox" if kind == "hbox" else "everyvbox")
    if after or hook:
        from ..programs import evaluate, CONTENT
        evaluate(host, (*after, *hook), span, policy=CONTENT)


def box(host, opening, meaning):
    make_box(host, IntegerScanner(host), opening.span, meaning.operand, ("append",))
    return result(host, opening)


def set_box(host, opening, meaning):
    owner(host)
    scanner = IntegerScanner(host)
    number = index(scanner)
    scanner.optional_equals()
    box_operand(host, scanner, opening.span, ("register", number, assignment_global(host)))
    return result(host, opening)


def move_box(host, opening, meaning):
    content = owner(host)
    command, scanner = meaning.operand, IntegerScanner(host)
    if command == "shipout":
        target = ("shipout",)
    elif command in {"leaders", "cleaders", "xleaders"}:
        target = ("leaders", command)
    elif command == "vcenter":
        if content.frame.mode != "m":
            raise ReadingIssue("content_mode", "vcenter requires math mode")
        make_box(host, scanner, opening.span, "vbox", ("vcenter",))
        return result(host, opening)
    else:
        horizontal = command in {"raise", "lower"}
        if (content.frame.mode == "v") == horizontal:
            raise ReadingIssue("content_mode", "Box shift is incompatible with the current mode")
        amount = dimension(scanner)[0] * (-1 if command in {"raise", "moveleft"} else 1)
        target = ("append", amount)
    box_operand(host, scanner, opening.span, target)
    return result(host, opening)


def unbox(host, opening, meaning):
    content, scanner = owner(host), IntegerScanner(host)
    number = index(scanner)
    scanner.finish()
    horizontal = meaning.operand in {"unhbox", "unhcopy"}
    if horizontal:
        content.horizontal(host, opening.span)
    elif content.frame.kind == "paragraph":
        content.paragraph(host, opening.span)
    if content.frame.mode != ("h" if horizontal else "v"):
        raise ReadingIssue("content_mode", "Unboxing is incompatible with the current mode")
    node = content.read_box(host, number, take=meaning.operand.endswith("box"))
    if node is not None:
        if (node.kind == "hbox") != horizontal:
            raise ReadingIssue("box_kind", "Cannot unbox a list of the other orientation")
        run_id = content.work
        for child in node.children:
            if child.kind == "character":
                child = child.with_value("run", (opening.span, run_id, child.get("run")))
            content.emit(child)
    return result(host, opening)


def box_value(scanner, meaning):
    content = owner(scanner.host)
    node = content.read_box(scanner.host, index(scanner))
    value = node.get(meaning.operand) if node is not None else 0
    if value is None:
        raise ReadingIssue("unknown_box_dimension", "Box measurement requires layout not yet performed")
    return InternalQuantity("dimension", value)


def box_dimension(host, opening, meaning):
    content, scanner = owner(host), IntegerScanner(host)
    number = index(scanner)
    scanner.optional_equals()
    value = dimension(scanner)[0]
    scanner.finish()
    node = content.read_box(host, number)
    if node is not None:
        # Box dimensions mutate the current box without saving/restoring the
        # register. Existing save entries from setbox still restore normally.
        host.context.state_cells.values["box:" + str(number)] = Cell(node.with_value(meaning.operand, value), opening.span)
    return result(host, opening)


def finish_leaders(host, node, kind, span):
    scanner, content = IntegerScanner(host), owner(host)
    token = scanner._nonspace()
    meaning = host.context.resolve_meaning(host.knowledge, token.value, token.kind) if token else None
    expected = "vskip" if content.frame.mode == "v" else "hskip"
    if not isinstance(meaning, PrimitiveMeaning) or meaning.uncertain is not None or meaning.operation != "content.list" or meaning.operand != expected:
        raise ReadingIssue("leaders_glue", "Leaders require glue in the current list direction")
    amount = glue(scanner)
    scanner.finish()
    content.emit(content.node(host, "leaders", span, (node,), pattern=kind, glue=amount))


def list_operation(host, opening, meaning):
    if getattr(host, "content", None) is None and host.preparation and not host.program and meaning.operand in {"indent", "noindent"}:
        return SourceCommand(opening.span, opening.token.value, "opaque", metadata={"execution": "deferred_layout"})
    content, command = owner(host), meaning.operand
    scanner, span = IntegerScanner(host), opening.span
    if command == "char":
        code = scanner.integer()
        if not 0 <= code <= 255:
            raise ReadingIssue("content_character", "char requires a byte character code")
        scanner.finish()
        content.character(host, chr(code), span, explicit=True)
    elif command in {"indent", "noindent"}:
        if content.frame.mode == "m":
            raise ReadingIssue("content_mode", "Paragraph indentation in math mode")
        was_horizontal = content.frame.mode == "h"
        content.horizontal(host, span, indent=command == "indent")
        if command == "indent" and was_horizontal:
            from ..measurement import parameter
            content.emit(content.node(host, "indent", span, width=parameter(host.context, "parindent")))
    elif command == "space":
        content.space(host, span, explicit=True)
    elif command == "italic":
        if content.frame.mode != "h":
            raise ReadingIssue("content_mode", "Italic correction requires horizontal mode")
        if content.frame.nodes and content.frame.nodes[-1].kind == "character":
            from ..measurement import horizontal
            last = content.frame.nodes[-1]
            start = len(content.frame.nodes) - 1
            while start and content.frame.nodes[start - 1].kind == "character" and content.frame.nodes[start - 1].get("run") == last.get("run"):
                start -= 1
            shaped = horizontal(host.context, content.frame.nodes[start:]).glyphs
            width = None
            if shaped:
                font, run = shaped[-1]
                glyph = next((item[1] for item in reversed(run) if item[0] == "glyph"), None)
                if glyph is not None:
                    width = host.context.fonts.metrics(font).glyphs[glyph].italic
            if last.get("font") == "nullfont":
                width = 0
            content.emit(content.node(host, "italic_correction", span, width=width))
    elif command in {"unskip", "unkern", "unpenalty"}:
        if content.frame.kind == "document":
            raise ReadingIssue("outer_vertical_tail", "The outer vertical tail belongs to the unimplemented page builder")
        expected = {"unskip": {"glue", "space", "leaders"}, "unkern": {"kern", "italic_correction"}, "unpenalty": {"penalty"}}[command]
        if content.frame.nodes and content.frame.nodes[-1].kind in expected:
            content.frame.nodes.pop()
    elif command == "penalty":
        amount = scanner.integer()
        scanner.finish()
        content.emit(content.node(host, "penalty", span, value=amount))
    elif command in {"kern", "mkern"}:
        if command == "mkern" and content.frame.mode != "m":
            raise ReadingIssue("content_mode", "Math kern requires math mode")
        amount = dimension(scanner, mu=command == "mkern")[0]
        scanner.finish()
        content.emit(content.node(host, "kern", span, width=amount, mu=command == "mkern"))
    elif command in {"hrule", "vrule"}:
        if content.frame.mode == "m":
            raise ReadingIssue("content_mode", "Rules in math require a box")
        if command == "vrule":
            content.horizontal(host, span)
        else:
            content.paragraph(host, span)
            if content.frame.mode != "v":
                raise ReadingIssue("content_mode", "hrule requires vertical mode")
        values = {"width": None, "height": 26214 if command == "hrule" else None,
                  "depth": 0 if command == "hrule" else None}
        if command == "vrule":
            values["width"] = 26214
        while True:
            key = next((key for key in values if scanner.keyword(key)), None)
            if key is None:
                break
            values[key] = dimension(scanner)[0]
        scanner.finish()
        content.emit(content.node(host, "rule", span, **values))
        if command == "hrule":
            content.frame.info["prev_depth"] = -65536000
    else:
        vertical, mu = command.startswith("v"), command == "mskip"
        if mu and content.frame.mode != "m":
            raise ReadingIssue("content_mode", "Math glue requires math mode")
        if vertical:
            content.paragraph(host, span)
            if content.frame.mode != "v":
                raise ReadingIssue("content_mode", "Vertical glue in a restricted list")
        elif not mu:
            content.horizontal(host, span)
        if command.endswith("skip"):
            amount = glue(scanner, mu=mu)
            scanner.finish()
        else:
            suffix = command[1:]
            amount = {"fil": Glue(stretch=65536, stretch_order=1),
                      "fill": Glue(stretch=65536, stretch_order=2),
                      "ss": Glue(stretch=65536, stretch_order=1, shrink=65536, shrink_order=1),
                      "filneg": Glue(stretch=-65536, stretch_order=1)}[suffix]
        content.emit(content.node(host, "glue", span, value=amount, mu=mu))
    return result(host, opening)


def last_value(scanner, meaning):
    content = owner(scanner.host)
    if content.frame.kind == "document":
        raise ReadingIssue("outer_vertical_tail", "Outer tail queries require the page builder")
    node = content.frame.nodes[-1] if content.frame.nodes else None
    if meaning.operand == "lastskip":
        value = node.get("value") if node and node.kind in {"glue", "space"} else node.get("glue") if node and node.kind == "leaders" else Glue()
        return InternalQuantity("muglue" if node and node.get("mu") else "glue", value)
    kind, attr = ("kern", "width") if meaning.operand == "lastkern" else ("penalty", "value")
    if kind == "kern" and node and node.kind == "italic_correction":
        if node.get("width") is None:
            raise ReadingIssue("unknown_italic_correction", "Italic correction requires glyph metrics")
        return InternalQuantity("dimension", node.get("width"))
    return InternalQuantity("dimension" if kind == "kern" else "integer", node.get(attr) if node and node.kind == kind else 0)


def last_execute(host, opening, meaning):
    raise ReadingIssue("internal_quantity", "A list-tail quantity requires a value consumer")


def list_state_value(scanner, meaning):
    content = owner(scanner.host)
    key, mode, default = (("space_factor", "h", 1000) if meaning.operand == "spacefactor"
                          else ("prev_depth", "v", -65536000))
    if content.frame.mode != mode:
        raise ReadingIssue("content_mode", meaning.operand + " is unavailable in this mode")
    value = content.frame.info.get(key, default)
    if value is None:
        raise ReadingIssue("unknown_list_dimension", "The preceding box depth requires layout")
    return InternalQuantity("integer" if mode == "h" else "dimension", value)


def list_state(host, opening, meaning):
    scanner = IntegerScanner(host)
    list_state_value(scanner, meaning)
    scanner.optional_equals()
    value = scanner.integer() if meaning.operand == "spacefactor" else dimension(scanner)[0]
    scanner.finish()
    if meaning.operand == "spacefactor" and not 1 <= value <= 32767:
        raise ReadingIssue("space_factor", "Space factor must lie in 1..32767")
    owner(host).frame.info["space_factor" if meaning.operand == "spacefactor" else "prev_depth"] = value
    return result(host, opening)


BOX = PrimitiveOperation("content.box", ExpansionKind.UNEXPANDABLE, box, operand_type=str)
SETBOX = PrimitiveOperation("content.setbox", ExpansionKind.UNEXPANDABLE, set_box, operand_type=type(None), accepted_prefixes=frozenset({"global"}))
MOVE = PrimitiveOperation("content.move_box", ExpansionKind.UNEXPANDABLE, move_box, operand_type=str)
UNBOX = PrimitiveOperation("content.unbox", ExpansionKind.UNEXPANDABLE, unbox, operand_type=str)
BOXDIM = PrimitiveOperation("content.box_dimension", ExpansionKind.UNEXPANDABLE, box_dimension, box_value, operand_type=str, accepted_prefixes=frozenset({"global"}))
LIST = PrimitiveOperation("content.list", ExpansionKind.UNEXPANDABLE, list_operation, operand_type=str)
LAST = PrimitiveOperation("content.last", ExpansionKind.UNEXPANDABLE, last_execute, last_value, operand_type=str)
STATE = PrimitiveOperation("content.list_state", ExpansionKind.UNEXPANDABLE, list_state, list_state_value, operand_type=str)
FAMILY = OperationFamily((BOX, SETBOX, MOVE, UNBOX, BOXDIM, LIST, LAST, STATE),
    tuple(BOX.declare(k, k) for k in "hbox vbox vtop box copy lastbox".split()) +
    (SETBOX.declare("setbox", None),) +
    tuple(MOVE.declare(k, k) for k in "raise lower moveleft moveright shipout leaders cleaders xleaders vcenter".split()) +
    tuple(UNBOX.declare(k, k) for k in "unhbox unvbox unhcopy unvcopy".split()) +
    tuple(BOXDIM.declare(k, v) for k, v in (("wd", "width"), ("ht", "height"), ("dp", "depth"))) +
    tuple(LIST.declare(k, k) for k in "char indent noindent hskip vskip mskip hfil hfill hss hfilneg vfil vfill vss vfilneg kern mkern penalty hrule vrule unskip unkern unpenalty".split()) +
    (LIST.declare(" ", "space"), LIST.declare("/", "italic")) +
    tuple(LAST.declare(k, k) for k in "lastskip lastkern lastpenalty".split()) +
    tuple(STATE.declare(k, k) for k in "spacefactor prevdepth".split()))
