"""Declaration and meaning-assignment operations over shared reader state.

These retain the reader's bounded contracts: captures are not compiled macros,
and an unavailable donor remains unknown rather than becoming undefined.
"""
from dataclasses import dataclass, replace

from ..operations import ExecutableOperation, ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ..expansion import ExpansionCursor
from ..transactions import atomic, meaning_assignment_scope
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.argument_scanner import ArgumentScanner
from ...reading.boolean_scanner import declaration as boolean_declaration
from ...reading.contracts import (BooleanMeaning, BoundMeaning,
                                  EffectiveReadingProfile, ReadingIssue, UncertainMeaning, UndefinedMeaning)
from ...reading.definition_scanner import DefinitionScanner
from ...reading.environment_registry import declarations
from ...reading.environment_scanner import EnvironmentScanner
from ...reading.tex_reader import CatCode, TokenKind


@dataclass(frozen=True, slots=True)
class DefinitionSpec:
    global_: bool = False
    expanded: bool = False


@atomic
def assign_meaning(host, opening, profile: PrimitiveMeaning[None]):
    """Raw target, optional equals/space, raw donor; no operand expansion.

    Copy the donor's current meaning into local state. Return the captured
    assignment and donor-resolution evidence; never execute the donor.
    """
    context = host.context
    command = AssignmentScanner(host.reader, context).let(opening.span, ("\\" + opening.token.value))
    target, donor = (a.tokens[0] for a in command.arguments)
    copied = context.resolve_meaning(host.knowledge, donor.value, donor.kind)
    if copied is None:
        if donor.kind == TokenKind.CHARACTER:
            copied = BoundMeaning(command.span, token=donor)
        else:
            copied = UncertainMeaning(host.uncertainty_origin(command.span))
    elif isinstance(copied, (PrimitiveMeaning, BoundMeaning)) and copied.span is None:
        copied = replace(copied, span=command.span)
    global_, scope_cause = meaning_assignment_scope(host)
    context.record_meaning(target.value, copied, target.kind, global_=global_, scope_cause=scope_cause)
    if isinstance(copied, UncertainMeaning):
        host.units.uncertainty_cause(copied.span, "assignment_donor", "The donor's current meaning is not established")
    return replace(command, scope_cause=scope_cause, metadata={"donor_resolved": not isinstance(copied, UncertainMeaning),
        "trailing_control_word": donor.kind == TokenKind.CONTROL_SEQUENCE and bool(donor.value)
            and context.catcodes[donor.value[-1]] == CatCode.LETTER})


def capture_let(reader, context, token, meaning: PrimitiveMeaning[None]):
    return AssignmentScanner(reader, context).let(token.span, token.value)


def capture_definition(reader, context, token, meaning: PrimitiveMeaning[DefinitionSpec]):
    return DefinitionScanner(reader, context).primitive(token.span.start)


@atomic
def store_primitive_definition(host, opening, meaning: PrimitiveMeaning[DefinitionSpec]):
    from ..continuation import ContinuationReader
    scanner = DefinitionScanner(host.reader, host.context)
    expand = (lambda scanner, count: expanded_body(host, scanner, count)) if meaning.operand.expanded else None
    definition = scanner.primitive(opening.span.start, expand_body=expand)
    if isinstance(host.reader, ContinuationReader):
        definition = host.reader.enclose_definition(definition)
    definition = host.identify(definition)
    prefixes = getattr(host, "assignment_prefixes", ())
    definition = replace(definition, long="long" in prefixes, outer="outer" in prefixes, protected="protected" in prefixes)
    global_, scope_cause = meaning_assignment_scope(host, meaning.operand.global_)
    definition = replace(definition, scope_cause=scope_cause)
    host.context.record_definition(definition, global_=global_, scope_cause=scope_cause)
    return definition


def command_presence(context, knowledge, name):
    """Known undefined overrides fallback profiles; absent knowledge stays None."""
    meaning = context.resolve_meaning(knowledge, name)
    if isinstance(meaning, UndefinedMeaning) and meaning.uncertain is None:
        return False
    if meaning is not None:
        return True
    return None


def expanded_body(host, scanner, count):
    """Expand an edef replacement, committing no state before collection ends.

    Authored tokens and the evaluated replacement have separate identities.
    A closing delimiter from a replacement frame needs a persistent execution
    continuation and remains an explicit boundary in this initial consumer.
    """
    cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations, host=host, protect_macros=True)
    cursor.allow_name_assignment = True  # The definition request owns rollback.
    tokens, depth = [], 1
    while (token := cursor.next_expanded()) is not None:
        if token.catcode == CatCode.BEGIN_GROUP:
            depth += 1
        elif token.catcode == CatCode.END_GROUP:
            depth -= 1
            if depth == 0:
                if cursor.pending or not cursor.source_tokens or token is not cursor.source_tokens[-1]:
                    raise ReadingIssue("expanded_delimiter", "Expanded closing delimiter needs an execution continuation")
                return tuple(cursor.source_tokens[:-1]), token, tuple(tokens)
        tokens.append(token)
        if token.catcode == CatCode.PARAMETER:
            following = cursor.next_expanded()  # scan_toks uses get_x_token when xpand is true.
            scanner._replacement_parameter(following, count)
            tokens.append(following)
    raise ReadingIssue("unclosed_definition", "EOF while expanding a definition")


