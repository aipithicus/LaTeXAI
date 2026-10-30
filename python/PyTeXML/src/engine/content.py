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
    payload: tuple = ()  # Frozen execution input; public token children carry its provenance.
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
    def __init__(self, span, *, limit=100000, insertion_roles=None, box_roles=None):
        from .lifecycle import Lifecycle
        self.frames = [Frame("document", "v", span)]
        self.limit, self.work = limit, 0
        self.lifecycle = Lifecycle(insertion_roles, box_roles)

    @property
    def frame(self):
        return self.frames[-1]

    def checkpoint(self):
        return [f.copy() for f in self.frames], self.lifecycle.checkpoint()

    def restore(self, saved):
        self.frames = [f.copy() for f in saved[0]]
        self.lifecycle.restore(saved[1])

    def node(self, host, kind, span, children=(), *, payload=(), **attributes):
        self.work += 1
        if self.work > self.limit:
            raise ReadingIssue("content_budget", "Content construction exhausted its node budget")
        return Node(kind, source_origin(host.program_sources, span), tuple(children), tuple(attributes.items()), tuple(payload))

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

    def break_text(self):
        if self.frame.mode == "h":
            self.work += 1
            self.frame.info["text_run"] = self.work

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
            from .measurement import parameter
            parameters = tuple((key, parameter(host.context, key, glue=key != "hsize"))
                               for key in ("hsize", "leftskip", "rightskip", "parfillskip"))
            self.emit(self.node(host, "paragraph", frame.span, frame.nodes,
                                indent=frame.info["indent"], layout="unbroken", layout_parameters=parameters))
            self.frame.info["prev_depth"] = None
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
        if "text_run" not in self.frame.info:
            self.break_text()
        font = host.context.state_cells.read("current_font")
        from .primitives.code_tables import read
        factor, previous = read(host.context, "sfcode", ord(char)), self.frame.info.get("space_factor", 1000)
        if factor:
            self.frame.info["space_factor"] = 1000 if factor > 1000 and previous < 1000 else factor
        self.emit(self.node(host, "character", span, text=char, code=ord(char), font=font,
                            shaping="pending", explicit=explicit, run=self.frame.info.get("text_run", 0)))

    def space(self, host, span, *, explicit=False):
        if explicit:
            self.horizontal(host, span)
        if self.frame.mode == "h" or explicit and self.frame.mode == "m":
            from .measurement import interword
            font = host.context.state_cells.read("current_font")
            amount = interword(host.context, font, 1000 if explicit else self.frame.info.get("space_factor", 1000))
            self.emit(self.node(host, "space", span, font=host.context.state_cells.read("current_font"),
                                explicit=explicit, value=amount, width=amount.width))

    def token(self, host, event):
        token, category = event.token, event.token.catcode
        if category == CatCode.SPACE:
            self.space(host, event.span)
        elif category == CatCode.MATH_SHIFT:
            self.math_shift(host, event.span)
        elif category == CatCode.BEGIN_GROUP:
            self.break_text()
            if self.frame.mode == "m":
                self.start_field(host, event.span, ("class", "ord"))
            else:
                host.begin_group("simple", event.span)
        elif category == CatCode.END_GROUP:
            self.break_text()
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
        measured = None
        if frame.kind in {"hbox", "vbox", "vtop"}:
            from .measurement import box
            measured = box(host.context, frame)
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
            node = self.node(host, frame.kind, frame.span, frame.nodes,
                             width=measured.width, height=measured.height, depth=measured.depth,
                             spec=frame.info.get("spec"), size=size,
                             measurement_requirements=measured.requirements, glyph_runs=measured.glyphs,
                             packing="measured" if all(v is not None for v in (measured.width, measured.height, measured.depth)) else "pending")
            self.deliver_box(host, node, frame.info["target"], frame.span)
        elif frame.kind == "alignment":
            self.emit(self.node(host, "alignment", frame.span, frame.nodes,
                columns=len(frame.info["columns"]), tabskip=frame.info["tabskip"],
                spec=frame.info["spec"], size=frame.info["size"], packing="pending"))
        elif frame.kind in {"insert", "vadjust", "noalign"}:
            node = self.node(host, frame.kind, frame.span, frame.nodes, **frame.info)
            if frame.kind == "insert":
                node = node.with_value("role", self.lifecycle.insertion_roles.get(frame.info["class_"], "unclassified"))
            self.emit(node)
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
            if node is not None and target[1] in self.lifecycle.box_roles:
                self.lifecycle.record(self.node(host, "stored_content", span, (node,), register=target[1],
                    role=self.lifecycle.box_roles[target[1]], placement="unresolved"), self)
        elif node is not None:
            if target[0] == "shipout":
                self.lifecycle.shipout(self, host, node, span)
                self.emit(self.node(host, "shipout", span, (node,), execution="observed"))
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
                elif self.frame.mode == "h":
                    self.frame.info["space_factor"] = 1000
                elif self.frame.mode == "v":
                    self.append_baseline(host, node, span)
                self.emit(node)

    def append_baseline(self, host, node, span):
        from .measurement import parameter
        from .dimensions import checked
        previous = self.frame.info.get("prev_depth", -65536000)
        height = node.get("height")
        if previous is not None and previous <= -65536000:
            pass
        elif previous is None or height is None:
            self.emit(self.node(host, "baseline_glue", span, width=None,
                                measurement_requirements=(("baseline_dimensions", span),)))
        elif previous > -65536000:
            baseline = parameter(host.context, "baselineskip", glue=True)
            distance = checked(baseline.width - previous - height)
            amount = (parameter(host.context, "lineskip", glue=True)
                      if distance < parameter(host.context, "lineskiplimit") else replace(baseline, width=distance))
            self.emit(self.node(host, "glue", span, value=amount, implicit="baseline"))
        self.frame.info["prev_depth"] = node.get("depth")

    def finish(self, host, span):
        self.paragraph(host, span)
        if len(self.frames) != 1 or host._groups:
            raise ReadingIssue("content_unclosed", "Content execution ended with an open group or list")
        if self.lifecycle.links or self.lifecycle.anchors:
            raise ReadingIssue("driver_unclosed", "Content execution ended with an open link or anchor")

    def as_dict(self):
        return {"schema": "pytexml-content/1", "stage": "pre_layout",
                "lifecycle": [n.as_dict() for n in self.lifecycle.records],
                "drivers": list(self.lifecycle.drivers),
                "virtual_outputs": {name: {"text": "".join(text + "\n" for text, _ in lines),
                    "sources": [location(span) for _, span in lines]} for name, lines in self.lifecycle.outputs.items()},
                "children": [n.as_dict() for n in self.frames[0].nodes],
                "open_lists": [{"kind": f.kind, "mode": f.mode, "source": location(f.span),
                                "children": [n.as_dict() for n in f.nodes]} for f in self.frames[1:]]}
