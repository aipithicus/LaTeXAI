"""Transactional bounded token programs using the existing dispatcher.

Each frozen input has a generated diagnostic coordinate basis and a separate
origin relation. Its tokens are copied, never retokenized from that display text.
Macro replacement frames execute in order against the same mutable context.
"""
from dataclasses import dataclass, replace

from .expansion import ExpansionCursor
from .requests import origin
from ..reading.contracts import (DeferredRegion, ReadingBoundary, ReadingIssue,
    ScannedArgument, SourceCommand, TokenArgument, TokenListMeaning)
from ..reading.spans import SourceBasis
from ..reading.tex_reader import CatCode, ReadEvent, TokenKind
from ..reading.token_cursor import TokenCursor


@dataclass(frozen=True, slots=True)
class ProgramSource:
    reader: TokenCursor
    anchor: object
    origins: tuple


@dataclass
class ProgramBudget:
    remaining: int

    def charge(self, amount=1):
        self.remaining -= amount
        if self.remaining < 0:
            raise ReadingIssue("program_budget", "Bounded token execution exhausted its shared work budget")


def frozen_reader(host, tokens, anchor):
    tokens = tuple(tokens)
    parts, offsets, position = [], [], 0
    for token in tokens:
        spelling = ("\\" + token.value + (" " if token.control_word else "")
                    if token.kind == TokenKind.CONTROL_SEQUENCE else token.value)
        parts.append(spelling)
        offsets.append((position, position + len(spelling)))
        position += len(spelling)
    host.program_serial += 1
    basis = SourceBasis(f"@evaluation/{host.program_serial}/{anchor.basis.source_id}",
                        -host.program_serial, position)
    rebased = tuple(replace(t, span=basis.span(a, b)) for t, (a, b) in zip(tokens, offsets))
    reader = TokenCursor(ScannedArgument("program", basis.whole, rebased), "".join(parts), host.context)
    host.program_sources.append(ProgramSource(reader, anchor, tuple(t.span for t in tokens)))
    return reader


def expand_call(host, event, definition):
    cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations)
    if isinstance(definition, TokenListMeaning):
        cursor.push(definition.replacement_tokens)
    else:
        cursor.expand_macro(event.token, definition)
    tokens = []
    while cursor.pending:
        tokens.append(cursor.next_token())
    span = host.reader.source_span(event.span.start, host.reader.position)
    return SourceCommand(span, event.token.value, "program_expand",
                         (TokenArgument("body", span, tuple(tokens)),))


def evaluate(host, tokens, anchor, *, registration_only=False, budget=10000):
    """Publish a supported program's state, or restore it completely.

    This consumer does no filesystem I/O, layout or general content projection.
    Groups may deliberately span a file event; the caller owns that continuation.
    """
    from ..reading.dispatcher import StructuralDispatcher
    depth = getattr(host, "program_depth", 0)
    if depth >= 48:
        raise ReadingIssue("program_budget", "Hook execution nesting exhausted its budget")
    saved_context, saved_units = host.context.copy(), host.units.checkpoint()
    fuel = getattr(host, "program_budget", None) or ProgramBudget(budget)
    saved_sources, saved_serial = len(host.program_sources), host.program_serial
    parent_groups, parent_conditionals = list(host._groups), [replace(c) for c in host._conditionals]
    try:
        reader = frozen_reader(host, tokens, anchor)
        child = StructuralDispatcher(reader, host.context, host.knowledge, preparation=True,
            source_commands=True, units=host.units, program=True)
        child._base_scope_depth = host._base_scope_depth
        child.program_depth = depth + 1
        child.program_budget = fuel
        child.options = host.options.copy() if host.options is not None else None
        child._groups, child._conditionals = list(parent_groups), [replace(c) for c in parent_conditionals]
        child.program_sources, child.program_serial = host.program_sources, host.program_serial
        results, registered = [], False
        while True:
            fuel.charge()
            item = child._next_item()
            if item is None:
                break
            if isinstance(item, (ReadingBoundary, DeferredRegion)):
                raise ReadingIssue(item.reason, item.detail, causes=getattr(item, "causes", ()))
            if isinstance(item, SourceCommand) and item.action == "program_expand":
                body = item.argument("body").tokens
                # Keep the unread frozen continuation available to operands in
                # the replacement: e.g. def a{b}; a{argument-for-b}. Nothing is
                # expanded ahead of intervening assignments or retokenized.
                tail = []
                while (token := child.reader.next_token()) is not None:
                    tail.append(token)
                fuel.charge(len(body) + len(tail))
                child._set_reader(frozen_reader(child, (*body, *tail), anchor))
                continue
            if registration_only:
                if isinstance(item, ReadEvent) and item.token.catcode == CatCode.SPACE:
                    continue
                if not isinstance(item, SourceCommand) or item.action not in {
                        "hook_register", "hook_remove", "hook_unresolved"}:
                    raise ReadingIssue("hook_program", "Invocation contains work beyond hook registration")
                registered = True
            elif isinstance(item, SourceCommand) and item.action not in {
                    "hook_register", "hook_remove", "hook_unresolved", "hook_use", "hook_diagnostic",
                    "meaning_assignment", "reading_assignment", "character_code_assignment",
                    "integer_parameter_assignment", "boolean_declaration", "conditional_test"}:
                raise ReadingIssue("hook_effect", f"Hook operation {item.action!r} needs an execution owner")
            results.append(item)
        if registration_only and not registered:
            raise ReadingIssue("hook_program", "Invocation performs no hook operation")
        if child._conditionals != parent_conditionals or child._pending_skip is not None:
            raise ReadingIssue("hook_conditional", "A hook program must complete its conditional scanning")
        host._groups = child._groups
        host.program_serial = child.program_serial
        host.reader.endline_char = host.context.endlinechar
        return tuple(results)
    except (ReadingIssue, ValueError) as error:
        current, previous = host.context.hooks, saved_context.hooks
        possible_hooks = tuple(name for name in (current.code.keys() | previous.code.keys()
                                                 | current.uncertain.keys() | previous.uncertain.keys())
            if current.code.get(name) != previous.code.get(name)
            or current.uncertain.get(name) != previous.uncertain.get(name))
        host.context.restore_from(saved_context)
        host.units.restore(saved_units)
        host._groups, host._conditionals = parent_groups, parent_conditionals
        del host.program_sources[saved_sources:]
        host.program_serial = saved_serial
        if isinstance(error, ReadingIssue):
            error.possible_hooks = tuple(dict.fromkeys((*getattr(error, "possible_hooks", ()), *possible_hooks)))
        raise


def registration_request(host, event, definition):
    """Probe one authored invocation, including all of its registration commands."""
    saved = host.reader.checkpoint()
    try:
        invocation = expand_call(host, event, definition)
        results = evaluate(host, invocation.argument("body").tokens, invocation.span, registration_only=True)
        return SourceCommand(invocation.span, event.token.value, "hook_program", metadata={
            "expanded_invocation": True,
            "trailing_control_word": invocation.span.end == event.span.end and event.token.control_word,
            "hooks": [r.metadata["hook"] for r in results],
            "definition": origin(definition.span)})
    except ReadingIssue as error:
        host.reader.restore(saved)
        for name in getattr(error, "possible_hooks", ()):
            host.context.hooks.invalidate(name, event.span)
        return None
