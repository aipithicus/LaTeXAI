"""Opt-in, source-pinned driver seams. No PDF object model or native process.

Only the listed interfaces are adapted; bypasses and remaining driver routines
must retain their ordinary unsupported-operation boundaries.
"""
import hashlib

from .integers import IntegerScanner
from .operations import ExpansionKind, OperationFamily, PrimitiveOperation
from .primitive import PrimitiveMeaning
from .programs import CONTENT, evaluate
from .token_text import token_text
from .transactions import atomic
from .primitives.content import owner, result
from .primitives.conversions import group
from .primitives.format_state import expanded_group
from ..reading.contracts import ReadingIssue, BooleanMeaning, UncertainMeaning, StoredDefinition, UndefinedMeaning

DRIVER = "hyperref-hpdftex-7.01s"
SOURCE_SHA256 = "db41df0ca7a5001e76ef891d741ea634b9dd175c6a4f6f0ee7cd483755d3ff51"
INTERFACES = {"hyper@anchorstart": "anchor_start", "hyper@anchorend": "anchor_end",
              "hyper@linkstart": "link_start", "hyper@linkend": "link_end",
              "hyper@linkurl": "url", "hyper@link": "link", "pdfinfo": "metadata"}


def install(host, driver, source, span):
    if driver != DRIVER or hashlib.sha256(source.encode("utf-8")).hexdigest() != SOURCE_SHA256:
        raise ReadingIssue("driver_source", "Semantic driver selection requires the pinned hpdftex.def source")
    if host.context.scope_depth:
        raise ReadingIssue("driver_scope", "Driver installation requires the outer initialization scope")
    content = owner(host)
    if content.lifecycle.drivers:
        raise ReadingIssue("driver_reload", "A semantic driver is already installed")
    for name, action in INTERFACES.items():
        host.context.record_meaning(name, PrimitiveMeaning("semantic.driver", action), global_=True)
    content.lifecycle.drivers.append({"id": driver, "source_sha256": SOURCE_SHA256,
                                     "interfaces": sorted(INTERFACES), "mode": "semantic",
                                     "qualification": "plain destinations and URLs; no PDF encoding or colour backend"})


def require_plain_configuration(host):
    for name in ("ifHy@colorlinks", "ifHy@ocgcolorlinks", "ifHy@pdfa", "ifHy@href@ismap"):
        meaning = host.context.resolve_meaning(host.knowledge, name)
        if meaning is not None and not isinstance(meaning, UndefinedMeaning):
            false = getattr(meaning, "uncertain", None) is None and ((isinstance(meaning, BooleanMeaning) and meaning.truth is False) or
                     (isinstance(meaning, PrimitiveMeaning) and meaning.operation == "conditional.route"
                      and meaning.operand.evaluation == "always_false"))
            if not false:
                raise ReadingIssue("driver_option", "Unqualified semantic driver option: " + name)
    meaning = host.context.resolve_meaning(host.knowledge, "HyperDestNameFilter")
    if meaning is not None and not isinstance(meaning, UndefinedMeaning) and not (isinstance(meaning, StoredDefinition) and
            [(t.value, t.catcode) for t in meaning.parameter_tokens] == [("#", 6), ("1", 12)] and
            [(t.value, t.catcode) for t in meaning.body_tokens] == [("#", 6), ("1", 12)]):
        raise ReadingIssue("driver_destination_filter", "Nonidentity destination filters require a qualified adapter")
    for name in ("Hy@href@nextactionraw", "Hy@xspace@end"):
        meaning = host.context.resolve_meaning(host.knowledge, name)
        if meaning is not None and not isinstance(meaning, UndefinedMeaning) and not (
                isinstance(meaning, StoredDefinition) and not meaning.body_tokens):
            raise ReadingIssue("driver_hook", "Nonempty driver hook requires qualification: " + name)


def argument(host):
    return "".join(token_text(t, host.context) for t in expanded_group(host))


def body(host):
    scanner = IntegerScanner(host)
    tokens = group(scanner.reader)
    scanner.finish()
    return tokens


def event(content, host, span, action, **values):
    content.emit(content.node(host, "driver_event", span, action=action, driver=DRIVER, **values))


def start(content, host, span, kind, destination):
    require_plain_configuration(host)
    if content.lifecycle.links:
        raise ReadingIssue("driver_nested_link", "Nested link annotations require a separate qualified contract")
    content.horizontal(host, span)
    if kind != "url" and not destination:
        destination = "UNDEFINED"
    # The colour group is observable even when the output has no colour backend.
    # Helper strings not yet reproduced are uncertain, rather than stale values.
    helper = "Hy@pstringURI" if kind == "url" else "Hy@testname"
    host.context.record_meaning(helper, UncertainMeaning(span))
    if kind != "url":
        colour = host.context.resolve_meaning(host.knowledge, "@" + kind + "bordercolor")
        host.context.record_meaning("CurrentBorderColor", colour if colour is not None and not isinstance(colour, UndefinedMeaning) else UncertainMeaning(span))
    host.begin_group("semisimple", span)
    identifier = content.lifecycle.identifier()
    content.lifecycle.links = (identifier,)
    event(content, host, span, "link_start", identifier=identifier, link_type=kind, destination=destination)


def end(content, host, span):
    if not content.lifecycle.links:
        raise ReadingIssue("driver_link_stack", "Link end has no matching start")
    after = host.end_group("semisimple", deliver=False)
    if after:
        evaluate(host, after, span, policy=CONTENT)
    event(content, host, span, "link_end", identifier=content.lifecycle.links[-1])
    content.lifecycle.links = ()


@atomic
def execute(host, opening, meaning):
    content, action, span = owner(host), meaning.operand, opening.span
    if action == "link_start":
        kind, destination = argument(host), argument(host)
        start(content, host, span, kind, destination)
    elif action == "link_end":
        end(content, host, span)
    elif action in {"url", "link"}:
        if action == "url":
            tokens, destination, kind = body(host), argument(host), "url"
        else:
            kind, destination, tokens = argument(host), argument(host), body(host)
        if action == "url":
            host.begin_group("semisimple", span)
        start(content, host, span, kind, destination)
        evaluate(host, tokens, span, policy=CONTENT)
        end(content, host, span)
        if action == "url":
            after = host.end_group("semisimple", deliver=False)
            if after:
                evaluate(host, after, span, policy=CONTENT)
    elif action == "anchor_start":
        require_plain_configuration(host)
        destination = argument(host)
        if content.lifecycle.anchors:
            raise ReadingIssue("driver_anchor_stack", "Nested anchors are not qualified")
        content.lifecycle.anchors = (destination,)
        host.context.record_meaning("ifHy@activeanchor", BooleanMeaning(span, True))
        host.context.record_meaning("Hy@pstringDest", UncertainMeaning(span))
        event(content, host, span, action, destination=destination)
    elif action == "anchor_end":
        if not content.lifecycle.anchors:
            raise ReadingIssue("driver_anchor_stack", "Anchor end has no matching start")
        event(content, host, span, action, destination=content.lifecycle.anchors[-1])
        content.lifecycle.anchors = ()
        host.context.record_meaning("ifHy@activeanchor", BooleanMeaning(span, False))
    else:
        # Retain the expanded dictionary. Parsing arbitrary PDF syntax or
        # interpreting arbitrary literal operators is not this adapter's role.
        event(content, host, span, "metadata", dictionary=argument(host), interpretation="raw_pdf_dictionary")
    return result(host, opening)


OPERATION = PrimitiveOperation("semantic.driver", ExpansionKind.UNEXPANDABLE, execute, operand_type=str)
FAMILY = OperationFamily((OPERATION,))
