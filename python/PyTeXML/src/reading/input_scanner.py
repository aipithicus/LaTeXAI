"""Capture source insertions without execution, checking their insertion context."""
from .contracts import (ConditionalRegion, DeferredRegion, EnvironmentDefinition,
                        ReadingIssue, SourceCommand, StoredDefinition)
from .tex_reader import CatCode, EventKind


class InputScanner:
    def __init__(self, reader, context):
        self.reader, self.context = reader, context

    def read(self, *, may_skip, classify, protect):
        """Only possible skipped-branch insertion requires pass_text validation."""
        reader = self.reader
        checkpoint = reader.checkpoint()
        tokens, events, observations, changed = [], [], [], set()
        groups = 0
        while (event := reader.next_event()) is not None:
            token = event.token
            if token is None or event.kind == EventKind.END_OF_LINE:
                events.append(event)
                if token is not None:
                    tokens.append(token)
                continue
            if may_skip and classify(token) is not None:
                raise ReadingIssue("conditional_input", "Conditional tokens in a candidate input require branch-aware resolution")
            captured = protect(token, shadowed=changed)
            if captured:
                if isinstance(captured, StoredDefinition):
                    changed.add(captured.target.value)
                elif isinstance(captured, SourceCommand) and captured.action == "meaning_assignment":
                    changed.add(captured.argument("target").tokens[0].value)
                elif isinstance(captured, EnvironmentDefinition):
                    changed.update((captured.name, "end" + captured.name))
                elif isinstance(captured, DeferredRegion):
                    if isinstance(captured, ConditionalRegion):
                        changed.update(captured.changed_meanings)
                    if captured.command is not None:
                        changed.update(captured.command.metadata.get("observed_write_names", ()))
                        if captured.command.action == "end_input":
                            raise ReadingIssue("conditional_input" if may_skip else "input_boundary",
                                               "endinput requires an input-boundary lowering rule")
                    if captured.command is None or token.value not in changed:
                        observations.append(captured)
                continue
            tokens.append(token)
            events.append(event)
            groups += (token.catcode == CatCode.BEGIN_GROUP) - (token.catcode == CatCode.END_GROUP)
            if groups < 0:
                raise ReadingIssue("input_scope", "Candidate input closes a caller's group")
        if groups:
            raise ReadingIssue("input_scope", "Candidate input leaves an open group")
        if may_skip:
            active_end = reader.checkpoint()
            reader.restore(checkpoint)
            with self.context.skipped_branch():
                while (token := reader.next_token()) is not None:
                    if classify(token) is not None:
                        raise ReadingIssue("conditional_input", "Inlining would expose a conditional token while skipping")
            reader.restore(active_end)
        reason = "conditional_input" if may_skip else "deferred_input"
        return DeferredRegion(reader.basis.whole, reason,
            "Source insertion captured under entry reading assumptions; commands and branches remain unexecuted",
            tuple(tokens), observations=tuple(observations), events=tuple(events)), tuple(sorted(changed))
