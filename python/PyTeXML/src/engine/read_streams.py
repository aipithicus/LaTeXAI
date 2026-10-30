"""Transactional TeX read streams over an explicit, closed source inventory.

No filesystem search or terminal input occurs here. The physical source owner
provides decoded snapshots; tokens retain those snapshots' occurrence identity.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType
from ..reading.contracts import ReadingIssue
from ..reading.spans import SourceBasis
from ..reading.tex_reader import CatCode, TexReader


@dataclass(frozen=True, slots=True)
class ReadSource:
    text: str
    basis: SourceBasis

    @classmethod
    def from_text(cls, name, text, *, occurrence_id=0):
        return cls(text, SourceBasis(name, occurrence_id, len(text)))


@dataclass(frozen=True, slots=True)
class ReadStream:
    source: ReadSource
    position: int = 0


class ReadStreams:
    def __init__(self, *, initial=False):
        self.initial = initial
        self.sources = None
        self.streams = {}
        self.uncertain = None

    def configure(self, sources):
        """Install a finite inventory, where an absent name means a known miss."""
        if any(not isinstance(v, ReadSource) or len(v.text) != v.basis.length for v in sources.values()):
            raise TypeError("Read streams require decoded source snapshots with exact extents")
        self.sources = MappingProxyType(dict(sources))

    def copy(self):
        result = ReadStreams(initial=self.initial)
        result.sources = self.sources
        result.streams = dict(self.streams)
        result.uncertain = self.uncertain
        return result

    def check(self):
        if self.uncertain is not None:
            raise ReadingIssue("uncertain_input_stream", "Retained code may have changed input streams", causes=(self.uncertain,))

    def eof(self, index):
        self.check()
        if index not in self.streams and not self.initial:
            raise ReadingIssue("unavailable_input_stream", "Stream state has not been established")
        return self.streams.get(index) is None

    def open(self, index, name):
        self.check()
        if self.sources is None:
            raise ReadingIssue("input_inventory", "Openin requires an explicit closed source inventory")
        source = self.sources.get(name)
        if source is None and "." not in name.rsplit("/", 1)[-1]:
            source = self.sources.get(name + ".tex")
        self.streams[index] = ReadStream(source) if source is not None else None

    def close(self, index):
        self.check()
        self.streams[index] = None

    def read(self, index, context, *, budget=10000):
        self.check()
        if self.eof(index):
            raise ReadingIssue("terminal_input", "Reading a closed stream would require terminal input")
        stream = self.streams[index]
        source, position = stream.source, stream.position
        mouth = TexReader(source.text, source_id=source.basis.source_id,
                          catcodes=context.catcodes, endline_char=context.endlinechar)
        mouth.basis = source.basis
        tokens, depth = [], 0
        while True:
            if position == len(source.text):
                if depth:
                    raise ReadingIssue("unbalanced_read", "File ended within a read group")
                self.streams[index] = None
                # TeX appends one empty line when a read discovers EOF.
                empty = TexReader("\n", catcodes=context.catcodes, endline_char=context.endlinechar)
                for token in iter(empty.next_token, None):
                    tokens.append(replace(token, span=source.basis.span(position, position), transformed=True))
                return tuple(tokens)
            end = position
            while end < len(source.text) and source.text[end] not in "\r\n":
                end += 1
            if end < len(source.text):
                end += 2 if source.text[end:end + 2] == "\r\n" else 1
            line = mouth.line_window(source.basis.span(position, end))
            for token in iter(line.next_token, None):
                depth += (token.catcode == CatCode.BEGIN_GROUP) - (token.catcode == CatCode.END_GROUP)
                if depth < 0:
                    # Native read_toks discards the remainder of this physical line.
                    depth = 0
                    break
                if len(tokens) >= budget:
                    raise ReadingIssue("read_budget", "Read token list exceeds the bounded input budget")
                tokens.append(token)
            position = end
            if depth == 0:
                self.streams[index] = ReadStream(source, position)
                return tuple(tokens)

    def invalidate(self, span):
        changed = self.uncertain is None
        self.uncertain = self.uncertain or span
        return changed
