"""Source-bearing, pre-layout TeX lists driven by the shared execution cursor.

Characters are unshaped; paragraphs have not been broken into lines. Unknown
geometry is represented by None, never a plausible numeric approximation.
"""
from dataclasses import dataclass, field, replace

from .dimensions import Glue
from .primitive import PrimitiveMeaning
from .programs import CONTENT, evaluate, expand_call, source_origin
from .state_cells import Cell
from ..reading.contracts import ReadingIssue, SourceCommand
from ..reading.spans import SourceSpan
from ..reading.tex_reader import CatCode, TokenKind


@dataclass(frozen=True)
class Node:
    kind: str
    span: SourceSpan
    children: tuple = ()
    attributes: tuple = ()
    size: int = field(init=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "size", 1 + sum(n.size for n in self.children))

    def get(self, key, default=None):
        return dict(self.attributes).get(key, default)

    def with_value(self, key, value):
        return replace(self, attributes=tuple({**dict(self.attributes), key: value}.items()))

    def as_dict(self):
        def value(item):
            if isinstance(item, Node):
                return item.as_dict()
            if isinstance(item, SourceSpan):
                return location(item)
            if isinstance(item, Glue):
                return {name: getattr(item, name) for name in item.__dataclass_fields__}
            if isinstance(item, tuple):
                return [value(v) for v in item]
            return item
        return {"kind": self.kind, "source": location(self.span),
                "attributes": {k: value(v) for k, v in self.attributes},
                "children": [n.as_dict() for n in self.children]}


def location(span):
    return {"source": span.basis.source_id, "occurrence": span.basis.occurrence_id,
            "start": span.start, "end": span.end}


@dataclass
class Frame:
    kind: str
    mode: str
    span: SourceSpan
    nodes: list = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def copy(self):
        return replace(self, nodes=list(self.nodes), info=dict(self.info))


def content_request(host, event, definition):
    """Execute a macro through the normal bounded program, with a content owner."""
    invocation = expand_call(host, event, definition)
    evaluate(host, invocation.argument("body").tokens, invocation.span, policy=CONTENT,
             return_lookahead=invocation.metadata.get("return_lookahead"))
    if invocation.metadata["input_return_barrier"]:
        from .input_boundaries import require_inert_barrier
        require_inert_barrier(host.context, host.knowledge)
    return SourceCommand(invocation.span, event.token.value, "content")


