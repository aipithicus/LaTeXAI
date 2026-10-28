"""Accept one completed package request from a bounded macro invocation.

Expansion is pure. The existing preparation owner resolves/loads the package
only after this probe succeeds; a failed probe publishes no effects.
"""
from dataclasses import replace

from .expansion import ExpansionCursor
from ..reading.argument_scanner import ArgumentScanner, group_tokens
from ..reading.contracts import ReadingIssue, TokenArgument
from ..reading.tex_reader import CatCode, TexReader


def origin(span):
    return {"source": span.basis.source_id, "occurrence": span.basis.occurrence_id,
            "start": span.start, "end": span.end}


class _RequestArguments(ArgumentScanner):
    def __init__(self, cursor, context, invocation):
        super().__init__(cursor, context)
        self.invocation = invocation

    def _group_contents(self, name, opening, *, optional=False):
        tokens, _ = group_tokens(self.reader, name, optional=optional)
        return TokenArgument(name, self.invocation, tokens)

    def command_span(self, opening):
        return self.invocation.basis.span(self.invocation.start,
            max(self.invocation.end, self.reader.source.position))


def package_request(host, event):
    if not isinstance(host.reader, TexReader):
        return None  # Frozen replay has its own continuation owner.
    saved = host.reader.checkpoint()
    cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations)
    cursor.push((event.token,))
    selected = None

    def stop(profile):
        nonlocal selected
        if profile.family == "source_command" and profile.action == "package_load":
            selected = profile
            return True
        return False

    try:
        token = cursor.next_expanded(stop=stop)
        if token is None or selected is None:
            raise ReadingIssue("macro_request", "Invocation is not a package request")
        if (selected.grammar.get("handler") != "source_arguments"
                or "starred_arguments" in selected.grammar
                or any(spec["kind"] not in {"braced", "optional"} for spec in selected.grammar["arguments"])):
            raise ReadingIssue("macro_request", "Unsupported token-argument request grammar")
        command = _RequestArguments(cursor, host.context, event.span).read(event.span, selected)
        for argument in command.arguments:
            argument.literal()
        while cursor.pending:
            if cursor.next_token().catcode != CatCode.SPACE:
                raise ReadingIssue("macro_request", "Invocation has additional execution after its request")
        return replace(command, metadata={**command.metadata,
            "expanded_invocation": True,
            "trailing_control_word": command.span.end == event.span.end and event.token.control_word,
            "expansion_calls": [{"invocation": origin(call.invocation.span),
                                 "definition": origin(call.definition.span)} for call in cursor.calls]})
    except ReadingIssue:
        host.reader.restore(saved)
        return None
