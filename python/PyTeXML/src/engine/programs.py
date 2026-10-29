"""Transactional bounded token programs using the existing dispatcher.

Each frozen input has a generated diagnostic coordinate basis and a separate
origin relation. Its tokens are copied, never retokenized from that display text.
Macro replacement frames execute in order against the same mutable context.
"""
from dataclasses import dataclass, replace

from .expansion import ExpansionCursor
from .requests import origin
from .primitive import PrimitiveMeaning
from ..reading.contracts import (BooleanMeaning, BoundMeaning, DeferredRegion,
    EffectiveReadingProfile, EnvironmentDefinition, ReadingBoundary, ReadingIssue,
    ScannedArgument, SkippedRegion, SourceCommand, StoredDefinition, TokenArgument, TokenListMeaning)
from ..reading.spans import SourceBasis
from ..reading.tex_reader import CatCode, ReadEvent, TokenKind
from ..reading.token_cursor import TokenCursor


@dataclass(frozen=True, slots=True)
class ProgramSource:
    reader: TokenCursor
    anchor: object
    origins: tuple


def source_origin(sources, span):
    """Locate a causal effect in authored tokens, even after probe rollback.

    One generated extent may combine a definition and its actual arguments.
    Enclose origins sharing a source occurrence; otherwise use the invocation
    anchor. Follow frozen-frame relations without parsing diagnostic text.
    """
    if not sources or span.basis.occurrence_id >= 0:
        return span  # Physical-source effects need no program-origin lookup.
    by_basis = {source.reader.basis: source for source in sources}
    while (source := by_basis.get(span.basis)) is not None:
        origins = [origin for token, origin in zip(source.reader.tokens, source.origins)
                   if token.span.start < span.end and token.span.end > span.start]
        if (origins and all(origin.basis == origins[0].basis for origin in origins)
                and all(a.end <= b.start for a, b in zip(origins, origins[1:]))):
            span = origins[0].basis.span(min(s.start for s in origins), max(s.end for s in origins))
        else:
            span = source.anchor
    return span


@dataclass
class ProgramBudget:
    remaining: int

    def charge(self, amount=1):
        self.remaining -= amount
        if self.remaining < 0:
            raise ReadingIssue("program_budget", "Bounded token execution exhausted its shared work budget")


# These are results whose execution is owned by the dispatcher, not requests for
# preparation's filesystem, package loader or content projection to execute.
PROGRAM_ACTIONS = frozenset({
    "hook_register", "hook_remove", "hook_unresolved", "hook_use", "hook_diagnostic",
    "meaning_assignment", "reading_assignment", "character_code_assignment",
    "integer_parameter_assignment", "boolean_declaration", "conditional_test", "reading_noop"})


@dataclass(frozen=True, slots=True)
class ProgramPolicy:
    name: str
    content: bool
    balanced_groups: bool

    def accept(self, item, host):
        if isinstance(item, SourceCommand):
            accepted = item.action in PROGRAM_ACTIONS
        elif (not self.content and isinstance(item, (StoredDefinition, EnvironmentDefinition))
              and getattr(item, "target_check", None) == "unverified"):
            # Top-level declarations carry a separate target-existence
            # requirement. A private setup probe cannot quietly discharge it.
            accepted = False
        elif isinstance(item, (StoredDefinition, EnvironmentDefinition, SkippedRegion)):
            accepted = True
        elif isinstance(item, ReadEvent):
            accepted = self.content or _setup_event(item, host)
        else:
            accepted = False
        if not accepted:
            raise ReadingIssue("program_effect", f"{self.name} cannot execute {getattr(item, 'action', type(item).__name__)!r}")


HOOK_BODY = ProgramPolicy("Hook body", content=True, balanced_groups=False)
SETUP = ProgramPolicy("Setup invocation", content=False, balanced_groups=True)