class ContentState:
    def __init__(self, span, *, limit=100000):
        self.frames = [Frame("document", "v", span)]
        self.limit, self.work = limit, 0

    @property
    def frame(self):
        return self.frames[-1]

    def checkpoint(self):
        return [f.copy() for f in self.frames]

    def restore(self, saved):
        self.frames = [f.copy() for f in saved]

    def node(self, host, kind, span, children=(), **attributes):
        self.work += 1
        if self.work > self.limit:
            raise ReadingIssue("content_budget", "Content construction exhausted its node budget")
        return Node(kind, source_origin(host.program_sources, span), tuple(children), tuple(attributes.items()))

    def emit(self, node):
        # Immutable sharing must not hide exponential copy expansion from the
        # eventual tree serializer. Charge the expanded reference, not its id.
        self.work += node.size
        if self.work > self.limit:
            raise ReadingIssue("content_budget", "Expanded content references exhausted the node budget")
        self.frame.nodes.append(node)

    def hook(self, host, name, span):
        tokens = host.context.token_registers.read(name)
        if tokens:
            evaluate(host, tokens, span, policy=CONTENT)

    def horizontal(self, host, span, *, indent=True):
        if self.frame.mode == "v":
            self.frames.append(Frame("paragraph", "h", span, info={"indent": indent}))
            self.hook(host, "everypar", span)
            if self.frame.mode != "h":
                raise ReadingIssue("paragraph_hook", "everypar changed the pending paragraph's mode")

    def paragraph(self, host, span):
        if self.frame.mode == "m":
            raise ReadingIssue("content_mode", "A paragraph cannot end inside math")
        if self.frame.kind == "paragraph":
            frame = self.frames.pop()
            # TeX removes final interword glue before line breaking.
            if frame.nodes and frame.nodes[-1].kind == "space":
                frame.nodes.pop()
            self.emit(self.node(host, "paragraph", frame.span, frame.nodes,
                                indent=frame.info["indent"], layout="unbroken"))
        # par is inert in restricted horizontal mode and vertical mode.

    def character(self, host, char, span, *, explicit=False):
        if ord(char) > 255:
            raise ReadingIssue("content_character", "The pdfTeX content profile uses byte character codes")
        if self.frame.mode == "m":
            from .primitives.code_tables import read
            key = "mathcode:" + str(ord(char))
            store = host.context.integer_parameters
            code = read(host.context, "mathcode", ord(char))
            self.math_character(host, code, span)
            return
        self.horizontal(host, span)
        font = host.context.state_cells.read("current_font")
        self.emit(self.node(host, "character", span, text=char, code=ord(char), font=font,
                            shaping="pending", explicit=explicit))

    def space(self, host, span, *, explicit=False):
        if explicit:
            self.horizontal(host, span)
        if self.frame.mode == "h" or explicit and self.frame.mode == "m":
            self.emit(self.node(host, "space", span, font=host.context.state_cells.read("current_font"),
                                explicit=explicit, width=None))

    def token(self, host, event):
        token, category = event.token, event.token.catcode
        if category == CatCode.SPACE:
            self.space(host, event.span)
        elif category == CatCode.MATH_SHIFT:
            self.math_shift(host, event.span)
        elif category == CatCode.BEGIN_GROUP:
            if self.frame.mode == "m":
                self.start_field(host, event.span, ("class", "ord"))
            else:
                host.begin_group("simple", event.span)
        elif category == CatCode.END_GROUP:
            if host._groups and host._groups[-1].kind in {"content:math", "content:left", "content:cell"}:
                raise ReadingIssue("content_group", "A brace cannot close this math or alignment context")
            if host._groups and host._groups[-1].kind.startswith("content:"):
                self.close(host, event.span)
            else:
                host.end_group("simple")
        elif category in {CatCode.SUPERSCRIPT, CatCode.SUBSCRIPT}:
            self.scan_field(host, event.span, ("script", "sup" if category == CatCode.SUPERSCRIPT else "sub"))
        elif category == CatCode.ALIGNMENT_TAB:
            from .primitives.alignments import end_cell
            end_cell(host, event.span, row=False)
        elif category == CatCode.PARAMETER:
            raise ReadingIssue("content_token", "Alignment/parameter token outside its owning scanner")
        else:
            self.character(host, token.value, event.span)
        return event

    def start_field(self, host, span, target):
        if self.frame.mode != "m":
            raise ReadingIssue("content_mode", "Math field requires math mode")
        if target[0] == "script":
            if not self.frame.nodes or self.frame.nodes[-1].kind != "noad":
                self.emit(self.node(host, "noad", span, class_="ord"))
            if any(n.kind == target[1] for n in self.frame.nodes[-1].children):
                raise ReadingIssue("double_script", "The current math atom already has that script")
        host.begin_group("content:field", span)
        self.frames.append(Frame("field", "m", span, info={"target": target}))

    def scan_field(self, host, span, target):
        from .integers import IntegerScanner
        from .primitives.conversions import is_opening_group
        scanner = IntegerScanner(host)
        token = scanner._nonspace()
        if is_opening_group(scanner.reader, token):
            scanner.finish()
            self.start_field(host, span, target)
            return
        code = None
        if token is not None and token.kind == TokenKind.CHARACTER and token.catcode in {CatCode.LETTER, CatCode.OTHER}:
            from .primitives.code_tables import read
            key = "mathcode:" + str(ord(token.value))
            store = host.context.integer_parameters
            code = read(host.context, "mathcode", ord(token.value))
        elif token is not None:
            meaning = host.context.resolve_meaning(host.knowledge, token.value, token.kind)
            if isinstance(meaning, PrimitiveMeaning) and meaning.uncertain is None:
                if meaning.operation == "math.character":
                    code = meaning.operand
                elif meaning.operation == "content.math" and meaning.operand == "mathchar":
                    code = scanner.integer()
        if code is None:
            raise ReadingIssue("math_field", "Expected a character, math character or opening group")
        scanner.finish()
        self.start_field(host, span, target)
        self.math_character(host, code, token.span)
        self.close(host, span)

    def math_character(self, host, code, span):
        if self.frame.mode != "m":
            raise ReadingIssue("content_mode", "Math character requires math mode")
        if not 0 <= code <= 32767:
            raise ReadingIssue("math_character", "Active or out-of-range math codes require another expansion step")
        cls, family, char = code // 4096, (code // 256) % 16, code % 256
        if cls == 7:
            fam = host.context.integer_parameters.read("fam")
            if 0 <= fam <= 15:
                family = fam
            cls = 0
        nucleus = self.node(host, "math_character", span, family=family, code=char)
        self.emit(self.node(host, "noad", span, (nucleus,), class_=("ord", "op", "bin", "rel", "open", "close", "punct", "ord")[cls]))

    def math_shift(self, host, span):
        if self.frame.kind == "math":
            if host._groups[-1].kind != "content:math":
                raise ReadingIssue("math_group", "Math shift cannot close an intervening group")
            if self.frame.info["display"]:
                following = host.reader.next_token()
                if following is None or following.catcode != CatCode.MATH_SHIFT:
                    raise ReadingIssue("math_delimiter", "Display math requires two closing math shifts")
            self.close(host, span)
            return
        if self.frame.mode == "m":
            raise ReadingIssue("math_group", "Math shift inside an unfinished math field")
        following = host.reader.next_token()
        display = following is not None and following.catcode == CatCode.MATH_SHIFT
        if following is not None and not display:
            host.reader.unread_token(following)
        if display:
            self.paragraph(host, span)
            if self.frame.mode != "v":
                raise ReadingIssue("content_mode", "Display math in a restricted horizontal list")
        else:
            self.horizontal(host, span)
        host.begin_group("content:math", span)
        host.context.integer_parameters.assign("fam", -1, span)
        self.frames.append(Frame("math", "m", span, info={"display": display}))
        self.hook(host, "everydisplay" if display else "everymath", span)

    def math_nodes(self, host, frame):
        if "numerator" not in frame.info:
            return tuple(frame.nodes)
        return (self.node(host, "fraction", frame.span,
                          (self.node(host, "numerator", frame.span, frame.info["numerator"]),
                           self.node(host, "denominator", frame.span, frame.nodes)),
                          thickness=frame.info["thickness"]),)

    def close(self, host, span):
        if self.frame.kind == "paragraph":
            self.paragraph(host, span)
        frame = self.frame
        if not host._groups or host._groups[-1].kind != "content:" + frame.kind:
            raise ReadingIssue("content_group", "Content frame does not own the closing group")
        after = host.end_group("content:" + frame.kind, deliver=False)
        self.frames.pop()
        if frame.kind == "math":
            self.emit(self.node(host, "math", frame.span, self.math_nodes(host, frame),
                                display=frame.info["display"], layout="unconverted"))
        elif frame.kind == "field":
            target = frame.info["target"]
            nodes = self.math_nodes(host, frame)
            if target[0] == "script":
                previous = self.frame.nodes[-1]
                self.frame.nodes[-1] = replace(previous, children=(*previous.children,
                    self.node(host, target[1], frame.span, nodes)))
            elif target[0] == "choice":
                alternatives = (*target[1], self.node(host, ("display", "text", "script", "scriptscript")[len(target[1])], frame.span, nodes))
                if len(alternatives) < 4:
                    self.require_field_group(host, span, ("choice", alternatives))
                else:
                    self.emit(self.node(host, "choice", frame.span, alternatives))
            else:
                nucleus = self.node(host, "math_list", frame.span, nodes)
                self.emit(self.node(host, "noad", frame.span, (nucleus,), class_=target[1],
                                    **({"accent_code" if target[1] == "accent" else "delimiter": target[2]} if len(target) > 2 else {})))
        elif frame.kind == "left":
            self.emit(self.node(host, "noad", frame.span,
                                (self.node(host, "delimited", frame.span, self.math_nodes(host, frame),
                                           left=frame.info["left"], right=frame.info["right"]),), class_="inner"))
        elif frame.kind in {"hbox", "vbox", "vtop"}:
            size = frame.info.get("size")
            width = size if frame.kind == "hbox" and frame.info.get("spec") == "to" else None
            height = size if frame.kind == "vbox" and frame.info.get("spec") == "to" else None
            if not frame.nodes:
                width = width if width is not None else (size or 0) if frame.kind == "hbox" else 0
                height = height if height is not None else (size or 0) if frame.kind != "hbox" else 0
            depth = 0 if not frame.nodes else None
            if frame.kind == "vtop" and not frame.nodes:
                height, depth = 0, size or 0
            node = self.node(host, frame.kind, frame.span, frame.nodes, width=width, height=height,
                             depth=depth, spec=frame.info.get("spec"), size=size,
                             packing="pending" if frame.nodes else "empty")
            self.deliver_box(host, node, frame.info["target"], frame.span)
        elif frame.kind == "alignment":
            self.emit(self.node(host, "alignment", frame.span, frame.nodes,
                columns=len(frame.info["columns"]), tabskip=frame.info["tabskip"],
                spec=frame.info["spec"], size=frame.info["size"], packing="pending"))
        elif frame.kind in {"insert", "vadjust", "noalign"}:
            self.emit(self.node(host, frame.kind, frame.span, frame.nodes, **frame.info))
        else:
            raise ReadingIssue("content_group", "Unsupported content group")
        if after:
            host.insert_tokens(after, span)

    def require_field_group(self, host, span, target):
        from .integers import IntegerScanner
        from .primitives.conversions import is_opening_group
        scanner = IntegerScanner(host)
        if not is_opening_group(scanner.reader, scanner._nonspace()):
            raise ReadingIssue("math_field", "This math field requires an opening group")
        scanner.finish()
        self.start_field(host, span, target)

    def read_box(self, host, index, *, take=False):
        key, cells = "box:" + str(index), host.context.state_cells
        if key not in cells.values and not host.context.primitive_initial_state:
            raise ReadingIssue("unavailable_box", "Box register has no established initial value")
        box = cells.read(key) if key in cells.values else cells.initial(None)
        if take and box is not None:
            # Taking a box changes the current slot without making a new save
            # entry. An existing local assignment still restores on group exit.
            cells.values[key] = Cell(None, cells.values[key].span)
        return box

    def deliver_box(self, host, node, target, span):
        if target[0] == "register":
            host.context.state_cells.assign("box:" + str(target[1]), node, span, global_=target[2])
        elif node is not None:
            if target[0] == "shipout":
                self.emit(self.node(host, "shipout", span, (node,), execution="issued"))
            elif target[0] == "leaders":
                from .primitives.content import finish_leaders
                finish_leaders(host, node, target[1], span)
            elif target[0] == "vcenter":
                self.emit(self.node(host, "noad", span, (node,), class_="vcenter"))
            else:
                if len(target) > 1:
                    node = node.with_value("shift", target[1])
                if self.frame.mode == "m":
                    node = self.node(host, "noad", span, (node,), class_="ord")
                self.emit(node)

    def finish(self, host, span):
        self.paragraph(host, span)
        if len(self.frames) != 1 or host._groups:
            raise ReadingIssue("content_unclosed", "Content execution ended with an open group or list")

    def as_dict(self):
        return {"schema": "pytexml-content/1", "stage": "pre_layout",
                "children": [n.as_dict() for n in self.frames[0].nodes],
                "open_lists": [{"kind": f.kind, "mode": f.mode, "source": location(f.span),
                                "children": [n.as_dict() for n in f.nodes]} for f in self.frames[1:]]}
