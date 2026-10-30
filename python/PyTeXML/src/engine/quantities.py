"""Typed internal values shared by scanners and expandable conversions."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING
from ..reading.tex_reader import Token
if TYPE_CHECKING:
    from .dimensions import Glue


@dataclass(frozen=True, slots=True)
class InternalQuantity:
    kind: Literal["integer", "dimension", "glue", "muglue", "tokens", "font"]
    value: int | tuple[Token, ...] | str | "Glue"


def print_scaled(value):
    """TeX82 print_scaled: shortest decimal which round-trips scaled points."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    result = sign + str(value // 65536) + "."
    fraction, delta = 10 * (value % 65536) + 5, 10
    while True:
        if delta > 65536:
            fraction += 32768 - 50000
        result += str(fraction // 65536)
        fraction = 10 * (fraction % 65536)
        delta *= 10
        if fraction <= delta:
            return result + "pt"
