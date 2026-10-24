"""Capture a bounded boolean declaration; execution stays in the dispatcher.

The LaTeX kernel's ltdefns.dtx defines newif as a one-argument macro. This
scanner accepts a single control-sequence token, optionally in a brace group,
without expanding a computed target. Naming and setter recipes come from YAML.
"""
from .context import ExecutionMode
from .contracts import ReadingIssue, SourceCommand
from .tex_reader import CatCode, TokenKind


def declaration(reader, context, opening, profile):
    if (context.mode != ExecutionMode.ACTIVE_EXECUTION or reader.catcodes is not context.catcodes
            or reader.endline_char != context.endlinechar):
        raise ReadingIssue("inactive_context", "Boolean declaration requires the active shared reader")
    with context.argument_scanning():
        target = reader.next_token()
        while target is not None and target.catcode == CatCode.SPACE:
            target = reader.next_token()
        braced = target is not None and target.catcode == CatCode.BEGIN_GROUP
        if braced:
            target = reader.next_token()
        if target is None or target.kind != TokenKind.CONTROL_SEQUENCE:
            raise ReadingIssue("unsupported_boolean_target", "Expected one literal control-sequence target")
        closing = reader.next_token() if braced else target
        if closing is None or (braced and closing.catcode != CatCode.END_GROUP):
            raise ReadingIssue("unsupported_boolean_target", "A braced boolean target must contain exactly one token")
        prefix = profile.grammar["target_prefix"]
        if not target.value.startswith(prefix) or len(target.value) == len(prefix):
            raise ReadingIssue("unsupported_boolean_target", f"Boolean target must start with {prefix!r} and have a name")
    return SourceCommand(reader.source_span(opening.start, closing.span.end), profile.name,
                         "boolean_declaration", metadata={"target": target.value, "unbraced": not braced})
