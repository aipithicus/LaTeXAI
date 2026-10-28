"""The common current-meaning lookup used by execution and its consumers."""
from .primitive import PrimitiveMeaning
from ..reading.contracts import BoundMeaning, EffectiveReadingProfile
from ..reading.tex_reader import TokenKind


def resolve_meaning(context, knowledge, name, kind=TokenKind.CONTROL_SEQUENCE):
    meaning = context.lookup_meaning(name, kind)
    if meaning is not None:
        return meaning
    if kind != TokenKind.CONTROL_SEQUENCE:
        return None
    primitive = context.engine_profile.lookup(name)
    if primitive is not None:
        return primitive
    # Temporary reader knowledge remains available for unmigrated constructs.
    legacy = knowledge.resolve_command(name)
    return BoundMeaning(None, profile=legacy) if isinstance(legacy, EffectiveReadingProfile) else None


def conditional_rule(meaning):
    if isinstance(meaning, PrimitiveMeaning) and meaning.operation == "conditional.route":
        return meaning.operand
    if isinstance(meaning, BoundMeaning) and meaning.profile is not None:
        return meaning.profile.conditional
    return None
