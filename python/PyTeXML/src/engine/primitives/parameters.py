"""Integer parameters: optional expanded equals, expanded integer, local write.

The internal-value role reads the same cell without assigning it. The operation
returns an authored source command; preparation preserves it for later layout or
backend execution. Output mode is not selected by this evaluator.

References: TeX82 tex.web and pdftexdir/pdftex.web, assign_int/word_define.
"""
from ...reading.contracts import ReadingIssue, SourceCommand
from ..integers import IntegerScanner
from ..operations import ExecutableOperation


def parameter_key(profile):
    key = profile.tex_mechanics.get("parameter")
    if (profile.grammar != {"handler": "integer_parameter_assignment"}
            or profile.state_management is None or profile.state_management.scope != "local"
            or not isinstance(key, str) or not key or key.startswith("\\")):
        raise ReadingIssue("unsupported_parameter", "Integer parameter requires an explicit cell identity and local grammar")
    return key


def integer_value(scanner, profile):
    return scanner.host.context.integer_parameters.read(parameter_key(profile))


def assign_integer(host, opening, profile):
    key = parameter_key(profile)
    scanner = IntegerScanner(host)
    with host.context.argument_scanning():
        scanner.optional_equals()
        value = scanner.integer()
        scanner.finish()
    span = host.reader.source_span(opening.span.start, host.reader.position)
    host.context.integer_parameters.assign(key, value, span)
    return SourceCommand(span, profile.name, "integer_parameter_assignment",
                         metadata={"parameter": key, "value": value,
                                   "trailing_control_word": scanner.ends_control_word,
                                   "source_reference": profile.tex_mechanics["source_reference"]})


OPERATIONS = (
    ExecutableOperation("parameter.assign_integer", assign_integer, integer_value, unexpandable=True),
)