def _setup_event(item, host):
    """Only dispatcher-applied structural events, never literal output/modes.

    Most operations return typed commands. These existing event-returning
    operations retain the mouth event; recognize their resolved meanings rather
    than spellings, so aliases obey the same contract. A changed meaning that no
    longer proves this contract conservatively rejects the entire request.
    """
    token = item.token
    if token is None or token.catcode in {CatCode.SPACE, CatCode.BEGIN_GROUP, CatCode.END_GROUP}:
        return True
    meaning = host.context.resolve_meaning(host.knowledge, token.value, token.kind)
    if isinstance(meaning, BooleanMeaning):
        return meaning.uncertain is None
    if isinstance(meaning, PrimitiveMeaning):
        return meaning.uncertain is None and meaning.operation in {"scope.begin", "scope.end"}
    profile = meaning.profile if isinstance(meaning, BoundMeaning) else host.knowledge.resolve_command(token.value)
    return (isinstance(profile, EffectiveReadingProfile)
            and profile.family in {"assign_catcode", "expl3_lexical_enter", "expl3_lexical_exit"}
            and profile.action in {"assign_catcode", "expl3_lexical_enter", "expl3_lexical_exit"})


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
        cursor.expand_macro(event.token, definition, execution=True)
    tokens = []
    while cursor.pending:
        tokens.append(cursor.next_token())
    span = host.reader.source_span(event.span.start, host.reader.position)
    last = cursor.source_tokens[-1] if cursor.source_tokens else event.token
    return SourceCommand(span, event.token.value, "program_expand",
                         (TokenArgument("body", span, tuple(tokens)),), metadata={
                             "trailing_control_word": last.control_word and last.span.end == span.end})


def evaluate(host, tokens, anchor, *, policy=None, budget=10000):
    """Publish a supported program's state, or restore it completely.

    This consumer does no filesystem I/O, layout or general content projection.
    Groups may deliberately span a file event; the caller owns that continuation.
    """
    from ..reading.dispatcher import StructuralDispatcher
    policy = policy or getattr(host, "program_policy", HOOK_BODY)
    depth = getattr(host, "program_depth", 0)
    if depth >= 48:
        raise ReadingIssue("program_budget", "Token program nesting exhausted its budget")
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
        child.program_policy = policy
        child.options = host.options.copy() if host.options is not None else None
        child._groups, child._conditionals = list(parent_groups), [replace(c) for c in parent_conditionals]
        child.program_sources, child.program_serial = host.program_sources, host.program_serial
        results = []
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
            policy.accept(item, child)
            results.append(item)
        if child._conditionals != parent_conditionals or child._pending_skip is not None:
            raise ReadingIssue("program_conditional", "A token program must complete its conditional scanning")
        if policy.balanced_groups and child._groups != parent_groups:
            raise ReadingIssue("program_scope", "A setup invocation must restore its entry group stack")
        host._groups = child._groups
        host.program_serial = child.program_serial
        host.reader.endline_char = host.context.endlinechar
        return tuple(results)
    except (ReadingIssue, ValueError) as error:
        if isinstance(error, ReadingIssue):
            error.causes = tuple(dict.fromkeys(source_origin(host.program_sources, span) for span in error.causes))
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


def setup_request(host, event, definition):
    """Execute a complete bounded setup invocation, preserving its runtime source."""
    saved = host.reader.checkpoint()
    try:
        invocation = expand_call(host, event, definition)
        results = evaluate(host, invocation.argument("body").tokens, invocation.span, policy=SETUP)
        return SourceCommand(invocation.span, event.token.value, "setup_program", metadata={
            "expanded_invocation": True,
            "trailing_control_word": invocation.metadata["trailing_control_word"],
            "hooks": [r.metadata["hook"] for r in results
                      if isinstance(r, SourceCommand) and "hook" in r.metadata],
            "definition": origin(definition.span)})
    except ReadingIssue as error:
        host.reader.restore(saved)
        if error.reason == "argument_lookahead":
            # The invocation's end is not established. Ordinary deferral may
            # otherwise route caller tokens that still belong to its operands.
            raise
        for name in getattr(error, "possible_hooks", ()):
            host.context.hooks.invalidate(name, event.span)
        return None
