"""Local code assignments and internal catcode values, using shared scanning."""
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.contracts import CharacterCodeMeaning, ReadingIssue, ScannedArgument, SourceCommand
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import AssignmentTarget, PrimitiveMeaning
from ..quantities import InternalQuantity
from ..transactions import atomic, assignment_global


def character_index(scanner):
    value = scanner.integer()
    # Preserve the existing reader's Unicode category-table domain. chardef
    # below deliberately retains the narrower TeX82/e-TeX character-code range.
    if not 0 <= value <= 0x10FFFF:
        raise ReadingIssue("invalid_assignment", "Category-table character index is out of range")
    return chr(value)


def catcode_value(scanner, profile: PrimitiveMeaning[None]):
    return InternalQuantity("integer", int(scanner.host.context.catcodes[character_index(scanner)]))


@atomic
def assign_catcode(host, opening, profile: PrimitiveMeaning[None]):
    scanner = IntegerScanner(host)
    with host.context.argument_scanning():
        character = character_index(scanner)
        scanner.optional_equals()
        category = scanner.integer()
        if not 0 <= category <= 15:
            raise ReadingIssue("invalid_assignment", "Category number is out of range")
        scanner.finish()
    host.context.assign_catcode(character, category, global_=assignment_global(host))
    return SourceCommand(host.reader.source_span(opening.span.start, host.reader.position),
                         ("\\" + opening.token.value), "reading_assignment",
                         metadata={"character": character, "category": category,
                                   **({"trailing_control_word": True} if scanner.ends_control_word else {})})


@atomic
def define_character_code(host, opening, profile: PrimitiveMeaning[None]):
    with host.context.argument_scanning():
        target = AssignmentScanner(host.reader, host.context).target()
        scanner = IntegerScanner(host, relaxed_target=(target.kind, target.value))
        scanner.optional_equals()
        value = scanner.integer()
        if not 0 <= value <= 255:
            raise ReadingIssue("invalid_assignment", "chardef value is outside 0..255")
        scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.record_meaning(target.value, CharacterCodeMeaning(span, value), target.kind, global_=assignment_global(host))
    return SourceCommand(span, ("\\" + opening.token.value), "character_code_assignment",
                         (ScannedArgument("target", target.span, (target,), "data"),),
                         {"value": value, "trailing_control_word": scanner.ends_control_word})


def capture_character_target(reader, context, token, meaning: PrimitiveMeaning[None]):
    with context.argument_scanning():
        return AssignmentTarget(AssignmentScanner(reader, context).target())


@atomic
def define_math_character(host, opening, meaning):
    target = AssignmentScanner(host.reader, host.context).target()
    scanner = IntegerScanner(host, relaxed_target=(target.kind, target.value))
    scanner.optional_equals()
    number = scanner.integer()
    if not 0 <= number <= 32767:
        raise ReadingIssue("invalid_assignment", "mathchardef value is outside 0..32767")
    scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.record_meaning(target.value, PrimitiveMeaning("math.character", number, span), target.kind,
                                global_=assignment_global(host))
    return SourceCommand(span, opening.token.value, "character_code_assignment")


def math_character(host, opening, meaning):
    if getattr(host, "content", None) is not None:
        host.content.math_character(host, meaning.operand, opening.span)
        return SourceCommand(opening.span, opening.token.value, "content")
    raise ReadingIssue("math_character", "Math character execution requires a math list consumer")


def math_character_value(scanner, meaning):
    return InternalQuantity("integer", meaning.operand)


CATCODE = PrimitiveOperation("reading.assign_catcode", ExpansionKind.UNEXPANDABLE, assign_catcode,
                             catcode_value, operand_type=type(None), accepted_prefixes=frozenset({"global"}))
CHARDEF = PrimitiveOperation("meaning.define_character_code", ExpansionKind.UNEXPANDABLE, define_character_code,
                             operand_type=type(None), capture=capture_character_target,
                             accepted_prefixes=frozenset({"global"}))

MATHCHARDEF = PrimitiveOperation("meaning.define_math_character", ExpansionKind.UNEXPANDABLE, define_math_character,
    operand_type=type(None), accepted_prefixes=frozenset({"global"}))
MATHCHAR = PrimitiveOperation("math.character", ExpansionKind.UNEXPANDABLE, math_character, math_character_value,
    operand_type=int)
FAMILY = OperationFamily(
    operations=(CATCODE, CHARDEF, MATHCHARDEF, MATHCHAR),
    primitives=(CATCODE.declare("catcode", None), CHARDEF.declare("chardef", None),
                MATHCHARDEF.declare("mathchardef", None)),
)
