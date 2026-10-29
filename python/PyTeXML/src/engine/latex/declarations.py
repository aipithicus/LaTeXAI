"""Adapt ltdefns.dtx's new/renew/provide command operations in Python.

CommandDefinition remains an authored observation. The ordinary meaning table
holds the constructed primitive macro(s), including the actual optional wrapper.
"""
from dataclasses import replace

from ..operations import ExecutableOperation, ExpansionKind, OperationFamily
from ..primitive import PrimitiveMeaning
from ..transactions import atomic, meaning_assignment_scope
from ..meanings import token_key
from .construction import control, character, parameter, group, definition
from ...reading.contracts import (EffectiveReadingProfile, StateManagementRule,
    ReadingIssue, UndefinedMeaning, UncertainMeaning, OptionalInvocation)
from ...reading.definition_scanner import DefinitionScanner


def grammar(name, requirement):
    return EffectiveReadingProfile('\\' + name, 'format_declaration',
        binding_id='latex-python/2026-06-01', state_management=StateManagementRule(scope='local'),
        grammar={'handler': 'command_definition', 'expansion': 'none',
                 'target_requirement': requirement,
                 'forbidden_names': ['relax'] if requirement == 'absent' else [],
                 'forbidden_prefixes': ['end'] if requirement == 'absent' else []})


PROFILES = {name: grammar(name, requirement) for name, requirement in
            [('newcommand', 'absent'), ('renewcommand', 'present'), ('providecommand', 'either')]}


@atomic
def declare(host, opening, profile):
    observed = DefinitionScanner(host.reader, host.context).read(opening.span.start, profile)
    context, target = host.context, observed.target
    current = context.resolve_meaning(host.knowledge, target.value)
    absent = isinstance(current, UndefinedMeaning) and current.uncertain is None or (
        isinstance(current, PrimitiveMeaning) and current.operation == 'execution.relax')
    uncertain = isinstance(current, UncertainMeaning) or getattr(current, 'uncertain', None) is not None
    known = current is not None and not absent and not uncertain
    requirement = observed.target_requirement
    if known and requirement == 'absent' or absent and requirement == 'present':
        raise ReadingIssue('definition_conflict', f'{target.value!r} violates the declaration target requirement')
    if requirement == 'either' and absent and (target.value == 'relax' or target.value.startswith('end')):
        raise ReadingIssue('invalid_definition_target', f'{target.value!r} is not a legal new command name')
    observed = host.identify(replace(observed,
        target_check='known_absent' if absent else 'known_present' if known else 'unverified'))
    global_, scope_cause = meaning_assignment_scope(host)
    # @star@or@long resets these on every declaration, including a provide
    # whose target already exists. Never let an old scratch value survive.
    context.record_meaning('pr@tectedrel@x', PrimitiveMeaning('execution.relax', None),
                           global_=global_, scope_cause=scope_cause)
    context.record_meaning('l@ngrel@x', context.resolve_meaning(host.knowledge,
                           'relax' if observed.starred else 'long'), global_=global_, scope_cause=scope_cause)
    # Their precise private token templates are outside this adaptation's
    # current contract. Mark those writes explicitly, with normal restoration.
    for name in ('reserved@a', 'reserved@b', 'reserved@c', 'reserved@d', '@let@token'):
        context.record_meaning(name, UncertainMeaning(observed.span), global_=global_, scope_cause=scope_cause)
    if requirement in ('present', 'either'):
        temp_scope, temp_cause = meaning_assignment_scope(host, default=True)
        temp_body = group(tuple(character(c, observed.target.span) for c in target.value), observed.target.span)
        context.record_definition(definition(host, control('@gtempa', observed.span), (), temp_body, observed.span),
                                  global_=temp_scope, scope_cause=temp_cause)
        context.record_meaning('@ifdefinable', UncertainMeaning(observed.span),
                               global_=global_, scope_cause=scope_cause)
    if requirement == 'either' and not (known or absent):
        context.record_meaning(target.value, UncertainMeaning(observed.span), global_=global_, scope_cause=scope_cause)
        return observed
    if requirement == 'either' and known:
        return observed
    parameters = tuple(t for number in range(1, observed.parameter_count + 1)
                       for t in parameter(number, observed.parameter_text))
    # @yargd@f applies l@ngrel@x only when the arity is nonzero.
    long = bool(observed.parameter_count) and not observed.starred
    if observed.optional_default is None:
        value = definition(host, target, parameters, observed.body_tokens, observed.span, long=long)
    else:
        from ..token_text import escape
        hidden_name = escape(context) + target.value
        hidden = control(hidden_name, observed.target.span)
        hidden_parameters = (character('[', observed.parameter_text), *parameters[:2],
                             character(']', observed.parameter_text), *parameters[2:])
        implementation = definition(host, hidden, hidden_parameters, observed.body_tokens, observed.span, long=long)
        context.record_definition(implementation, global_=global_, scope_cause=scope_cause)
        body = (control('@protected@testopt', observed.span), target, hidden,
                *group(observed.optional_default.tokens, observed.optional_default.span))
        value = definition(host, target, (), body, observed.span)
        value = replace(value, optional_invocation=OptionalInvocation(observed.parameter_count,
            hidden_name, tuple(map(token_key, implementation.parameter_tokens)), long))
    context.record_definition(replace(value, scope_cause=scope_cause), global_=global_, scope_cause=scope_cause)
    return replace(observed, scope_cause=scope_cause)


DECLARE = ExecutableOperation('format.declare_command', ExpansionKind.INTERNAL, declare)
FAMILY = OperationFamily((DECLARE,), ())
