"""Observe dependency syntax in captured tokens; never execute those tokens.

Argument roles come from the active grammar. Unknown/stored code can mention a
dependency, whereas diagnostic/data arguments cannot dispatch a file request.
The explicit stack shares source buffers and avoids recursive macro evaluation.
"""
from dataclasses import replace

from .argument_scanner import ArgumentScanner
from .contracts import EffectiveReadingProfile, ReadingIssue, ScannedArgument, StoredDefinition
from .definition_scanner import DefinitionScanner
from .token_cursor import TokenCursor
from .tex_reader import TokenKind


DEPENDENCY_ACTIONS = frozenset({"source_input", "source_include", "source_import", "source_subimport",
    "asset_reference", "bibliography", "biblatex_resource", "biblatex_print", "package_load",
    "document_class", "external_literal"})


def argument_activity(role):
    return "data" if role in {"data", "diagnostic"} else "stored" if role == "stored" else "unresolved"


def observe_dependencies(argument, text, context, knowledge, units, owner_id, *, excluded=()):
    """Yield (token, unit id, action, role, captured header) without execution."""
    excluded = set(excluded)
    pending = [(argument, owner_id, set())]
    while pending:
        arg, owner, shadowed = pending.pop()
        if arg.role in {"data", "diagnostic"}:
            continue
        cursor = TokenCursor(arg, text, context)
        scanner = ArgumentScanner(cursor, context)
        while (token := cursor.next_token()) is not None:
            if token.kind != TokenKind.CONTROL_SEQUENCE:
                continue
            profile = knowledge.resolve_command(token.value)
            active_grammar = isinstance(profile, EffectiveReadingProfile)
            # A source definition overrides even an otherwise known diagnostic.
            if token.value in shadowed or context.lookup_meaning(token.value, token.kind) is not None:
                continue
            if not isinstance(profile, EffectiveReadingProfile):
                syntax = getattr(knowledge, "source_command_syntax", lambda _: None)(token.value)
                profile = syntax
            if profile is None:
                continue
            if profile.grammar.get("handler") in {"inline_character", "token_delimited", "physical_line_literal"}:
                # Captured tokens cannot reproduce a raw-character literal
                # cursor. Do not turn its apparent contents into dependencies.
                break
            if profile.family == "environment_open":
                checkpoint = cursor.checkpoint()
                try:
                    name = scanner.group("environment").literal()
                    environment = knowledge.resolve_environment(name)
                except ReadingIssue:
                    cursor.restore(checkpoint)
                    break
                if not isinstance(environment, EffectiveReadingProfile) or environment.grammar.get("handler") in {
                        "token_delimited", "physical_line_literal"}:
                    break
                continue
            if profile.family == "stored_definition":
                checkpoint = cursor.checkpoint()
                try:
                    definition = DefinitionScanner(cursor, context).read(token.span.start, profile)
                except ReadingIssue:
                    cursor.restore(checkpoint)
                    continue
                child = units.add(definition.body, "stored_body", owner, activity="stored",
                                  evidence={"reason": "stored_definition"})
                shadowed.add(definition.target.value)
                pending.append((ScannedArgument("body", definition.body, definition.body_tokens, "stored"), child, set(shadowed)))
                continue
            if profile.action in DEPENDENCY_ACTIONS and profile.action != "asset_reference" and token.span.start not in excluded:
                identifier = units.add(token.span, "possible_dependency", owner,
                    activity=argument_activity(arg.role), evidence={"reason": "dependency_in_" + arg.role,
                                                                  "argument_role": arg.role})
                yield token, identifier, profile.action, arg.role, None
            if profile.grammar.get("handler") != "source_arguments":
                continue
            checkpoint = cursor.checkpoint()
            try:
                command = scanner.read(token.span, profile)
            except ReadingIssue:
                cursor.restore(checkpoint)
                continue
            command_id = units.add(command.span, "observed_command", owner,
                activity=argument_activity(arg.role), evidence={"reason": "captured_argument_command"})
            if profile.action in {"asset_reference", "asset_search_paths", "asset_extensions"} and token.span.start not in excluded:
                yield token, command_id, profile.action, arg.role, replace(command, unit_id=command_id)
            for child in reversed(command.arguments):
                # Storedness is inherited until an invocation is interpreted.
                role = child.role if active_grammar else "unknown"
                role = "stored" if arg.role == "stored" and role not in {"data", "diagnostic"} else role
                child = replace(child, role=role)
                child_id = units.add(child.span, "argument", command_id, activity=argument_activity(role),
                    evidence={"reason": "declared_argument_role", "argument_name": child.name,
                              "argument_role": role, "binding_id": profile.binding_id})
                pending.append((child, child_id, set(shadowed)))
