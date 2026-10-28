"""Local code assignments and internal catcode values, using shared scanning."""
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.contracts import CharacterCodeMeaning, ReadingIssue, ScannedArgument, SourceCommand
from ..integers import IntegerScanner
from ..operations import ExecutableOperation
from ..primitive import AssignmentTarget


def character_index(scanner):
    value = scanner.integer()
    # Preserve the existing reader's Unicode category-table domain. chardef
    # below deliberately retains the narrower TeX82/e-TeX character-code range.
    if not 0 <= value <= 0x10FFFF:
        raise ReadingIssue("invalid_assignment", "Category-table character index is out of range")
    return chr(value)


def catcode_value(scanner, profile):
    return int(scanner.host.context.catcodes[character_index(scanner)])


def assign_catcode(host, opening, profile):
    scanner = IntegerScanner(host)
    with host.context.argument_scanning():
        character = character_index(scanner)
        scanner.optional_equals()
        category = scanner.integer()
        if not 0 <= category <= 15:
            raise ReadingIssue("invalid_assignment", "Category number is out of range")
        scanner.finish()
    host.context.catcodes[character] = category
    return SourceCommand(host.reader.source_span(opening.span.start, host.reader.position),
                         ("\\" + opening.token.value), "reading_assignment",
                         metadata={"character": character, "category": category,
                                   **({"trailing_control_word": True} if scanner.ends_control_word else {})})


def define_character_code(host, opening, profile):
    with host.context.argument_scanning():
        target = AssignmentScanner(host.reader, host.context).target()
        scanner = IntegerScanner(host, relaxed_target=(target.kind, target.value))
        scanner.optional_equals()
        value = scanner.integer()
        if not 0 <= value <= 255:
            raise ReadingIssue("invalid_assignment", "chardef value is outside 0..255")
        scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.record_meaning(target.value, CharacterCodeMeaning(span, value), target.kind)
    return SourceCommand(span, ("\\" + opening.token.value), "character_code_assignment",
                         (ScannedArgument("target", target.span, (target,), "data"),),
                         {"value": value, "trailing_control_word": scanner.ends_control_word})


def capture_character_target(reader, context, token, meaning):
    with context.argument_scanning():
        return AssignmentTarget(AssignmentScanner(reader, context).target())


OPERATIONS = (
    ExecutableOperation("reading.assign_catcode", assign_catcode, catcode_value, unexpandable=True),
    ExecutableOperation("meaning.define_character_code", define_character_code, unexpandable=True,
                        capture=capture_character_target),
)
