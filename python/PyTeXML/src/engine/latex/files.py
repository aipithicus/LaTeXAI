"""Kernel file-test grammar; the input owner supplies the resource environment."""
from ...reading.contracts import EffectiveReadingProfile
from ...reading.tex_reader import CatCode
from ..transactions import meaning_assignment_scope
from .construction import control, character, definition

PROFILES = {'IfFileExists': EffectiveReadingProfile('\\IfFileExists', 'source_command',
    action='file_exists', binding_id='latex-python/2026-06-01', grammar={
        'handler': 'source_arguments', 'arguments': [
            {'name': 'target', 'kind': 'braced', 'role': 'data'},
            {'name': 'then', 'kind': 'braced', 'role': 'branch'},
            {'name': 'else', 'kind': 'braced', 'role': 'branch'}]})}


def record_test(host, command, name, resolved):
    """ltfiles/ltfilehook state for a literal, unsubstituted filename.

    The original file test remains in emitted TeX. These native definitions
    allow subsequent engine requests to observe its effects during preparation.
    """
    local, cause = meaning_assignment_scope(host)
    global_, global_cause = meaning_assignment_scope(host, default=True)
    selected = command.argument('then' if resolved is not None else 'else')
    anchor = command.span
    values = [('@curr@file', name, global_, global_cause),
              ('@curr@file@reqd', name, global_, global_cause),
              ('@filef@und', '' if resolved is None else '"' + resolved + '" ', local, cause)]
    for target, text, scope, uncertainty in values:
        tokens = tuple(character(c, anchor, CatCode.SPACE if c == ' ' else CatCode.OTHER) for c in text)
        host.context.record_definition(definition(host, control(target, anchor), (), tokens, anchor),
                                       global_=scope, scope_cause=uncertainty)
    host.context.record_definition(definition(host, control('reserved@a', anchor), (), selected.tokens, anchor),
                                   global_=local, scope_cause=cause)
