"""Bounded source capture for preparation; no expansion or effect execution."""
from .argument_scanner import ArgumentScanner
from .contracts import DeferredRegion, EnvironmentDefinition, ReadingIssue, SourceCommand, StoredDefinition
from .tex_reader import CatCode, TokenKind


class DeferredScanner:
    def __init__(self, reader, context):
        self.reader, self.context = reader, context

    def command(self, opening, reason, detail):
        """Protect following balanced groups without guessing a macro's arity."""
        scanner = ArgumentScanner(self.reader, self.context)
        tokens = [opening]
        with self.context.argument_scanning():
            while True:
                checkpoint = self.reader.checkpoint()
                token = scanner.next_nonspace()
                self.reader.restore(checkpoint)
                if token is not None and token.kind == TokenKind.CHARACTER and token.value == "*" and len(tokens) == 1:
                    tokens.append(scanner.next_nonspace())
                    continue
                optional = token is not None and token.kind == TokenKind.CHARACTER and token.value == "["
                if token is None or (token.catcode != CatCode.BEGIN_GROUP and not optional):
                    break
                tokens.extend(scanner.group("uninterpreted group", optional=optional).tokens)
        return DeferredRegion(self.reader.source_span(opening.span.start, self.reader.position),
                              reason, detail, tuple(tokens))

    def math(self, opening):
        """Preserve dollar-delimited math using entry catcodes; do not digest it."""
        reader = self.reader
        checkpoint = reader.checkpoint()
        second = reader.next_token()
        display = second is not None and second.catcode == CatCode.MATH_SHIFT and second.span.start == opening.span.end
        if not display:
            reader.restore(checkpoint)
        tokens = [opening] + ([second] if display else [])
        depth = 0
        with self.context.argument_scanning():
            while (token := reader.next_token()) is not None:
                tokens.append(token)
                if token.catcode == CatCode.BEGIN_GROUP:
                    depth += 1
                elif token.catcode == CatCode.END_GROUP:
                    depth -= 1
                    if depth < 0:
                        raise ReadingIssue("unclosed_math", "Math crosses an unmatched closing group")
                elif token.catcode == CatCode.MATH_SHIFT and depth == 0:
                    if display:
                        closing = reader.next_token()
                        if closing is None or closing.catcode != CatCode.MATH_SHIFT:
                            raise ReadingIssue("unclosed_math", "Display math needs two closing math shifts")
                        tokens.append(closing)
                    return DeferredRegion(reader.source_span(opening.span.start, reader.position),
                        "math_interpretation", "Math retained for downstream interpretation", tuple(tokens))
        raise ReadingIssue("unclosed_math", "EOF while capturing math")

    def environment(self, opening, name, *, protect):
        """Capture an unbound environment; its contents never enter execution.

        This is an entry-catcode observation. A missing literal binding can make
        its delimiters uncertain, so the requirement explicitly retains that fact.
        """
        tokens, observations, depth = [], [], 1
        shadowed = set()
        scanner = ArgumentScanner(self.reader, self.context)
        while (token := self.reader.next_token()) is not None:
            protected = protect(token, shadowed=shadowed)
            if protected:
                if isinstance(protected, StoredDefinition):
                    # Do not install definitions from an unexecuted body. Their
                    # presence still invalidates later use of the old grammar.
                    shadowed.add(protected.target.value)
                if isinstance(protected, EnvironmentDefinition):
                    shadowed.update((protected.name, "end" + protected.name))
                if isinstance(protected, SourceCommand) and protected.action == "meaning_assignment":
                    shadowed.add(protected.argument("target").tokens[0].value)
                if isinstance(protected, DeferredRegion):
                    tokens.extend(protected.tokens)
                    if protected.command is not None and protected.command.action == "declared_effects":
                        shadowed.update(protected.command.metadata["meaning_copies"])
                    if protected.command is not None and token.value not in shadowed:
                        observations.append(protected)
                continue
            tokens.append(token)
            if token.kind != TokenKind.CONTROL_SEQUENCE or token.value not in {"begin", "end"}:
                continue
            checkpoint = self.reader.checkpoint()
            try:
                with self.context.argument_scanning():
                    arg = scanner.group("environment name")
                    matched = arg.literal() == name
            except ReadingIssue:
                self.reader.restore(checkpoint)
                continue
            tokens.extend(arg.tokens)
            if matched:
                depth += 1 if token.value == "begin" else -1
                if not depth:
                    return DeferredRegion(self.reader.source_span(opening.start, self.reader.position),
                        "environment_binding", f"Environment {name!r} captured under entry catcodes; reading behavior needs a binding",
                        tuple(tokens), observations=tuple(observations))
        raise ReadingIssue("unclosed_environment", f"No source-visible closing delimiter for {name!r}")
