"""Small declarative, non-expanding argument grammars for source traversal."""
from __future__ import annotations
from dataclasses import replace
from .contracts import ReadingIssue, ScannedArgument, SourceCommand
from .tex_reader import CatCode, Token, TokenKind


def group_tokens(reader, name, *, optional=False, long=True):
    """Collect raw tokens after an opener, without assuming one source basis."""
    depth, tokens = 0, []
    while (token := reader.next_token()) is not None:
        if not long and token.kind == TokenKind.CONTROL_SEQUENCE and token.value == "par":
            raise ReadingIssue("runaway_argument", f"Paragraph in a short argument of {name}")
        if token.catcode == CatCode.BEGIN_GROUP:
            depth += 1
        elif token.catcode == CatCode.END_GROUP:
            if depth == 0 and not optional:
                return tuple(tokens), token
            depth -= 1
            if depth < 0:
                raise ReadingIssue("unclosed_argument", f"Unbalanced {name}")
        elif (optional and depth == 0 and token.kind == TokenKind.CHARACTER
              and token.value == "]" and token.catcode == CatCode.OTHER):
            return tuple(tokens), token
        tokens.append(token)
    raise ReadingIssue("unclosed_argument", f"EOF while scanning {name}")


def undelimited_tokens(reader, name, *, first=None, long=True):
    """Return argument tokens and their actual opening/closing tokens.

    Token lists can span multiple input frames. Source scanners may additionally
    establish a contiguous source extent; expansion need not invent one.
    """
    if first is None:
        first = reader.next_token()
        while first is not None and first.catcode == CatCode.SPACE:
            first = reader.next_token()
    if first is None or first.catcode == CatCode.END_GROUP:
        raise ReadingIssue("argument_required", f"Expected a token or balanced group for {name}")
    if first.catcode == CatCode.BEGIN_GROUP:
        tokens, closing = group_tokens(reader, name, long=long)
        return tokens, first, closing
    if not long and first.kind == TokenKind.CONTROL_SEQUENCE and first.value == "par":
        raise ReadingIssue("runaway_argument", f"Paragraph in a short argument of {name}")
    return (first,), first, first


def optional_tokens(reader, name, default, *, long=True):
    """LaTeX's execution-time optional argument, using frozen raw tokens.

    The kernel's next-character test skips spaces, without expanding the next
    token. Braces protect closing brackets. Like a TeX delimited parameter, a
    supplied argument consisting of one group loses that outer pair of braces.
    The captured default is substituted as-is.
    """
    first = reader.next_token()
    while first is not None and first.catcode == CatCode.SPACE:
        first = reader.next_token()
    if first is None:
        # A physical file or bounded replacement can end before its caller's
        # next token. EOF here does not prove that the optional argument is absent.
        raise ReadingIssue("argument_lookahead", f"Optional argument of {name} needs an input continuation")
    if not (first is not None and first.kind == TokenKind.CHARACTER
            and first.value == "[" and first.catcode == CatCode.OTHER):
        if first is not None:
            reader.unread_token(first)
        return tuple(default)
    tokens, _ = group_tokens(reader, name, optional=True, long=long)
    if tokens and tokens[0].catcode == CatCode.BEGIN_GROUP:
        depth = 0
        for index, token in enumerate(tokens):
            if token.catcode == CatCode.BEGIN_GROUP:
                depth += 1
            elif token.catcode == CatCode.END_GROUP:
                depth -= 1
            if depth == 0:
                return tokens[1:-1] if index == len(tokens) - 1 else tokens
    return tokens


class ArgumentScanner:
    def __init__(self, reader, context):
        self.reader, self.context = reader, context
        self.filename_braced = None

    def _peek(self):
        checkpoint = self.reader.checkpoint()
        token = self.reader.next_token()
        self.reader.restore(checkpoint)
        return token

    def next_nonspace(self) -> Token | None:
        """Consume SPACE-category tokens and return the next token, or EOF.

        Paragraph tokens and active characters remain significant. This uses
        the current cursor without expanding tokens or changing execution scope.
        """
        token = self.reader.next_token()
        while token is not None and token.catcode == CatCode.SPACE:
            token = self.reader.next_token()
        return token

    def group(self, name: str, *, optional=False) -> ScannedArgument | None:
        checkpoint = self.reader.checkpoint()
        opening = self.next_nonspace()
        if optional:
            is_open = opening is not None and opening.kind == TokenKind.CHARACTER and opening.value == "[" and opening.catcode == CatCode.OTHER
        else:
            is_open = opening is not None and opening.catcode == CatCode.BEGIN_GROUP
        if not is_open:
            if optional:
                self.reader.restore(checkpoint)
                return None
            raise ReadingIssue("argument_required", f"Expected a braced {name}")
        return self._group_contents(name, opening, optional=optional)

    def undelimited(self, name: str, *, first: Token | None = None) -> ScannedArgument:
        """Capture one raw token or an explicit balanced group, stripping its braces.

        SPACE tokens are skipped; paragraph tokens are allowed. No meaning lookup,
        expansion or execution occurs. A caller that already read the first
        nonspace token can pass it without rewinding the mouth. This is the long
        argument form; short/outer validity requires the eventual macro runtime.
        """
        tokens, opening, closing = undelimited_tokens(self.reader, name, first=first)
        span = (self.reader.source_span(opening.span.end, closing.span.start)
                if opening.catcode == CatCode.BEGIN_GROUP else opening.span)
        return ScannedArgument(name, span, tokens)

    def _group_contents(self, name: str, opening: Token, *, optional=False) -> ScannedArgument:
        tokens, closing = group_tokens(self.reader, name, optional=optional)
        return ScannedArgument(name, self.reader.source_span(opening.span.end, closing.span.start), tokens)

    def filename(self, name: str) -> ScannedArgument:
        checkpoint = self.reader.checkpoint()
        first = self.next_nonspace()
        if first is None:
            raise ReadingIssue("argument_required", "Missing input filename")
        self.filename_braced = first.catcode == CatCode.BEGIN_GROUP
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
        first = self.next_nonspace()
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
        metadata = {**profile.tex_mechanics, "binding_id": profile.binding_id}
        if self.filename_braced is not None:
            metadata["filename_braced"] = self.filename_braced
        return SourceCommand(self.command_span(opening), profile.name,
                             profile.action, tuple(arguments), metadata)

    def command_span(self, opening):
        return self.reader.source_span(opening.start, self.reader.position)


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
