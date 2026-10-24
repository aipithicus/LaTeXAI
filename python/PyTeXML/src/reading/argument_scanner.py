"""Small declarative, non-expanding argument grammars for source traversal."""
from __future__ import annotations
from dataclasses import replace
from .contracts import ReadingIssue, ScannedArgument, SourceCommand
from .tex_reader import CatCode, TokenKind


class ArgumentScanner:
    def __init__(self, reader, context):
        self.reader, self.context = reader, context

    def _peek(self):
        checkpoint = self.reader.checkpoint()
        token = self.reader.next_token()
        self.reader.restore(checkpoint)
        return token

    def _nonspace(self):
        token = self.reader.next_token()
        while token is not None and token.catcode == CatCode.SPACE:
            token = self.reader.next_token()
        return token

    def group(self, name: str, *, optional=False) -> ScannedArgument | None:
        checkpoint = self.reader.checkpoint()
        opening = self._nonspace()
        if optional:
            is_open = opening is not None and opening.kind == TokenKind.CHARACTER and opening.value == "[" and opening.catcode == CatCode.OTHER
        else:
            is_open = opening is not None and opening.catcode == CatCode.BEGIN_GROUP
        if not is_open:
            if optional:
                self.reader.restore(checkpoint)
                return None
            raise ReadingIssue("argument_required", f"Expected a braced {name}")
        depth = 0
        tokens = []
        while (token := self.reader.next_token()) is not None:
            if token.catcode == CatCode.BEGIN_GROUP:
                depth += 1
            elif token.catcode == CatCode.END_GROUP:
                if depth == 0 and not optional:
                    return ScannedArgument(name, self.reader.source_span(opening.span.end, token.span.start), tuple(tokens))
                depth -= 1
                if depth < 0:
                    raise ReadingIssue("unclosed_argument", f"Unbalanced {name}")
            elif optional and depth == 0 and token.kind == TokenKind.CHARACTER and token.value == "]" and token.catcode == CatCode.OTHER:
                return ScannedArgument(name, self.reader.source_span(opening.span.end, token.span.start), tuple(tokens))
            tokens.append(token)
        raise ReadingIssue("unclosed_argument", f"EOF while scanning {name}")

    def filename(self, name: str) -> ScannedArgument:
        checkpoint = self.reader.checkpoint()
        first = self._nonspace()
        if first is None:
            raise ReadingIssue("argument_required", "Missing input filename")
        if first.catcode == CatCode.BEGIN_GROUP:
            self.reader.restore(checkpoint)
            return self.group(name)
        tokens = [first]
        # A noncharacter terminates the primitive filename without being consumed.
        # Macro-built names are deliberately unresolved, not silently truncated.
        while (token := self._peek()) is not None:
            if token.catcode == CatCode.SPACE:
                self.reader.next_token()
                break
            if token.kind != TokenKind.CHARACTER or token.catcode not in (CatCode.LETTER, CatCode.OTHER, CatCode.SUBSCRIPT, CatCode.SUPERSCRIPT):
                raise ReadingIssue("computed_filename", "Unbraced filenames require a space terminator")
            tokens.append(self.reader.next_token())
        arg = ScannedArgument(name, self.reader.source_span(first.span.start, tokens[-1].span.end), tuple(tokens))
        arg.literal()
        return arg

    def control_sequence(self, name: str) -> ScannedArgument:
        checkpoint = self.reader.checkpoint()
        first = self._nonspace()
        if first is not None and first.catcode == CatCode.BEGIN_GROUP:
            self.reader.restore(checkpoint)
            argument = self.group(name)
        elif first is not None:
            argument = ScannedArgument(name, first.span, (first,))
        else:
            raise ReadingIssue("argument_required", f"Missing {name}")
        if len(argument.tokens) != 1 or argument.tokens[0].kind != TokenKind.CONTROL_SEQUENCE:
            raise ReadingIssue("computed_argument", f"{name} requires one literal control sequence")
        return argument

    def read(self, opening, profile) -> SourceCommand:
        arguments = []
        with self.context.argument_scanning():
            specs = profile.grammar["arguments"]
            if "starred_arguments" in profile.grammar:
                token = self._peek()
                if token is not None and token.kind == TokenKind.CHARACTER and token.value == "*" and token.catcode == CatCode.OTHER:
                    token = self.reader.next_token()
                    arguments.append(ScannedArgument("star", token.span, (token,)))
                    specs = profile.grammar["starred_arguments"]
            for spec in specs:
                kind, name = spec["kind"], spec["name"]
                if kind == "star":
                    token = self._peek()
                    if token is not None and token.kind == TokenKind.CHARACTER and token.value == "*" and token.catcode == CatCode.OTHER:
                        token = self.reader.next_token()
                        arguments.append(ScannedArgument(name, token.span, (token,)))
                    continue
                if kind == "filename":
                    arg = self.filename(name)
                elif kind == "control_sequence":
                    arg = self.control_sequence(name)
                else:
                    arg = self.group(name, optional=kind == "optional")
                if arg is not None:
                    arguments.append(replace(arg, role=spec.get("role", "unknown"),
                        literal_categories=tuple(spec["literal_categories"]) if "literal_categories" in spec else None))
        return SourceCommand(self.reader.source_span(opening.start, self.reader.position), profile.name,
                             profile.action, tuple(arguments), {**profile.tex_mechanics, "binding_id": profile.binding_id})


def key_value_items(argument: ScannedArgument | None):
    """Yield keys and original value tokens, retaining duplicates and positions."""
    if argument is None:
        return
    entries, current, depth = [], [], 0
    for token in argument.tokens:
        if token.catcode == CatCode.BEGIN_GROUP:
            depth += 1
        elif token.catcode == CatCode.END_GROUP:
            depth -= 1
        if token.value == "," and token.catcode == CatCode.OTHER and depth == 0:
            entries.append(current)
            current = []
        else:
            current.append(token)
    entries.append(current)
    for entry in entries:
        if not entry or all(t.catcode == CatCode.SPACE for t in entry):
            continue
        separator = next((i for i, t in enumerate(entry)
                          if t.kind == TokenKind.CHARACTER and t.catcode == CatCode.OTHER and t.value == "="), None)
        key_tokens = entry if separator is None else entry[:separator]
        if any(t.kind != TokenKind.CHARACTER or t.catcode not in {CatCode.LETTER, CatCode.OTHER, CatCode.SPACE}
               or t.value in "\\{}" for t in key_tokens):
            raise ReadingIssue("computed_option", "Option names require literal characters")
        key = "".join(t.value for t in key_tokens).strip()
        if not key:
            raise ReadingIssue("computed_option", "Option names require literal characters")
        yield key, tuple(entry[separator + 1:]) if separator is not None else None


def key_values(argument: ScannedArgument | None) -> dict[str, str]:
    """Split a captured key/value list at top-level commas, without expansion."""
    return {key: "".join(("\\" if t.kind == TokenKind.CONTROL_SEQUENCE else "") + t.value
                        for t in tokens).strip() if tokens is not None else "true"
            for key, tokens in key_value_items(argument)}
