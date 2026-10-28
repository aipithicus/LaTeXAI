"""Complete bounded source-request operands using the shared expansion cursor.

Expansion is pure. The existing preparation owner resolves/loads the package
only after this probe succeeds; a failed probe publishes no effects.
"""
from dataclasses import replace

from .expansion import ExpansionCursor
from ..reading.argument_scanner import ArgumentScanner, group_tokens
from ..reading.contracts import ReadingIssue, ScannedArgument, TokenArgument
from ..reading.token_cursor import TokenCursor
from ..reading.tex_reader import CatCode, TexReader


def origin(span):
    return {"source": span.basis.source_id, "occurrence": span.basis.occurrence_id,
            "start": span.start, "end": span.end}


def expand_literal_argument(host, argument, *, strip_spaces=False):
    """Expand a bounded token argument; no physical-input continuation or effects.

    A replacement frame can contain tokens from many source occurrences. The
    empty base cursor supplies an anchor only, never a synthetic source slice.
    """
    source = TokenCursor(ScannedArgument(argument.name, argument.span, ()), "", host.context)
    cursor = ExpansionCursor(source, host.context, host.knowledge, host.operations)
    cursor.push(t for t in argument.tokens if not strip_spaces or t.catcode != CatCode.SPACE)
    tokens = []
    while (token := cursor.next_expanded()) is not None:
        tokens.append(token)
    result = TokenArgument(argument.name, argument.span, tuple(tokens),
                           argument.role, argument.literal_categories)
    result.literal()  # A request must be completely resolved before publication.
    return result


def forwarding_request(host, command):
    arguments = tuple(expand_literal_argument(host, arg, strip_spaces=arg.name == "options")
                      for arg in command.arguments)
    # zap@space removes source spaces before expansion. Spaces introduced by a
    # replacement have different kernel semantics; do not silently erase them.
    if any(t.catcode == CatCode.SPACE for arg in arguments if arg.name == "options" for t in arg.tokens):
        raise ReadingIssue("option_expansion", "Expansion-produced option spaces require further resolution")
    return replace(command, arguments=arguments)


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
