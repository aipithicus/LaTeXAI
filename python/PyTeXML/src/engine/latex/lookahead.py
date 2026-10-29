"""Python adaptations of the kernel's optional-argument execution routines."""
from .construction import control, character, group, definition
from ..meanings import compare_tokens
from ..operations import ExecutableOperation, ExpansionKind, OperationFamily
from ..transactions import atomic, assignment_global
from ...reading.argument_scanner import undelimited_tokens
from ...reading.contracts import BoundMeaning, EffectiveReadingProfile, ReadingIssue, SourceCommand, TokenArgument, UncertainMeaning
from ...reading.tex_reader import CatCode, TokenKind

PROFILES = {
    '@protected@testopt': EffectiveReadingProfile('\\@protected@testopt', 'format_protected_optional', binding_id='latex-python/2026-06-01'),
    '@testopt': EffectiveReadingProfile('\\@testopt', 'format_optional', binding_id='latex-python/2026-06-01'),
}


def result(host, opening, tokens):
    span = host.reader.source_span(opening.span.start, host.reader.position)
    return SourceCommand(span, opening.token.value, 'program_expand', (TokenArgument('body', span, tuple(tokens)),))


@atomic
def protected_optional(host, opening, profile):
    if not host.program:
        raise ReadingIssue('format_continuation', 'Protected optional dispatch requires an execution continuation')
    # The public token is an operand of this routine; the hidden implementation
    # and default remain in the input for @testopt, exactly as in ltdefns.dtx.
    undelimited_tokens(host.reader, '@protected@testopt', long=False)
    same = compare_tokens(control('protect', opening.span), control('@typeset@protect', opening.span),
                          host.context, host.knowledge, host.operations)
    if same is not True:
        raise ReadingIssue('format_protection', 'Non-typesetting protection requires the protected-write consumer')
    return result(host, opening, (control('@testopt', opening.span),))


@atomic
def test_optional(host, opening, profile):
    if not host.program:
        raise ReadingIssue('format_continuation', 'Optional dispatch requires an execution continuation')
    body = undelimited_tokens(host.reader, '@testopt', long=True)[0]
    default = undelimited_tokens(host.reader, '@testopt', long=True)[0]
    bracket = character('[', opening.span)
    yes = body
    no = (*body, bracket, *group(default, opening.span), character(']', opening.span))
    # kernel@ifnextchar skips spaces but leaves the selected token unread.
    while True:
        saved = host.reader.checkpoint()
        following = host.reader.next_token()
        if following is None:
            following = getattr(host, 'return_lookahead', None)
            host.reader.restore(saved)
            if following is None:
                raise ReadingIssue('argument_lookahead', 'Optional lookahead has no established continuation token')
            break
        if following.catcode != CatCode.SPACE:
            host.reader.restore(saved)
            break
    matched = compare_tokens(following, bracket, host.context, host.knowledge, host.operations)
    if matched is None:
        raise ReadingIssue('uncertain_meaning', 'Optional lookahead depends on an unknown token meaning')
    global_ = assignment_global(host)
    host.context.record_meaning('reserved@d', BoundMeaning(opening.span, token=bracket), global_=global_)
    for name, tokens in [('reserved@a', yes), ('reserved@b', no)]:
        host.context.record_definition(definition(host, control(name, opening.span), (), tokens, opening.span), global_=global_)
    donor = (BoundMeaning(following.span, token=following) if following.kind == TokenKind.CHARACTER else
             host.context.resolve_meaning(host.knowledge, following.value, following.kind))
    host.context.record_meaning('@let@token', donor or UncertainMeaning(following.span), global_=global_)
    chosen = host.context.lookup_definition('reserved@a' if matched else 'reserved@b')
    host.context.record_meaning('reserved@c', chosen, global_=global_)
    return result(host, opening, yes if matched else no)


OPTIONAL = ExecutableOperation('format.test_optional', ExpansionKind.INTERNAL, test_optional, continuation=True)
PROTECTED = ExecutableOperation('format.protected_optional', ExpansionKind.INTERNAL, protected_optional, continuation=True)
FAMILY = OperationFamily((OPTIONAL, PROTECTED), ())
