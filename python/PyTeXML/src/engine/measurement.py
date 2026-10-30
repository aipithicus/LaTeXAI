"""Exact local list measurements with explicit prerequisites for unknown fields.

This module performs no paragraph/page breaking and invokes no native process.
"""
from dataclasses import dataclass

from .dimensions import Glue, checked, trunc_div
from ..reading.contracts import ReadingIssue


@dataclass(frozen=True)
class Measurement:
    width: int | None
    height: int | None
    depth: int | None
    requirements: tuple = ()
    glyphs: tuple = ()


def add(a, b):
    return checked(a + b) if a is not None and b is not None else None


def maximum(a, b):
    return max(a, b) if a is not None and b is not None else None


def parameter(context, name, *, glue=False):
    store = context.state_cells if glue else context.integer_parameters
    if name in store.values:
        return store.read(name)
    if context.primitive_initial_state:
        return store.initial(Glue()) if glue else 0
    raise ReadingIssue("unavailable_measurement_parameter", f"No established {name}")


def interword(context, font, factor=1000):
    space = parameter(context, "spaceskip", glue=True)
    extra = parameter(context, "xspaceskip", glue=True)
    if factor >= 2000 and extra != Glue():
        return extra
    values = context.fonts.parameters(font)
    if space == Glue():
        space = Glue(values[1], values[2], 0, values[3], 0)
    return Glue(checked(space.width + (values[6] if factor >= 2000 else 0)),
                checked(trunc_div(space.stretch * factor, 1000)), space.stretch_order,
                checked(trunc_div(space.shrink * 1000, factor)), space.shrink_order)


def horizontal(context, nodes):
    width, height, depth, requirements, runs = 0, 0, 0, [], []
    index = 0
    while index < len(nodes):
        node = nodes[index]
        if node.kind == "character":
            font, run, start = node.get("font"), node.get("run"), index
            while index < len(nodes) and nodes[index].kind == "character" and (nodes[index].get("font"), nodes[index].get("run")) == (font, run):
                index += 1
            try:
                metrics = context.fonts.metrics(font)
                shaped = metrics.shape(tuple(n.get("code") for n in nodes[start:index]))
                w, h, d = 0, 0, 0
                for kind, value, cluster in shaped:
                    if kind == "kern":
                        w = checked(w + value)
                    elif kind == "glyph":
                        glyph = metrics.glyphs[value]
                        w, h, d = checked(w + glyph.width), max(h, glyph.height), max(d, glyph.depth)
                runs.append((font, shaped))
            except ReadingIssue as error:
                w, h, d = None, None, None
                requirements.append((error.reason, node.span))
        else:
            index += 1
            if node.kind in {"glue", "space", "leaders"}:
                value = node.get("value", node.get("glue"))
                w, h, d = (value.width if isinstance(value, Glue) else node.get("width")), 0, 0
            elif node.kind in {"kern", "italic_correction", "indent"}:
                w, h, d = node.get("width"), 0, 0
            elif node.kind in {"hbox", "vbox", "vtop", "cell", "rule"}:
                shift = node.get("shift", 0)
                w, h, d = node.get("width"), node.get("height"), node.get("depth")
                if node.kind == "rule":
                    h, d = h or 0, d or 0  # running rule extents follow the enclosing box
                h, d = add(h, -shift), add(d, shift)
            elif node.kind in {"penalty", "write", "output_stream", "mark", "insert", "vadjust", "special", "driver_event", "anchor"}:
                w, h, d = 0, 0, 0
            else:
                w, h, d = None, None, None
                requirements.append(("math_layout" if node.kind == "math" else "content_measurement", node.span))
        width, height, depth = add(width, w), maximum(height, h), maximum(depth, d)
        if (w is None or h is None or d is None) and not any(s == node.span for _, s in requirements):
            requirements.append(("child_measurement", node.span))
    return Measurement(width, height, depth, tuple(dict.fromkeys(requirements)), tuple(runs))


def vertical(context, nodes, *, maxdepth):
    width, height, depth, requirements = 0, 0, 0, []
    for node in nodes:
        if node.kind in {"hbox", "vbox", "vtop", "row", "rule", "alignment"}:
            w, h, d = node.get("width"), node.get("height"), node.get("depth")
            if node.kind == "rule":
                w = w or 0
            width = maximum(width, add(w, node.get("shift", 0)))
            height, depth = add(add(height, depth), h), d
        elif node.kind in {"glue", "kern"}:
            amount = node.get("value").width if node.kind == "glue" else node.get("width")
            height, depth = add(add(height, depth), amount), 0
        elif node.kind in {"penalty", "write", "output_stream", "mark", "insert", "vadjust", "special", "driver_event", "anchor"}:
            continue
        else:
            width, height, depth = None, None, None
            requirements.append(("paragraph_breaking" if node.kind == "paragraph" else "vertical_layout", node.span))
        if any(v is None for v in (width, height, depth)):
            requirements.extend(node.get("measurement_requirements", ()))
    if depth is not None and depth > maxdepth:
        height, depth = add(height, depth - maxdepth), maxdepth
    return Measurement(width, height, depth, tuple(dict.fromkeys(requirements)))


def box(context, frame):
    result = (horizontal(context, frame.nodes) if frame.kind == "hbox" else
              vertical(context, frame.nodes, maxdepth=parameter(context, "boxmaxdepth")))
    w, h, d = result.width, result.height, result.depth
    size, spec = frame.info.get("size"), frame.info.get("spec")
    if size is not None:
        if frame.kind == "hbox":
            w = size if spec == "to" else add(w, size)
        else:
            h = size if spec == "to" else add(h, size)
    if frame.kind == "vtop":
        first = frame.nodes[0] if frame.nodes else None
        top = first.get("height") if first and first.kind in {"hbox", "vbox", "vtop", "rule"} else 0
        h, d = top, add(add(h, d), -top) if top is not None else None
    return Measurement(w, h, d, result.requirements, result.glyphs)
