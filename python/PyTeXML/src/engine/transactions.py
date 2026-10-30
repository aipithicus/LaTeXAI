"""Atomic language requests, including input, scope and conditional state."""
from contextlib import contextmanager
from functools import wraps
from ..reading.contracts import ReadingIssue
from .checkpoints import language_checkpoint


def atomic(handler):
    @wraps(handler)
    def execute(host, *args, **kwargs):
        with transaction(host):
            return handler(host, *args, **kwargs)
    return execute


@contextmanager
def transaction(host):
    with language_checkpoint(host):
        yield


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
