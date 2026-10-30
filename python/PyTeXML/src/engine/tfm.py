"""Read TFM parameter arrays and bounded local glyph measurement programs.

Scaling follows TeX82 read_font_info/store_scaled. The original metric bytes
remain with the caller; unsupported shaping operations retain explicit boundaries.
"""
import struct
from dataclasses import dataclass
from .dimensions import checked
from ..reading.contracts import ReadingIssue


def scale_word(word, size):
    """TeX store_scaled, including its two integer divisions and sign byte."""
    z, alpha = size, 16
    while z >= 8388608:
        z //= 2
        alpha *= 2
    beta, alpha = 256 // alpha, alpha * z
    a, b, c, d = word
    if a not in {0, 255}:
        raise ReadingIssue("font_metric", "Invalid TFM fix_word")
    return checked((((d * z // 256 + c * z) // 256) + b * z) // beta - (alpha if a == 255 else 0))


@dataclass(frozen=True)
class Glyph:
    width: int
    height: int
    depth: int
    italic: int
    program: int | None


@dataclass(frozen=True)
class Metrics:
    glyphs: tuple
    program: tuple
    kerns: tuple
    boundary: bool = False

    def instruction(self, left, right):
        start = self.glyphs[left].program
        if start is None:
            return None
        steps = 0
        if self.program[start][0] > 128:
            start = self.program[start][2] * 256 + self.program[start][3]
        while 0 <= start < len(self.program):
            steps += 1
            if steps > len(self.program):
                raise ReadingIssue("font_metric", "Cyclic ligature/kern program")
            skip, char, op, remainder = self.program[start]
            if skip <= 128 and char == right:
                return op, remainder
            if skip >= 128:
                return None
            start += skip + 1
        raise ReadingIssue("font_metric", "Ligature/kern address is outside the TFM program")

    def shape(self, characters):
        """Return glyph/kern items, preserving each glyph's logical character cluster.

        TFM boundary-character programs are deliberately an explicit requirement
        until their start/end semantics have a native witness.
        """
        if self.boundary:
            raise ReadingIssue("font_boundary_program", "Boundary ligature/kern programs are not qualified")
        items = [("glyph" if self.glyphs[c] else "missing", c, (i,)) for i, c in enumerate(characters)]
        cursor, work = 0, 0
        while cursor + 1 < len(items):
            work += 1
            if work > 100000:
                raise ReadingIssue("font_program_budget", "Ligature program exhausted its work budget")
            left, right = items[cursor:cursor + 2]
            action = self.instruction(left[1], right[1]) if left[0] == right[0] == "glyph" else None
            if action is None:
                cursor += 1
                continue
            op, value = action
            if op >= 128:
                address = (op - 128) * 256 + value
                if address >= len(self.kerns):
                    raise ReadingIssue("font_metric", "Kern address is outside the TFM table")
                items.insert(cursor + 1, ("kern", self.kerns[address], ()))
                cursor += 2
            else:
                if op != 0:
                    raise ReadingIssue("font_ligature_operation", "Retaining or stopping ligature operations are not qualified")
                if self.glyphs[value] is None:
                    raise ReadingIssue("font_metric", "Ligature refers to an absent glyph")
                replacement = ([left] if op & 2 else []) + [("glyph", value, (*left[2], *right[2]))] + ([right] if op & 1 else [])
                items[cursor:cursor + 2] = replacement
                cursor += op // 4
        return tuple(items)


def metrics(data, *, at):
    size, _ = parameters(data, at=at)
    lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np = struct.unpack_from(">12H", data)
    chars = 6 + lh
    widths = chars + ec - bc + 1
    heights, depths = widths + nw, widths + nw + nh
    italics = depths + nd
    programs = italics + ni
    kerns = programs + nl
    def table(offset, count):
        return tuple(scale_word(data[4 * n:4 * n + 4], size) for n in range(offset, offset + count))
    w, h, d, i = table(widths, nw), table(heights, nh), table(depths, nd), table(italics, ni)
    if any(values[0] for values in (w, h, d, i)):
        raise ReadingIssue("font_metric", "TFM zero dimension entries must be zero")
    glyphs = [None] * 256
    program = tuple(tuple(data[4 * n:4 * n + 4]) for n in range(programs, programs + nl))
    for c in range(bc, ec + 1):
        wi, hd, it, remainder = data[4 * (chars + c - bc):4 * (chars + c - bc) + 4]
        hi, di, ii, tag = hd >> 4, hd & 15, it >> 2, it & 3
        if wi >= nw or hi >= nh or di >= nd or ii >= ni or tag == 1 and remainder >= nl:
            raise ReadingIssue("font_metric", "Invalid TFM character dimensions or ligature address")
        if wi:
            glyphs[c] = Glyph(w[wi], h[hi], d[di], i[ii], remainder if tag == 1 else None)
    return Metrics(tuple(glyphs), program, table(kerns, nk), bool(program and (program[0][0] == 255 or program[-1][0] == 255)))


def parameters(data, *, at=None, scaled=1000):
    def invalid():
        raise ReadingIssue("font_metric", "Malformed or unsupported TFM parameter data")
    if len(data) < 32:
        invalid()
    lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np = struct.unpack_from(">12H", data)
    if (lh < 2 or bc > ec + 1 or ec > 255 or min(nw, nh, nd, ni) == 0 or
            lf != 6 + lh + (ec - bc + 1) + nw + nh + nd + ni + nl + nk + ne + np or
            len(data) < 4 * lf or np > 10000):
        invalid()
    design = int.from_bytes(data[28:32], "big", signed=True) // 16
    if design < 65536:
        invalid()
    size = checked(at if at is not None else design * scaled // 1000)
    if size <= 0 or size >= 134217728:
        invalid()
    z, alpha = size, 16
    while z >= 8388608:
        z //= 2
        alpha *= 2
    beta, alpha = 256 // alpha, alpha * z
    result = []
    for index in range(np):
        word = data[4 * (lf - np + index):4 * (lf - np + index + 1)]
        if index == 0:
            value = int.from_bytes(word, "big", signed=True) // 16
        else:
            a, b, c, d = word
            if a not in {0, 255}:
                invalid()
            value = (((d * z // 256 + c * z) // 256) + b * z) // beta
            if a == 255:
                value -= alpha
        result.append(checked(value))
    return size, tuple(result) + (0,) * max(0, 7 - len(result))
