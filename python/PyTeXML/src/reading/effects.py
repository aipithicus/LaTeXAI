"""Apply small, declared reading effects without performing layout or expansion."""
from dataclasses import dataclass
from .contracts import (BooleanMeaning, BoundMeaning, EffectiveReadingProfile,
                        ReadingIssue, ScannedArgument, StoredDefinition)
from .effect_summary import EffectSummary, NameSet
from .tex_reader import CatCode, TokenKind


def command_summary(metadata, context):
    """Compile the declaration only while its source assumptions hold."""
    summary = EffectSummary.parse(metadata["effect_summary"])
    for name in metadata["requires_unshadowed"]:
        if context.lookup_meaning(name) is not None:
            return EffectSummary.unknown(f"Summary prerequisite {name!r} is shadowed")
    return summary


def observed_write_names(command, context, knowledge):
    """Invalidate observational grammars, without executing a retained command.

    Names unknown to both source and catalog have no grammar to accidentally use.
    A later captured declaration is separately added by each observing scanner.
    """
    if "effect_summary" not in command.metadata:
        return ()
    summary = command_summary(command.metadata, context)
    candidates = knowledge.reading_names() | context.meaning_names()
    return tuple(sorted(set(summary.meanings.names) | {
        name for name in candidates if not summary.selective or summary.meanings.contains(name)}))


@dataclass
class _EffectBudget:
    # Bound an entire call graph, not just its depth: a nonrecursive DAG can
    # revisit the same body exponentially often. Exhaustion preserves source.
    remaining: int = 4096


def definition_summary(definition, context, knowledge, *, active=(), forbidden=NameSet(), _budget=None):
    """Bound writes of an argument-free captured body, without running that body.

    Call-time meanings matter: no result is cached on the definition. Expansion,
    computed targets, cycles, unknown callees and reads after possible writes all
    prevent a complete summary. The ordinary capture scanners protect operands.
    """
    from .argument_scanner import ArgumentScanner
    from .assignment_scanner import AssignmentScanner
    from .definition_scanner import DefinitionScanner
    from .token_cursor import TokenCursor

    _budget = _budget if _budget is not None else _EffectBudget()
    if _budget.remaining <= 0:
        return EffectSummary.unknown("Effect analysis work budget exhausted")
    _budget.remaining -= 1
    if (not isinstance(definition, StoredDefinition) or definition.expanded_tokens is not None or definition.parameter_count
            or definition.parameter_tokens or definition.hash_brace):
        return EffectSummary.unknown("Invocation requires argument or environment interpretation")
    if definition.span in active or len(active) >= 64:
        return EffectSummary.unknown("Recursive or excessively deep effect dependency")
    active = (*active, definition.span)
    cursor = TokenCursor(ScannedArgument("body", definition.body, definition.body_tokens), "", context)
    total, depth = EffectSummary(), 0
    try:
        while (token := cursor.next_token()) is not None:
            if _budget.remaining <= 0:
                return EffectSummary.unknown("Effect analysis work budget exhausted")
            _budget.remaining -= 1
            if token.kind == TokenKind.CHARACTER:
                if token.catcode == CatCode.BEGIN_GROUP:
                    depth += 1
                elif token.catcode == CatCode.END_GROUP:
                    depth -= 1
                    if depth < 0:
                        return EffectSummary.unknown("Body leaves its entry group")
                elif token.catcode != CatCode.SPACE:
                    return EffectSummary.unknown("Body text/math needs mode and hook knowledge")
                continue
            if (token.kind != TokenKind.CONTROL_SEQUENCE or total.meanings.contains(token.value)
                    or forbidden.contains(token.value)):
                return EffectSummary.unknown("Body calls an active or possibly overwritten meaning")
            meaning = context.lookup_meaning(token.value)
            if isinstance(meaning, StoredDefinition):
                blocked = NameSet((*forbidden.names, *total.meanings.names), (*forbidden.prefixes, *total.meanings.prefixes))
                effect = definition_summary(meaning, context, knowledge, active=active, forbidden=blocked, _budget=_budget)
            elif isinstance(meaning, BooleanMeaning) and meaning.target is not None and meaning.uncertain is None:
                effect = EffectSummary(meanings=NameSet((meaning.target,)))
            else:
                if meaning is not None and (not isinstance(meaning, BoundMeaning) or meaning.uncertain is not None):
                    return EffectSummary.unknown(f"Unbounded body meaning {token.value!r}")
                profile = meaning.profile if isinstance(meaning, BoundMeaning) else knowledge.resolve_command(token.value)
                if not isinstance(profile, EffectiveReadingProfile):
                    return EffectSummary.unknown(f"No effect contract for {token.value!r}")
                if profile.family == "meaning_assignment":
                    command = AssignmentScanner(cursor, context).let(token.span, profile)
                    target = command.argument("target").tokens[0]
                    if target.kind != TokenKind.CONTROL_SEQUENCE:
                        return EffectSummary.unknown("Active-character assignment needs further resolution")
                    effect = EffectSummary(meanings=NameSet((target.value,)))
                elif profile.family == "stored_definition":
                    captured = DefinitionScanner(cursor, context).read(token.span.start, profile)
                    if captured.target.kind != TokenKind.CONTROL_SEQUENCE:
                        return EffectSummary.unknown("Active-character definition needs further resolution")
                    effect = EffectSummary(meanings=NameSet((captured.target.value,)),
                                           scope=profile.state_management.scope)
                elif profile.family == "parameter_assignment":
                    AssignmentScanner(cursor, context).literal_integer_assignment()
                    effect = EffectSummary(registers=(profile.tex_mechanics["parameter"],))
                elif profile.family == "source_command" and ("effect_summary" in profile.tex_mechanics or profile.action == "reading_noop"):
                    command = ArgumentScanner(cursor, context).read(token.span, profile)
                    for argument in command.arguments:
                        if argument.role != "data":
                            return EffectSummary.unknown("Effect arguments require interpretation")
                        argument.literal()
                    if any(total.meanings.contains(n) or forbidden.contains(n)
                           for n in command.metadata.get("requires_unshadowed", ())):
                        return EffectSummary.unknown("A summary prerequisite may have been overwritten")
                    effect = command_summary(command.metadata, context) if "effect_summary" in command.metadata else EffectSummary()
                else:
                    return EffectSummary.unknown(f"No bounded body operation for {token.value!r}")
            if not effect.selective:
                return effect
            total = total.union(effect)
        return total if depth == 0 else EffectSummary.unknown("Body leaves an open group")
    except ReadingIssue as error:
        return EffectSummary.unknown(f"{error.reason}: {error.detail}")


def declared_effects(command, context, knowledge):
    """A source-backed summary is valid only while its assumed meanings hold.

    Values used for layout are left in source. Explicit meaning assignments are
    installed locally; this prevents a 'pure formatting' shortcut from retaining
    stale definitions of commands the real operation overwrites.
    """
    contract = command.metadata
    for name in contract["requires_unshadowed"]:
        if context.lookup_meaning(name) is not None:
            raise ReadingIssue("effect_precondition", f"Reading summary depends on the standard meaning of {name!r}")
    copies = []
    for target, donor in contract["meaning_copies"].items():
        profile = knowledge.resolve_command(donor)
        if not isinstance(profile, EffectiveReadingProfile):
            raise ReadingIssue("effect_precondition", f"No established reading meaning for {donor!r}")
        copies.append((target, BoundMeaning(command.span, profile=profile)))
    for target, meaning in copies:
        context.record_meaning(target, meaning)
