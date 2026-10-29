"""Connect Python format file tests to preparation's explicit resource search."""
from pathlib import Path

from ..engine.latex.construction import control, definition
from ..engine.latex.files import record_test
from ..engine.transactions import transaction
from ..reading.contracts import ReadingIssue, StoredDefinition, TokenListMeaning, UndefinedMeaning
from ..reading.effect_summary import EffectSummary, NameSet
from ..reading.effects import definition_summary
from ..reading.tex_reader import CatCode, TokenKind
from .recovery import resource_record


def input_directories(session):
    """Read literal input@path groups without treating macro text as a path."""
    meaning = session.context.resolve_meaning(session.resolver, 'input@path')
    if isinstance(meaning, UndefinedMeaning) and meaning.uncertain is None:
        return []
    if not isinstance(meaning, (StoredDefinition, TokenListMeaning)) or getattr(meaning, 'parameter_tokens', ()):
        raise ReadingIssue('file_search_paths', 'The current input@path is not a known literal directory list')
    directories, current, depth = [], [], 0
    for token in meaning.replacement_tokens:
        if token.catcode == CatCode.BEGIN_GROUP and depth == 0:
            depth = 1
        elif token.catcode == CatCode.END_GROUP and depth == 1:
            directories.append((session.root.parent / ''.join(current)).resolve())
            current, depth = [], 0
        elif depth == 1 and token.kind == TokenKind.CHARACTER and token.catcode not in (CatCode.BEGIN_GROUP, CatCode.END_GROUP):
            current.append(token.value)
        elif depth == 0 and token.catcode == CatCode.SPACE:
            continue
        else:
            raise ReadingIssue('file_search_paths', 'input@path needs literal balanced directory groups')
    if depth:
        raise ReadingIssue('file_search_paths', 'input@path has an unclosed directory group')
    return directories


def lookup_file(session, command):
    target = command.value('target')
    if not target or target.startswith('|'):
        raise ReadingIssue('file_test_name', 'This file test needs a nonempty literal file name')
    suffixes = [''] if Path(target).suffix else ['.tex', '']
    directories = [session.frames[-1].import_dir or session.root.parent, session.store.root,
                   *input_directories(session)]
    path = session.resolve(target, suffixes, command.span, directories=directories,
                           required=False, provisional=True)
    external = session.resources.find(target, suffixes) if path is None else None
    return target, path, external


def file_exists(session, command):
    host = session.dispatcher
    target = None
    try:
        target = command.value('target')
        target, path, external = lookup_file(session, command)
        found = path or external
        if found is None and not session.resources.closed:
            raise ReadingIssue('file_search_environment', 'File absent from project; configure TeX resource roots to establish external absence')
        resolved = str(external).replace('\\', '/') if external else session.name(path) if path else None
        # Kpathsea's absolute hit is provenance. LaTeX's file_full_name result
        # keeps the searched relative name for a native search-path hit.
        runtime_name = Path(target).with_name(external.name).as_posix() if external else resolved
        with transaction(host):
            record_test(host, command, target, runtime_name)
        if path:
            session.tested_resources[session.name(path)] = path
        host.decisions.append({'unit_id': command.unit_id, 'predicate': 'file_exists',
            'name': target, 'truth': found is not None, 'resolved': resolved,
            'search': session.resources.record()})
        observation = resource_record(session, command, 'file_test', requested=target,
            target=resolved, outcome='present' if found is not None else 'absent',
            purpose='probe', search=session.resources.record())
        observation['recovery'] = {'disposition': 'authored_branch',
            'branch': 'then' if found is not None else 'else', 'original_resource': 'not_required'}
        host.select_branch(command, found is not None)
    except ReadingIssue as error:
        observation = resource_record(session, command, 'file_test',
            requested=target,
            outcome='ambiguous' if error.reason == 'ambiguous_dependency' else
                    'unreadable' if error.reason == 'resource_access' else 'unresolved',
            purpose='probe', search=session.resources.record())
        observation['causes'] = [{'reason': error.reason, 'detail': error.detail}]
        observation['recovery'] = {'disposition': 'retained_source', 'original_resource': 'unresolved'}
        session.observe(command)
        # Unknown file selection does not itself invalidate unrelated registers.
        summary = EffectSummary(meanings=NameSet(('@curr@file', '@curr@file@reqd', '@filef@und', 'reserved@a')), scope='global')
        for argument in (command.argument('then'), command.argument('else')):
            value = definition(host, control('branch', argument.span), (), argument.tokens, argument.span)
            summary = summary.union(definition_summary(value, session.context, session.resolver))
        host.defer_effects(command.span, reason=error.reason, detail=error.detail, summary=summary)
        session.require(command.span, error.reason, error.detail, stage='preparation', unit_id=command.unit_id)
        session.require_deferred_dependencies((), command=command, parent_id=command.unit_id)
        session.emit(command.span, command=command)
