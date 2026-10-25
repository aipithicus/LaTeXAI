"""Non-expanding conditional envelopes, with independent skipped-text agreement.

The dispatcher supplies command knowledge and protected-region capture. This
scanner neither executes branches nor invents truth values. Two linear reads
must agree on every conditional marker before the cursor may resume after fi.
"""
from .contracts import (ConditionalRegion, DeferredRegion, EnvironmentDefinition,
                        ReadingIssue, SourceCommand, StoredDefinition)
from .tex_reader import CatCode, TokenKind


class ConditionalScanner:
    def __init__(self, reader, context):
        self.reader, self.context = reader, context

    def source(self, *, classify, protect):
        """Observe a complete input for insertion into either conditional branch.

        This bounded route admits no conditional tokens, including ones hidden
        in literal data/definitions during active reading: insertion would expose
        them to pass_text in an unselected branch. Effects are never executed.
        """
        reader = self.reader
        checkpoint = reader.checkpoint()
        tokens, observations, changed = [], [], set()
        groups = 0
        while (token := reader.next_token()) is not None:
            if classify(token) is not None:
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
                    tokens.extend(captured.tokens)
                    if captured.command is not None:
                        changed.update(captured.command.metadata.get("observed_write_names", ()))
                        if captured.command.action == "end_input":
                            raise ReadingIssue("conditional_input", "endinput requires an input-boundary lowering rule")
                        if token.value not in changed:
                            observations.append(captured)
                continue
            tokens.append(token)
            groups += 1 if token.catcode == CatCode.BEGIN_GROUP else -1 if token.catcode == CatCode.END_GROUP else 0
            if groups < 0:
                raise ReadingIssue("conditional_input", "Candidate input closes a caller's group")
        if groups:
            raise ReadingIssue("conditional_input", "Candidate input leaves an open group")
        reader.restore(checkpoint)
        with self.context.skipped_branch():
            while (token := reader.next_token()) is not None:
                if classify(token) is not None:
                    raise ReadingIssue("conditional_input", "Inlining would expose a conditional token while skipping")
        return DeferredRegion(reader.basis.whole, "conditional_input",
            "Input observed under the conditional's entry reading assumptions; no branch execution", tuple(tokens),
            observations=tuple(observations)), tuple(sorted(changed))

    def read(self, opening, rule, *, classify, protect):
        reader = self.reader
        if rule.capture_operands is None:
            raise ReadingIssue("conditional_header", "No bounded source-operand capture recipe for this predicate")
        tokens = [opening]
        for _ in range(rule.capture_operands):
            token = reader.next_token()
            if token is None:
                raise ReadingIssue("conditional_header", "EOF in conditional operands")
            tokens.append(token)
        checkpoint = reader.checkpoint()
        markers, observations, changed = [], [], set()
        # Each conditional branch must return to its entry group depth. This is
        # stricter than execution, deliberately excluding branch-crossing scopes.
        groups, frames = 0, [(0, False)]
        while (token := reader.next_token()) is not None:
            meaning = classify(token)
            if meaning is not None:
                if token.value in changed:
                    raise ReadingIssue("conditional_reading", "An unexecuted declaration may change conditional nesting")
                markers.append((token.span, meaning.role))
                tokens.append(token)
                if meaning.role == "opener":
                    frames.append((groups, False))
                    if meaning.evaluation == "deferred" and meaning.capture_operands is None:
                        raise ReadingIssue("conditional_header", "Nested predicate has no source-operand capture recipe")
                    for _ in range(meaning.capture_operands or 0):
                        operand = reader.next_token()
                        if operand is None:
                            raise ReadingIssue("conditional_header", "EOF in nested conditional operands")
                        tokens.append(operand)
                else:
                    base, alternative = frames[-1]
                    if groups != base:
                        raise ReadingIssue("conditional_scope", "Conditional branch crosses a lexical group boundary")
                    if meaning.role == "terminator":
                        frames.pop()
                        if not frames:
                            break
                    else:
                        if alternative:
                            raise ReadingIssue("conditional_structure", "Unexpected additional conditional alternative")
                        frames[-1] = (base, meaning.role == "alternative")
                continue
            captured = protect(token, shadowed=changed)
            if captured:
                if isinstance(captured, StoredDefinition):
                    changed.add(captured.target.value)
                elif isinstance(captured, SourceCommand) and captured.action == "meaning_assignment":
                    changed.add(captured.argument("target").tokens[0].value)
                elif isinstance(captured, EnvironmentDefinition):
                    changed.update((captured.name, "end" + captured.name))
                elif isinstance(captured, DeferredRegion):
                    tokens.extend(captured.tokens)
                    if captured.command is not None:
                        changed.update(captured.command.metadata.get("observed_write_names", ()))
                    if captured.command is not None and token.value not in changed:
                        observations.append(captured)
                continue
            tokens.append(token)
            if token.catcode == CatCode.BEGIN_GROUP:
                groups += 1
            elif token.catcode == CatCode.END_GROUP:
                groups -= 1
                if groups < frames[-1][0]:
                    raise ReadingIssue("conditional_scope", "Conditional closes a group belonging to its caller")
        else:
            raise ReadingIssue("unclosed_conditional", "EOF while capturing an unresolved conditional")
        end = reader.position
        active_end = reader.checkpoint()
        # pass_text does not dispatch verbatim, definitions, arguments or math.
        # Agreement prevents protecting a fake fi that would actually terminate
        # a skipped branch. No reading state or definitions are installed here.
        reader.restore(checkpoint)
        skipped, depth = [], 1
        with self.context.skipped_branch():
            while (token := reader.next_token()) is not None:
                meaning = classify(token)
                if meaning is None:
                    continue
                skipped.append((token.span, meaning.role))
                depth += 1 if meaning.role == "opener" else -1 if meaning.role == "terminator" else 0
                if not depth:
                    break
                if reader.position > end:
                    break
        reader.restore(active_end)
        if skipped != markers:
            raise ReadingIssue("conditional_reading", "Executed and skipped readings disagree on conditional boundaries")
        return ConditionalRegion(reader.source_span(opening.span.start, end), "conditional_interpretation",
            "Branches retained without predicate evaluation; boundary and dependency observations assume entry "
            "catcodes/meanings and unexpanded source operands. Executed and skipped marker scans agree.",
            tuple(tokens), observations=tuple(observations), markers=tuple(span for span, _ in markers),
            changed_meanings=tuple(sorted(changed)))