def store_environment(host, opening, profile):
    """Scan the collecting declaration raw, including signature and final code.

    Reject established target conflicts, then register the identified capture and
    its paired meanings locally. Return the capture without executing either body.
    """
    context, knowledge = host.context, host.knowledge
    definition = EnvironmentScanner(host.reader, context).definition(opening.span.start, profile)
    present = command_presence(context, knowledge, definition.name)
    end_present = command_presence(context, knowledge, "end" + definition.name)
    known = present is not False and (present is True or context.lookup_environment(definition.name) is not None
                                     or isinstance(knowledge.resolve_environment(definition.name), EffectiveReadingProfile))
    end_known = end_present is True
    if (known or end_known) and definition.target_requirement == "absent":
        raise ReadingIssue("definition_conflict", f"{definition.name!r} already has an established meaning")
    if present is False and definition.target_requirement == "present":
        raise ReadingIssue("definition_conflict", f"{definition.name!r} is established undefined")
    definition = host.identify(replace(definition, target_check="known_present" if known else
                                      "known_absent" if present is False and end_present is False else "unverified"))
    context.record_collected_environment(definition)
    return definition


def boolean_value(context, knowledge, name):
    """Read an established constant conditional meaning without expansion."""
    rule = context.conditional_rule(name.removeprefix("\\"), knowledge)
    if rule is None or rule.role != "opener" or rule.evaluation not in {"always_true", "always_false"}:
        raise ReadingIssue("unsupported_boolean_meaning", f"{name!r} has no established boolean value")
    return rule.evaluation == "always_true"


def declare_boolean(host, opening, profile):
    """Capture the raw boolean target using the resolved declaration grammar.

    Resolve its initial truth before installing the conditional and setters in
    local state. Return a declaration record, without expanding generated macros.
    """
    if not (profile.grammar.get("handler") == "boolean_declaration"
            and profile.state_management is not None and profile.state_management.scope == "local"):
        raise ReadingIssue("unsupported_boolean_declaration", "Boolean declaration needs a local recipe")
    command = boolean_declaration(host.reader, host.context, opening.span, profile)
    truth = boolean_value(host.context, host.knowledge, profile.grammar["initial"])
    target = command.metadata["target"]
    stem = target[len(profile.grammar["target_prefix"]):]
    host.context.record_meaning(target, BooleanMeaning(command.span, truth))
    for suffix, source in profile.grammar["setters"].items():
        host.context.record_meaning(stem + suffix, BooleanMeaning(command.span, target=target, source=source))
    return command


def declare_environment(host, opening, profile):
    """Scan a factory's raw arguments and register its declared local readers.

    Return the source command. Its bodies are not expanded or executed here.
    """
    command = ArgumentScanner(host.reader, host.context).read(opening.span, profile)
    for declaration in declarations(command, host.knowledge):
        host.context.record_environment(declaration)
    return command


ASSIGN = PrimitiveOperation("meaning.assign", ExpansionKind.UNEXPANDABLE, assign_meaning,
                            operand_type=type(None), capture=capture_let, continuation=True,
                            accepted_prefixes=frozenset({"global"}))
STORE = PrimitiveOperation("definition.store", ExpansionKind.UNEXPANDABLE, store_primitive_definition,
                           operand_type=DefinitionSpec, capture=capture_definition, continuation=True,
                           accepted_prefixes=frozenset({"global", "long", "protected"}))

FAMILY = OperationFamily(
    operations=(ASSIGN, STORE,
        ExecutableOperation[EffectiveReadingProfile]("definition.store_environment", ExpansionKind.INTERNAL, store_environment),
        ExecutableOperation[EffectiveReadingProfile]("definition.declare_boolean", ExpansionKind.INTERNAL, declare_boolean),
        ExecutableOperation[EffectiveReadingProfile]("definition.declare_environment", ExpansionKind.INTERNAL, declare_environment)),
    primitives=(ASSIGN.declare("let", None),
        *(STORE.declare(name, DefinitionSpec(global_, expanded)) for name, global_, expanded in
          (("def", False, False), ("gdef", True, False), ("edef", False, True), ("xdef", True, True)))),
)
