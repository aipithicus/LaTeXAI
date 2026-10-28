"""Scope operations over the existing state journal and execution group stack."""
from ..operations import ExecutableOperation
from ...reading.contracts import ReadingIssue


def validate_effect(profile):
    if profile.grammar or profile.interpolations or profile.active_options or profile.terminator is not None:
        raise ReadingIssue("unsupported_reading_effect", "Reading effect requires additional scanning or interpretation")
    if profile.state_management is not None and profile.state_management.scope != "local":
        raise ReadingIssue("unsupported_reading_effect", "Only local reading effects are supported")


def group_kind(profile):
    validate_effect(profile)
    if profile.catcode_overrides or profile.catcode_layers or profile.reader_parameters:
        raise ReadingIssue("unsupported_reading_effect", "Combined grouping and assignments are unsupported")
    kind = profile.state_management.group_kind if profile.state_management else None
    if kind not in {"simple", "semi_simple"}:
        raise ReadingIssue("unsupported_reading_effect", "Grouping requires a supported group kind")
    return kind


def begin_scope(host, opening, profile):
    """No operands or expansion; push a local journal and owned group frame.

    Return the original opener event, preserving its source and mouth state.
    """
    host.begin_group(group_kind(profile), opening.span)
    host.reader.endline_char = host.context.endlinechar
    return opening


def end_scope(host, opening, profile):
    """No operands or expansion; validate the owned group kind before restoring.

    Return the original closer. Synchronize the next line's reader parameter
    without reloading the current line or discarding pending conversions.
    """
    host.end_group(group_kind(profile))
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


OPERATIONS = (
    ExecutableOperation("scope.begin", begin_scope),
    ExecutableOperation("scope.end", end_scope),
    ExecutableOperation("reading.apply_lexical_profile", apply_lexical_profile),
)
