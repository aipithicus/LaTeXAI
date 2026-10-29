"""Non-executing syntax observations under an explicitly assumed entry profile.

Used after an execution barrier: declarations and source argument grammars can
still delimit candidates. No scope, package, catcode, or branch effects run here.
Failure restores the cursor after the opener, so later independent headers remain
visible. This is conditional evidence, not a substitute execution context.
"""
from .argument_scanner import ArgumentScanner
from .assignment_scanner import AssignmentScanner
from .contracts import EffectiveReadingProfile, ReadingIssue, SourceCommand
from .definition_scanner import DefinitionScanner
from .literal_scanner import LiteralScanner
from .tex_reader import TokenKind
from .effects import observed_write_names
from ..engine.primitive import AssignmentTarget, PrimitiveMeaning
from ..engine.observation import capture_primitive


def observe_source(reader, context, knowledge):
    arguments = ArgumentScanner(reader, context)
    definitions = DefinitionScanner(reader, context)
    literals = LiteralScanner(reader, context, knowledge)
    shadowed = set()
    while (token := reader.next_token()) is not None:
        if token.kind != TokenKind.CONTROL_SEQUENCE or token.value in shadowed:
            yield token
            continue
        profile = knowledge.resolve_command(token.value)
        if not isinstance(profile, EffectiveReadingProfile):
            profile = knowledge.source_command_syntax(token.value)
        checkpoint = reader.checkpoint()
        try:
            meaning = context.resolve_meaning(knowledge, token.value)
            if isinstance(meaning, PrimitiveMeaning):
                captured = capture_primitive(reader, context, token, meaning)
                if captured is not None:
                    target = getattr(captured, "target", None)
                    if target is not None:
                        shadowed.add(target.value)
                    elif isinstance(captured, SourceCommand) and captured.action == "meaning_assignment":
                        shadowed.add(captured.argument("target").tokens[0].value)
                    if isinstance(captured, AssignmentTarget):
                        yield token
                        yield captured.target
                    else:
                        yield captured
                    continue
                yield token
                continue
            if profile is not None:
                if profile.family == "character_code_definition":
                    with context.argument_scanning():
                        target = AssignmentScanner(reader, context).target()
                    shadowed.add(target.value)
                    # Protect the raw target, without evaluating its RHS or
                    # asserting how far that expansion-dependent value extends.
                    yield token
                    yield target
                    continue
                if profile.family == "format_declaration":
                    definition = definitions.read(token.span.start, profile)
                    shadowed.add(definition.target.value)
                    yield definition
                    continue
                if profile.family == "meaning_assignment":
                    assignment = AssignmentScanner(reader, context).let(token.span, profile.name)
                    shadowed.add(assignment.argument("target").tokens[0].value)
                    yield assignment
                    continue
                if profile.grammar.get("handler") == "inline_character":
                    yield literals.read(token.span.start, profile)
                    continue
                if profile.family == "environment_open":
                    name = arguments.group("environment").literal()
                    environment = knowledge.resolve_environment(name)
                    if isinstance(environment, EffectiveReadingProfile) and environment.grammar.get("handler") in {"token_delimited", "physical_line_literal"}:
                        # Configured/optional literal headers require their own
                        # resolution. Never claim their apparent body is active.
                        if environment.configuration or environment.grammar.get("has_optional_arguments"):
                            raise ReadingIssue("observation_literal", "Configured literal requires reading resolution")
                        yield literals.read(token.span.start, environment)
                        continue
                if profile.grammar.get("handler") == "source_arguments":
                    command = arguments.read(token.span, profile)
                    shadowed.update(observed_write_names(command, context, knowledge))
                    yield command
                    continue
        except ReadingIssue as issue:
            if issue.reason == "expansion_continuation":
                yield token
                return
        reader.restore(checkpoint)
        yield token
