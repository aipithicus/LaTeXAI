"""Read TFM parameter arrays for format state, without constructing glyph lists.

Scaling follows TeX82 read_font_info/store_scaled. The original metric bytes
remain with the caller; this reader establishes parameters, not layout support.
"""
import struct
from .dimensions import checked
from ..reading.contracts import ReadingIssue


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
