"""TeX scaled dimensions and glue, with explicit finite/infinite components."""
from dataclasses import dataclass
from fractions import Fraction
from .quantities import print_scaled
from ..reading.contracts import ReadingIssue
from ..reading.tex_reader import CatCode, TokenKind


MAX_DIMEN = 1073741823
UNITS = {"pt": (1, 1), "pc": (12, 1), "in": (7227, 100), "bp": (7227, 7200),
         "cm": (7227, 254), "mm": (7227, 2540), "dd": (1238, 1157), "cc": (14856, 1157), "sp": (1, 65536)}


def checked(value, maximum=MAX_DIMEN):
    if abs(value) > maximum:
        raise ReadingIssue("arithmetic_overflow", "Value exceeds the TeX quantity range")
    return value


def trunc_div(value, divisor):
    if divisor == 0:
        raise ReadingIssue("division_by_zero", "TeX arithmetic division by zero")
    return (-1 if (value < 0) != (divisor < 0) else 1) * (abs(value) // abs(divisor))


@dataclass(frozen=True, slots=True)
class Glue:
    width: int = 0
    stretch: int = 0
    stretch_order: int = 0
    shrink: int = 0
    shrink_order: int = 0

    def scaled(self, factor, *, divide=False):
        operation = (lambda n: trunc_div(n, factor)) if divide else (lambda n: checked(n * factor))
        return Glue(operation(self.width), operation(self.stretch), self.stretch_order,
                    operation(self.shrink), self.shrink_order)

    def plus(self, other):
        def add(a, ao, b, bo):
            if a == 0:
                return b, bo if b else 0
            if b == 0:
                return a, ao
            return (checked(a + b), ao) if ao == bo else (a, ao) if ao > bo else (b, bo)
        stretch, so = add(self.stretch, self.stretch_order, other.stretch, other.stretch_order)
        shrink, sho = add(self.shrink, self.shrink_order, other.shrink, other.shrink_order)
        return Glue(checked(self.width + other.width), stretch, so, shrink, sho)


def glue_text(value, *, mu=False):
    def part(number, order):
        return print_scaled(number)[:-2] + ("fi" + "l" * order if order else "mu" if mu else "pt")
    text = part(value.width, 0)
    if value.stretch:
        text += " plus " + part(value.stretch, value.stretch_order)
    if value.shrink:
        text += " minus " + part(value.shrink, value.shrink_order)
    return text


def signs(scanner):
    sign, token = 1, scanner._nonspace()
    while scanner._other(token, "+-"):
        if token.value == "-":
            sign = -sign
        token = scanner._nonspace()
    return sign, token


def dimension(scanner, *, mu=False, infinite=False, start=None):
    magnification = 1000
    sign, token, quantity = start if start is not None else (*signs(scanner), None)
    if token is not None and token.kind != TokenKind.CHARACTER:
        quantity = quantity or scanner.internal(token)
        if quantity.kind in {"dimension", "glue", "muglue"}:
            if mu != (quantity.kind == "muglue"):
                raise ReadingIssue("incompatible_units", "Cannot mix math and ordinary dimensions")
            value = quantity.value.width if quantity.kind in {"glue", "muglue"} else quantity.value
            return sign * value, 0
        if quantity.kind != "integer":
            raise ReadingIssue("dimension_value", "Expected a numeric internal value")
        number = Fraction(quantity.value)
    elif scanner._other(token, "'\"`"):
        scanner.reader.unread_token(token)
        number = Fraction(scanner.integer())
    else:
        digits = []
        while token is not None and token.catcode == CatCode.OTHER and token.value in "0123456789.,":
            digits.append(token.value)
            token = scanner._next()
        if token is not None:
            scanner.reader.unread_token(token)
        try:
            number = Fraction("".join(digits).replace(",", "."))
        except (ValueError, ZeroDivisionError) as error:
            raise ReadingIssue("dimension_value", "Invalid dimension number") from error
    if infinite and scanner.keyword("fil"):
        order = 1
        while scanner.keyword("l"):
            order += 1
        if order > 3:
            raise ReadingIssue("glue_order", "Glue order exceeds filll")
        scanner._optional_space()
        return checked(sign * ((number.numerator * 65536 * 2 + number.denominator) // (2 * number.denominator))), order
    if mu:
        if not scanner.keyword("mu"):
            raise ReadingIssue("dimension_unit", "Math glue requires mu units")
        factor = Fraction(1)
    else:
        true = scanner.keyword("true")
        unit = next((unit for unit in UNITS if scanner.keyword(unit)), None)
        if unit is None:
            if true:
                raise ReadingIssue("dimension_unit", "True dimensions require a physical unit")
            # Font-relative units use the established current font, never guesses.
            relative = next((unit for unit in ("em", "ex") if scanner.keyword(unit)), None)
            if relative is None:
                token = scanner._nonspace()
                if token is None:
                    raise ReadingIssue("dimension_unit", "Missing dimension unit")
                quantity = scanner.internal(token)
                if quantity.kind != "dimension":
                    raise ReadingIssue("dimension_unit", "Expected a dimension unit")
                factor = Fraction(quantity.value, 65536)
            else:
                cells = scanner.host.context.state_cells
                identity = (cells.initial("nullfont") if "current_font" not in cells.values and
                            scanner.host.context.primitive_initial_state else cells.read("current_font"))
                params = scanner.host.context.fonts.cell(identity, 6 if relative == "em" else 5)
                factor = Fraction(params[5 if relative == "em" else 4], 65536)
        else:
            factor = Fraction(*UNITS[unit])
        if true:
            from .primitives.parameters import internal_value
            from .primitive import PrimitiveMeaning
            mag = internal_value(scanner, PrimitiveMeaning("parameter.assign_integer", "mag")).value
            if not 1 <= mag <= 32768:
                raise ReadingIssue("magnification", "Magnification must be in 1..32768")
            cells = scanner.host.context.state_cells
            if "prepared_magnification" in cells.values and cells.read("prepared_magnification") != mag:
                raise ReadingIssue("magnification", "Magnification changed after true units were used")
            cells.assign("prepared_magnification", mag, token.span if token is not None else None, global_=True)
            magnification = mag
    # TeX rounds the decimal fraction to a scaled point before applying a unit
    # ratio, which then truncates. Integer sp deliberately drops the fraction.
    fraction = abs(number) % 1
    scaled = int(abs(number)) * 65536 + (fraction.numerator * 65536 * 2 + fraction.denominator) // (2 * fraction.denominator)
    # TeX truncates the magnification adjustment BEFORE converting units.
    # Combining both ratios changes valid dimensions (1truein at mag=1200).
    scaled = scaled * 1000 // magnification
    if not mu and unit == "sp":
        value = int(abs(number)) if magnification == 1000 else scaled // 65536
    else:
        value = int(scaled * factor)
    value *= -1 if number < 0 else 1
    scanner._optional_space()
    return checked(sign * value), 0


def glue(scanner, *, mu=False):
    sign, token = signs(scanner)
    quantity = None
    if token is not None and token.kind != TokenKind.CHARACTER:
        quantity = scanner.internal(token)
        if quantity.kind in {"glue", "muglue"}:
            if (quantity.kind == "muglue") != mu:
                raise ReadingIssue("incompatible_units", "Cannot mix ordinary and math glue")
            return quantity.value.scaled(sign)
    width, _ = dimension(scanner, mu=mu, start=(sign, token, quantity))
    stretch, so = dimension(scanner, mu=mu, infinite=True) if scanner.keyword("plus") else (0, 0)
    shrink, sho = dimension(scanner, mu=mu, infinite=True) if scanner.keyword("minus") else (0, 0)
    return Glue(width, stretch, so, shrink, sho)
