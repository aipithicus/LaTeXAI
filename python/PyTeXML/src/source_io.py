"""Strict source decoding with located malformed-byte diagnostics."""
from __future__ import annotations
import io
from dataclasses import dataclass
from pathlib import Path


class SourceDecodingError(ValueError):
    """A source file cannot be decoded without discarding bytes."""


def invalid_utf8_spans(data: bytes) -> list[tuple[int, bytes]]:
    """Return every malformed byte span without guessing an encoding.

    Surrogateescape is used only for inspection, never for emitted source.
    Offsets refer to the original byte stream, before newline normalization.
    """
    spans = []
    offset = 0
    start = None
    for char in data.decode("utf-8", errors="surrogateescape"):
        if 0xDC80 <= ord(char) <= 0xDCFF:
            if start is None:
                start = offset
            offset += 1
        else:
            if start is not None:
                spans.append((start, data[start:offset]))
                start = None
            offset += len(char.encode("utf-8"))
    if start is not None:
        spans.append((start, data[start:offset]))
    return spans


def decode_source(data: bytes, path: Path | str) -> str:
    """Decode without changing physical lines or losing source coordinates."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        details = "; ".join(f"byte {offset}: {raw.hex(' ')}"
                            for offset, raw in invalid_utf8_spans(data))
        raise SourceDecodingError(
            f"Cannot decode {path} as UTF-8: {details} ({exc.reason}). "
            "Specify a verified source encoding before transcoding; no bytes were discarded."
        ) from exc
    return text


def open_source(path: Path | str) -> io.StringIO:
    """Read UTF-8 strictly, preserving the previous universal-newline behavior."""
    path = Path(path)
    text = decode_source(path.read_bytes(), path)
    return io.StringIO(text.replace("\r\n", "\n").replace("\r", "\n"))


@dataclass(frozen=True, slots=True)
class SourceDocument:
    path: Path
    name: str
    text: str


class SourceStore:
    """One preparation's immutable filesystem snapshot, loaded lazily once.

    Enumeration and content caches are distinct. Repeated inclusions share text,
    never reader cursors or occurrence identities. Failures are cached too.
    """
    def __init__(self, root: Path, excluded_dirs=()):
        import os
        self.root = root.resolve()
        self.excluded = tuple((self.root / p).resolve() for p in (".git", "artifacts", "build", "extracted")) + tuple(
            Path(p).resolve() for p in excluded_dirs)
        files = []
        self.inventory_errors: list[OSError] = []
        for directory, dirs, names in os.walk(self.root, onerror=self.inventory_errors.append):
            base = Path(directory)
            dirs[:] = sorted(d for d in dirs if not self.is_excluded(base / d))
            files.extend((base / n).resolve() for n in sorted(names) if not self.is_excluded(base / n))
        self.files = tuple(sorted(set(files)))
        self._files = frozenset(files)
        self._bytes: dict[Path, bytes] = {}
        self._documents: dict[Path, SourceDocument] = {}
        self._errors: dict[Path, Exception] = {}

    def is_excluded(self, path: Path) -> bool:
        resolved = path.resolve()
        return not resolved.is_relative_to(self.root) or any(resolved.is_relative_to(p) for p in self.excluded)

    def contains(self, path: Path) -> bool:
        return path.resolve() in self._files

    def read_bytes(self, path: Path) -> bytes:
        path = path.resolve()
        if path not in self._files:
            raise FileNotFoundError(f"Not an inventoried source dependency: {path}")
        if path in self._errors and path not in self._bytes:
            raise self._errors[path]
        if path not in self._bytes:
            try:
                self._bytes[path] = path.read_bytes()
            except OSError as error:
                self._errors[path] = error
                raise
        return self._bytes[path]

    def document(self, path: Path) -> SourceDocument:
        path = path.resolve()
        if path in self._errors:
            raise self._errors[path]
        if path not in self._documents:
            try:
                text = decode_source(self.read_bytes(path), path)
                self._documents[path] = SourceDocument(path, path.relative_to(self.root).as_posix(), text)
            except (SourceDecodingError, OSError) as error:
                self._errors[path] = error
                raise
        return self._documents[path]

    def open(self, path: Path | str) -> io.StringIO:
        return io.StringIO(self.document(Path(path)).text)

    @property
    def read_paths(self) -> tuple[str, ...]:
        return tuple(path.relative_to(self.root).as_posix() for path in self._bytes)
