"""Resolve scoped environment declarations against declarative package recipes."""
from dataclasses import replace
import re

from .argument_scanner import key_values
from .contracts import EnvironmentDeclaration, EnvironmentDefinition, ReadingIssue, SpanClassification, require_resolved


def declarations(command, knowledge):
    """Build declarations without installing them; execution routing owns scope."""
    recipe = command.metadata
    name = command.value(recipe["name_argument"])
    if not name or any(c.isspace() or c in "\\{}" for c in name):
        raise ReadingIssue("environment_name", "Factory requires a literal nonempty environment name")
    base = command.value(recipe["base_argument"]) if "base_argument" in recipe else recipe["base"]
    options = key_values(command.argument(recipe["options_argument"])) if "options_argument" in recipe else {}
    profile = require_resolved(knowledge.resolve_environment(base, options))
    if profile.binding_id != recipe["base_binding"]:
        raise ReadingIssue("factory_base", "Base environment is outside this factory's binding contract")
    classification = SpanClassification(**recipe["classification"]) if "classification" in recipe else None
    result = []
    for variant in recipe["variants"]:
        new_name = name + variant["suffix"]
        require_resolved(knowledge.resolve_environment(base, {**options, **variant["options"]}))
        result.append(EnvironmentDeclaration(new_name, base, {**options, **variant["options"]},
            recipe["terminator"]["exact_string"].format(name=new_name),
            recipe["terminator"]["regex_pattern"].format(name=re.escape(new_name)),
            profile.binding_id, command.span, classification))
    return result


def resolve_environment(name, options, context, knowledge):
    declaration = context.lookup_environment(name)
    if declaration is None:
        return knowledge.resolve_environment(name, options)
    if isinstance(declaration, EnvironmentDefinition):
        raise ReadingIssue("environment_collector", "Collected environment requires token collection, not a literal profile")
    profile = require_resolved(knowledge.resolve_environment(declaration.base, {**declaration.options, **(options or {})}))
    if profile.binding_id != declaration.binding_id:
        raise ReadingIssue("factory_base", "Base environment binding changed after factory registration")
    return replace(profile, name=name,
        terminator=replace(profile.terminator, exact_string=declaration.exact_terminator,
                           regex_pattern=declaration.regex_terminator),
        span_classification=declaration.classification or profile.span_classification)
