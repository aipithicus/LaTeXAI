"""Non-expanding conditional skipping over the shared mouth cursor.

Like TeX82's pass_text, only conditional command meanings affect nesting. Braces,
definitions, literal openers, inputs and effects are just tokens here. The caller
chooses the stopping roles and owns all execution and conditional-stack changes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .context import ExecutionMode, ReaderContext
from .contracts import ConditionalRule, ReadingIssue, ReadingKnowledge
from .spans import SourceSpan
from .tex_reader import ReadEvent, TexReader, TokenKind


@dataclass(frozen=True, slots=True)
class SkippedScan:
    span: SourceSpan
    terminator: ReadEvent
    rule: ConditionalRule


class SkippedBranchScanner:
    def __init__(self, reader: TexReader, context: ReaderContext, knowledge: ReadingKnowledge):
        self.reader, self.context, self.knowledge = reader, context, knowledge

    def read(self, *, stop_at_alternative: bool) -> SkippedScan:
        """Return skipped extent and the already-consumed terminating event.

        False then-branches stop at else/or/fi; a discarded else-branch stops
        only at fi. The dispatcher handles invalid top-level or, without TeX's
        error-recovery insertion/deletion. Nothing is published on failure.
        """
        reader, context = self.reader, self.context
        if (context.mode != ExecutionMode.ACTIVE_EXECUTION
                or reader.catcodes is not context.catcodes
                or reader.endline_char != context.endlinechar):
            raise ReadingIssue("inactive_context", "Conditional skipping requires the active shared reader context")
        start, depth = reader.position, 0
        with context.skipped_branch():
            while (event := reader.next_event()) is not None:
                token = event.token
                if token is None or token.kind != TokenKind.CONTROL_SEQUENCE:
                    continue
                # Author macros have macro meaning even if their spelling is fi
                # or iftrue. They do not expand while skipping.
                rule = context.conditional_rule(token.value, self.knowledge)
                if rule is None:
                    continue
                if rule.role == "opener":
                    depth += 1
                elif rule.role in {"alternative", "case_alternative", "terminator"}:
                    if depth == 0:
                        if rule.role == "terminator" or stop_at_alternative:
                            return SkippedScan(reader.source_span(start, event.span.start), event, rule)
                    elif rule.role == "terminator":
                        depth -= 1
                else:
                    raise ReadingIssue("unsupported_conditional", "Unknown conditional nesting role")
        raise ReadingIssue("unclosed_conditional", "EOF while skipping a conditional branch")
