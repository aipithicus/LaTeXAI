"""Atomic language requests, including input, scope and conditional state."""
from contextlib import contextmanager
from dataclasses import replace
from functools import wraps
from ..reading.contracts import ReadingIssue


def atomic(handler):
    @wraps(handler)
    def execute(host, *args, **kwargs):
        with transaction(host):
            return handler(host, *args, **kwargs)
    return execute


@contextmanager
def transaction(host):
    reader, cursor = host.reader, host.reader.checkpoint()
    context, units = host.context.copy(), host.units.checkpoint()
    groups, conditionals = list(host._groups), [replace(c) for c in host._conditionals]
    decisions, conditional_units = list(host.decisions), dict(host._conditional_units)
    skip_start, pending_skip = host._skip_start, host._pending_skip
    sources, serial = len(host.program_sources), host.program_serial
    try:
        yield
    except Exception:
        host.context.restore_from(context)
        host.units.restore(units)
        host._groups, host._conditionals = groups, conditionals
        host.decisions, host._conditional_units = decisions, conditional_units
        host._skip_start, host._pending_skip = skip_start, pending_skip
        del host.program_sources[sources:]
        host.program_serial = serial
        host._set_reader(reader)
        reader.restore(cursor)
        raise


def assignment_global(host, default=False):
    if host.context.scope_depth == 0:
        return True  # At bottom level local and global assignments coincide.
    override = host.context.integer_parameters.read("globaldefs")
    return override > 0 if override else default or "global" in getattr(host, "assignment_prefixes", ())


def meaning_assignment_scope(host, default=False):
    """A retained assignment can establish its current value without its lifetime.

    Preparation preserves the authored assignment and marks enclosing restoration
    entries uncertain. Executed setup programs still require a definite scope.
    """
    try:
        return assignment_global(host, default), None
    except ReadingIssue as error:
        if (error.reason != "uncertain_integer" or not error.causes
                or not host.preparation or host.program):
            raise
        return False, error.causes[0]
