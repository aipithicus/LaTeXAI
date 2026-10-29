"""Bounded scantokens execution for definition-only generated source.

This is TeX's explicit token-to-text input operation. Arbitrary pseudo-file I/O,
text, reading-state changes and expansion-only uses remain separate capabilities.
"""
from ..expansion import ExpansionCursor
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..programs import ProgramSource, ProgramBudget, SETUP
from ..token_text import token_text
from ..transactions import transaction
from .conversions import group
from ...reading.contracts import ReadingBoundary, ReadingIssue, SourceCommand, StoredDefinition
from ...reading.tex_reader import CatCode, ReadEvent, TexReader


def scantokens(host, opening, meaning):
    from ...reading.dispatcher import StructuralDispatcher
    with transaction(host):
        cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations, host=host)
        tokens = group(cursor)
        if cursor.pending:
            raise ReadingIssue("rescan_continuation", "scantokens argument leaves replacement input pending")
        span = host.reader.source_span(opening.span.start, host.reader.position)
        text = "".join(token_text(t, host.context, double_parameters=True) for t in tokens)
        newline = host.context.integer_parameters.read("newlinechar")
        if 0 <= newline <= 255:
            text = text.replace(chr(newline), "\n")
        host.program_serial += 1
        reader = TexReader(text, source_id=f"@scantokens/{host.program_serial}/{span.basis.source_id}",
            occurrence_id=-host.program_serial, catcodes=host.context.catcodes, endline_char=host.context.endlinechar)
        host.program_sources.append(ProgramSource(reader, span, tuple(t.span for t in tokens), "retokenized"))
        child = StructuralDispatcher(reader, host.context, host.knowledge, preparation=True,
                                     source_commands=True, units=host.units, program=True)
        child.program_policy = SETUP
        child.program_sources, child.program_serial = host.program_sources, host.program_serial
        fuel = getattr(host, "program_budget", None) or ProgramBudget(10000)
        while (item := child._next_item()) is not None:
            fuel.charge()
            if isinstance(item, StoredDefinition):
                continue
            if isinstance(item, ReadEvent) and (item.token is None or item.token.catcode == CatCode.SPACE):
                continue
            if isinstance(item, ReadingBoundary):
                raise ReadingIssue(item.reason, item.detail, causes=item.causes)
            raise ReadingIssue("rescan_effect", "Generated source is outside definition-only scantokens execution")
        host.program_serial = child.program_serial
        return SourceCommand(span, opening.token.value, "rescanned_definitions",
                             metadata={"generated_source": reader.basis.source_id})


RESCAN = PrimitiveOperation("input.scantokens", ExpansionKind.EXPANDABLE, scantokens,
    operand_type=type(None), expansion_unavailable=True)
FAMILY = OperationFamily((RESCAN,), (RESCAN.declare("scantokens", None),))
