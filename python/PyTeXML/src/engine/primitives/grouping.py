"""Scope operations over the existing state journal and execution group stack."""
from ..operations import ExecutableOperation, ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from ...reading.contracts import EffectiveReadingProfile, ReadingIssue


def validate_effect(profile):
    if profile.grammar or profile.interpolations or profile.active_options or profile.terminator is not None:
        raise ReadingIssue("unsupported_reading_effect", "Reading effect requires additional scanning or interpretation")
    if profile.state_management is not None and profile.state_management.scope != "local":
        raise ReadingIssue("unsupported_reading_effect", "Only local reading effects are supported")


def begin_scope(host, opening, profile: PrimitiveMeaning[str]):
    """No operands or expansion; push a local journal and owned group frame.

    Return the original opener event, preserving its source and mouth state.
    """
    host.begin_group(profile.operand, opening.span)
    host.reader.endline_char = host.context.endlinechar
    return opening


def end_scope(host, opening, profile: PrimitiveMeaning[str]):
    """No operands or expansion; validate the owned group kind before restoring.

    Return the original closer. Synchronize the next line's reader parameter
    without reloading the current line or discarding pending conversions.
    """
    host.end_group(profile.operand)
    host.reader.endline_char = host.context.endlinechar
    return opening


def apply_lexical_profile(host, opening, profile):
    """No operands or expansion; apply established local lexical effects.

    State owns saved catcodes/parameters and expl3 entry/exit. Return the original
    event and synchronize endlinechar without resetting the mouth's N/M/S state.
    """
    validate_effect(profile)
    if profile.action not in {"assign_catcode", "expl3_lexical_enter", "expl3_lexical_exit"}:
        raise ReadingIssue("unsupported_operation", f"No execution route for {profile.action!r}")
    if set(profile.reader_parameters) - {"endlinechar"}:
        raise ReadingIssue("unsupported_reading_effect", "Unknown reader parameter")
    host.context.apply_profile(profile)
    host.reader.endline_char = host.context.endlinechar
    return opening


BEGIN = PrimitiveOperation("scope.begin", ExpansionKind.UNEXPANDABLE, begin_scope, operand_type=str)
END = PrimitiveOperation("scope.end", ExpansionKind.UNEXPANDABLE, end_scope, operand_type=str)

FAMILY = OperationFamily(
    operations=(BEGIN, END, ExecutableOperation[EffectiveReadingProfile](
        "reading.apply_lexical_profile", ExpansionKind.INTERNAL, apply_lexical_profile)),
    primitives=(BEGIN.declare("begingroup", "semi_simple"), END.declare("endgroup", "semi_simple")),
)
