"""Font-dimension array access through established font identities (TeX82)."""
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..quantities import InternalQuantity
from ..transactions import atomic, assignment_global
from ..primitive import PrimitiveMeaning
from ...reading.assignment_scanner import AssignmentScanner
from .registers import dimension
from ...reading.contracts import ReadingIssue, SourceCommand


def font_value(scanner, meaning):
    scanner.host.context.fonts.parameters(meaning.operand)
    return InternalQuantity("font", meaning.operand)


def select(host, opening, meaning):
    host.context.fonts.parameters(meaning.operand)
    host.context.state_cells.assign("current_font", meaning.operand, opening.span,
                                    global_=assignment_global(host))
    return SourceCommand(opening.span, opening.token.value, "font_parameter_assignment",
                         metadata={"trailing_control_word": opening.token.control_word})


def current(scanner, meaning):
    key = "current_font"
    identity = (scanner.host.context.state_cells.read(key) if key in scanner.host.context.state_cells.values
                else scanner.host.context.state_cells.initial("nullfont") if scanner.host.context.primitive_initial_state else None)
    if identity is None:
        raise ReadingIssue("unavailable_font", "Current font has not been established")
    return InternalQuantity("font", identity)


@atomic
def define(host, opening, meaning):
    from .read_streams import filename
    from ..tfm import parameters
    target = AssignmentScanner(host.reader, host.context).target()
    scanner = IntegerScanner(host, relaxed_target=(target.kind, target.value))
    scanner.optional_equals()
    name = filename(scanner)
    at, scaled = None, 1000
    if scanner.keyword("at"):
        at = dimension(scanner)
    elif scanner.keyword("scaled"):
        scaled = scanner.integer()
        if not 1 <= scaled <= 32768:
            raise ReadingIssue("font_size", "Font scale must be in 1..32768")
    scanner.finish()
    fonts = host.context.fonts
    if fonts.sources is None:
        raise ReadingIssue("font_inventory", "Font definition requires an explicit TFM inventory")
    data = fonts.sources.get(name, fonts.sources.get(name + ".tfm"))
    if data is None:
        raise ReadingIssue("font_metric", "Font metrics are absent from the supplied inventory")
    size, values = parameters(data, at=at, scaled=scaled)
    identity = f"{name.removesuffix('.tfm')}@{size}"
    span = host.reader.source_span(opening.span.start, host.reader.position)
    if identity not in fonts.values:
        fonts.establish(identity, values)
        fonts.identifiers[identity] = target.value
        for key, parameter in (("hyphenchar", "defaulthyphenchar"), ("skewchar", "defaultskewchar")):
            from .parameters import internal_value
            number = internal_value(scanner, PrimitiveMeaning("parameter.assign_integer", parameter)).value
            host.context.state_cells.assign(f"{key}:{identity}", number, span, global_=True)
    host.context.record_meaning(target.value, PrimitiveMeaning("font.identifier", identity, span), target.kind,
                                global_=assignment_global(host))
    return SourceCommand(span, opening.token.value, "meaning_assignment", metadata={"donor_resolved": True})


def property_address(scanner, meaning):
    if meaning.operand in {"textfont", "scriptfont", "scriptscriptfont"}:
        index = scanner.integer()
        if not 0 <= index <= 15:
            raise ReadingIssue("font_family", "Math font family must be in 0..15")
        return f"{meaning.operand}:{index}", True
    return f"{meaning.operand}:{font_identifier(scanner)}", False


def property_value(scanner, meaning):
    key, family = property_address(scanner, meaning)
    cells = scanner.host.context.state_cells
    if key not in cells.values and scanner.host.context.primitive_initial_state:
        result = cells.initial("nullfont" if family else -1 if key.startswith("skewchar:") else 45)
    else:
        result = cells.read(key)
    return InternalQuantity("font" if family else "integer", result)


@atomic
def assign_property(host, opening, meaning):
    scanner = IntegerScanner(host)
    key, family = property_address(scanner, meaning)
    scanner.optional_equals()
    result = font_identifier(scanner) if family else scanner.integer()
    scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.state_cells.assign(key, result, span, global_=assignment_global(host) if family else True)
    return SourceCommand(span, opening.token.value, "font_parameter_assignment",
                         metadata={"trailing_control_word": scanner.ends_control_word})


def font_identifier(scanner):
    token = scanner._nonspace()
    if token is None:
        raise ReadingIssue("font_identifier", "Expected an established font identifier")
    quantity = scanner.internal(token)
    if quantity.kind != "font":
        raise ReadingIssue("font_identifier", "Expected an established font identifier")
    return quantity.value


def address(scanner, *, writing=False):
    index = scanner.integer()
    identity = font_identifier(scanner)
    values = scanner.host.context.fonts.cell(identity, index, writing=writing)
    return identity, index, values


def value(scanner, meaning):
    identity, index, values = address(scanner)
    return InternalQuantity("dimension", values[index - 1])


@atomic
def assign(host, opening, meaning):
    scanner = IntegerScanner(host)
    identity, index, _ = address(scanner, writing=True)
    scanner.optional_equals()
    result = dimension(scanner)
    scanner.finish()
    host.context.fonts.assign(identity, index, result)
    span = host.reader.source_span(opening.span.start, host.reader.position)
    return SourceCommand(span, opening.token.value, "font_parameter_assignment",
                         metadata={"font": identity, "index": index, "value": result,
                                   "trailing_control_word": scanner.ends_control_word})


IDENTIFIER = PrimitiveOperation("font.identifier", ExpansionKind.UNEXPANDABLE, select, font_value, operand_type=str,
    accepted_prefixes=frozenset({"global"}))
DEFINE = PrimitiveOperation("font.define", ExpansionKind.UNEXPANDABLE, define, current, operand_type=type(None),
    accepted_prefixes=frozenset({"global"}))
PROPERTY = PrimitiveOperation("font.property", ExpansionKind.UNEXPANDABLE, assign_property, property_value,
    operand_type=str, accepted_prefixes=frozenset({"global"}))
ASSIGN = PrimitiveOperation("font.dimension", ExpansionKind.UNEXPANDABLE, assign, value,
    operand_type=type(None), accepted_prefixes=frozenset({"global"}))
FAMILY = OperationFamily((IDENTIFIER, ASSIGN, DEFINE, PROPERTY),
    (IDENTIFIER.declare("nullfont", "nullfont"), ASSIGN.declare("fontdimen", None), DEFINE.declare("font", None)) +
    tuple(PROPERTY.declare(name, name) for name in ("textfont", "scriptfont", "scriptscriptfont", "hyphenchar", "skewchar")))
