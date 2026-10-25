"""Apply small, declared reading effects without performing layout or expansion."""
from .contracts import BoundMeaning, EffectiveReadingProfile, ReadingIssue


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
