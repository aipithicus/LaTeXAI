"""Existing non-expanding declaration and meaning-assignment operations.

These retain the reader's bounded contracts: captures are not compiled macros,
and an unavailable donor remains unknown rather than becoming undefined.
"""
from dataclasses import replace

from ..operations import ExecutableOperation
from ...reading.assignment_scanner import AssignmentScanner
from ...reading.argument_scanner import ArgumentScanner
from ...reading.boolean_scanner import declaration as boolean_declaration
from ...reading.contracts import (BooleanMeaning, BoundMeaning, CommandDefinition,
                                  EffectiveReadingProfile, ReadingIssue, UncertainMeaning)
from ...reading.definition_scanner import DefinitionScanner
from ...reading.environment_registry import declarations
from ...reading.environment_scanner import EnvironmentScanner
from ...reading.tex_reader import CatCode, TokenKind


def assign_meaning(host, opening, profile):
    """Raw target, optional equals/space, raw donor; no operand expansion.

    Copy the donor's current meaning into local state. Return the captured
    assignment and donor-resolution evidence; never execute the donor.
    """
    context = host.context
    command = AssignmentScanner(host.reader, context).let(opening.span, profile)
    target, donor = (a.tokens[0] for a in command.arguments)
    copied = context.lookup_meaning(donor.value, donor.kind)
    if copied is None:
        if donor.kind == TokenKind.CHARACTER:
            copied = BoundMeaning(command.span, token=donor)
        else:
            donor_profile = host.knowledge.resolve_command(donor.value)
            copied = (BoundMeaning(command.span, profile=donor_profile)
                      if isinstance(donor_profile, EffectiveReadingProfile) else UncertainMeaning(command.span))
            if (isinstance(donor_profile, EffectiveReadingProfile) and donor_profile.conditional is not None
                    and donor_profile.conditional.evaluation in {"always_true", "always_false"}):
                copied = BooleanMeaning(command.span, donor_profile.conditional.evaluation == "always_true")
    context.record_meaning(target.value, copied, target.kind)
    if isinstance(copied, UncertainMeaning):
        host.units.uncertainty_cause(command.span, "assignment_donor", "The donor's current meaning is not established")
    return replace(command, metadata={"donor_resolved": not isinstance(copied, UncertainMeaning),
        "trailing_control_word": donor.kind == TokenKind.CONTROL_SEQUENCE and bool(donor.value)
            and context.catcodes[donor.value[-1]] == CatCode.LETTER})


def store_definition(host, opening, profile):
    """Scan target, signature and body raw; body tokens retain their catcodes.

    Check known target conflicts, identify the capture, then install it locally.
    Return that same capture; neither execute its body nor prove unknown names absent.
    """
    definition = DefinitionScanner(host.reader, host.context).read(opening.span.start, profile)
    if isinstance(definition, CommandDefinition):
        known = (host.context.lookup_meaning(definition.target.value) is not None
                 or isinstance(host.knowledge.resolve_command(definition.target.value), EffectiveReadingProfile))
        if known and definition.target_requirement == "absent":
            raise ReadingIssue("definition_conflict", f"{definition.target.value!r} already has an established meaning")
        definition = replace(definition, target_check="known_present" if known else "unverified")
    definition = host.identify(definition)
    host.context.record_definition(definition)
    return definition


def store_environment(host, opening, profile):
    """Scan the collecting declaration raw, including signature and final code.

    Reject established target conflicts, then register the identified capture and
    its paired meanings locally. Return the capture without executing either body.
    """
    context, knowledge = host.context, host.knowledge
    definition = EnvironmentScanner(host.reader, context).definition(opening.span.start, profile)
    known = (context.lookup_environment(definition.name) is not None
             or context.lookup_meaning(definition.name) is not None
             or isinstance(knowledge.resolve_environment(definition.name), EffectiveReadingProfile)
             or isinstance(knowledge.resolve_command(definition.name), EffectiveReadingProfile))
    end_known = (context.lookup_meaning("end" + definition.name) is not None
                 or isinstance(knowledge.resolve_command("end" + definition.name), EffectiveReadingProfile))
    if (known or end_known) and definition.target_requirement == "absent":
        raise ReadingIssue("definition_conflict", f"{definition.name!r} already has an established meaning")
    definition = host.identify(replace(definition, target_check="known_present" if known else "unverified"))
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


OPERATIONS = (
    ExecutableOperation("meaning.assign", assign_meaning),
    ExecutableOperation("definition.store", store_definition),
    ExecutableOperation("definition.store_environment", store_environment),
    ExecutableOperation("definition.declare_boolean", declare_boolean),
    ExecutableOperation("definition.declare_environment", declare_environment),
)
