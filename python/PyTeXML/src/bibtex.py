"""Small, dependency-free BibTeX data reader.

The reader preserves TeX within field values. It does not execute TeX, interpret
BST programs, split personal names, or apply BibLaTeX inheritance rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re


class BibTeXError(ValueError):
    pass


@dataclass
class Value:
    text: str
    unresolved: tuple[str, ...] = ()

    def resolve(self) -> str:
        if self.unresolved:
            raise BibTeXError("; ".join(self.unresolved))
        return self.text


@dataclass
class Entry:
    kind: str
    key: str
    fields: list[tuple[str, Value]]


@dataclass
class Database:
    entries: dict[str, list[Entry]] = field(default_factory=dict)
    preambles: list[Value] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    strings: dict[str, Value] = field(default_factory=lambda: {key: Value(value) for key, value in zip(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        ("January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"),
    )})

    def read(self, text: str, source: str = "<bibliography>") -> None:
        Reader(text, source, self).read()

    def selected(self, keys: list[str]) -> list[Entry]:
        """Keep citation order and close explicit crossref/xdata dependencies.

        Parent entries remain separate records, with their original keys and
        types. Field inheritance belongs to later bibliography interpretation.
        """
        requested = list(dict.fromkeys(
            key for citation in keys
            for key in (self.entries if citation == "*" else [citation])
        ))
        selected: dict[str, Entry] = {}
        active: set[str] = set()

        def visit(key: str) -> None:
            if key in active:
                raise BibTeXError(f"Cyclic bibliography dependency at {key}")
            if key in selected:
                return
            if key not in self.entries:
                raise BibTeXError(f"Bibliography entry missing: {key}")
            candidates = self.entries[key]
            entry = candidates[0]
            if any(candidate != entry for candidate in candidates[1:]):
                raise BibTeXError(f"Conflicting bibliography entries for cited key {key!r}")
            selected[key] = entry
            active.add(key)
            for name, value in entry.fields:
                if name in ("crossref", "xdata"):
                    resolved = value.resolve()
                    parents = resolved.split(",") if name == "xdata" else [resolved]
                    for parent in parents:
                        visit(parent.strip())
            active.remove(key)

        for key in requested:
            visit(key)
        return list(selected.values())


class Reader:
    def __init__(self, text: str, source: str, database: Database):
        self.text = text
        self.source = source
        self.database = database
        self.pos = 0

    def fail(self, message: str):
        line = self.text.count("\n", 0, self.pos) + 1
        raise BibTeXError(f"{self.source}:{line} (character {self.pos}): {message}")

    def space(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text[self.pos] == "%":
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end + 1
            else:
                break

    def take(self, token: str):
        self.space()
        if not self.text.startswith(token, self.pos):
            self.fail(f"Expected {token!r}")
        self.pos += len(token)

    def identifier(self) -> str:
        self.space()
        start = self.pos
        while (self.pos < len(self.text)
               and not self.text[self.pos].isspace()
               and self.text[self.pos] not in '\\{}()=,#%"'):
            self.pos += 1
        if self.pos == start:
            self.fail("Expected an identifier")
        return self.text[start:self.pos]

    def braced(self) -> str:
        self.take("{")
        start = self.pos
        depth = 1
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            self.pos += 1
            # BibTeX balances braces even after a backslash; \{ must be
            # paired with \} in a field. TeX interpretation comes later.
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return self.text[start:self.pos - 1]
        self.fail("Unterminated braced value")

    def quoted(self) -> str:
        self.take('"')
        pieces = []
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == '"':
                self.pos += 1
                return "".join(pieces)
            if ch == "{":
                pieces.append("{" + self.braced() + "}")
            elif ch == "}":
                self.fail("Unbalanced brace in quoted value")
            else:
                pieces.append(ch)
                self.pos += 1
        self.fail("Unterminated quoted value")

    def value(self) -> Value:
        pieces = []
        unresolved = []
        while True:
            self.space()
            ch = self.text[self.pos:self.pos + 1]
            if ch == "{":
                pieces.append(self.braced())
            elif ch == '"':
                pieces.append(self.quoted())
            else:
                word = self.identifier()
                if re.fullmatch(r"[0-9]+", word):
                    pieces.append(word)
                elif word.lower() in self.database.strings:
                    definition = self.database.strings[word.lower()]
                    pieces.append(definition.text)
                    unresolved.extend(definition.unresolved)
                else:
                    line = self.text.count("\n", 0, self.pos) + 1
                    problem = f"{self.source}:{line}: Undefined bibliography string {word!r}"
                    self.database.diagnostics.append(problem)
                    unresolved.append(problem)
                    # Retain the token for diagnostics, but resolve() refuses
                    # to emit this value as if it were literal field content.
                    pieces.append(word)
            self.space()
            if self.text[self.pos:self.pos + 1] != "#":
                return Value("".join(pieces), tuple(unresolved))
            self.pos += 1

    def read(self):
        while True:
            # Text outside entries is BibTeX commentary. Percent comments must
            # be skipped before looking for an at-sign on the same line.
            self.space()
            while self.pos < len(self.text) and self.text[self.pos] != "@":
                self.pos += 1
                self.space()
            if self.pos == len(self.text):
                return
            self.pos += 1
            kind = self.identifier().lower()
            self.space()
            opening = self.text[self.pos:self.pos + 1]
            if opening not in ("{", "("):
                self.fail("Expected '{' or '(' after entry type")
            closing = "}" if opening == "{" else ")"
            if kind == "comment":
                if opening == "{":
                    self.braced()
                else:
                    self.pos += 1
                    depth = 1
                    while self.pos < len(self.text) and depth:
                        ch = self.text[self.pos]
                        if ch == "{":
                            self.braced()
                            continue
                        depth += (ch == "(") - (ch == ")")
                        self.pos += 1
                    if depth:
                        self.fail("Unterminated comment")
                continue
            self.pos += 1
            if kind == "preamble":
                self.database.preambles.append(self.value())
                self.space()
                if self.text[self.pos:self.pos + 1] == ",":
                    self.pos += 1
                self.take(closing)
                continue
            key = self.identifier()
            if kind == "string":
                self.take("=")
                self.database.strings[key.lower()] = self.value()
                self.space()
                if self.text[self.pos:self.pos + 1] == ",":
                    self.pos += 1
                self.take(closing)
                continue
            if key in self.database.entries:
                line = self.text.count("\n", 0, self.pos) + 1
                self.database.diagnostics.append(
                    f"{self.source}:{line}: Repeated entry key {key!r}; all records retained, "
                    "conflicting records cannot be selected for inline output"
                )
            self.take(",")
            fields = []
            while True:
                self.space()
                if self.text[self.pos:self.pos + 1] == closing:
                    self.pos += 1
                    break
                name = self.identifier().lower()
                if any(previous == name for previous, _ in fields):
                    line = self.text.count("\n", 0, self.pos) + 1
                    self.database.diagnostics.append(
                        f"{self.source}:{line}: Repeated field {name!r} in {key!r}; all occurrences retained"
                    )
                self.take("=")
                fields.append((name, self.value()))
                self.space()
                if self.text[self.pos:self.pos + 1] != closing:
                    self.take(",")
            self.database.entries.setdefault(key, []).append(Entry(kind, key, fields))
