"""Strict source decoding with located malformed-byte diagnostics."""
from __future__ import annotations
import io
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


def open_source(path: Path | str) -> io.StringIO:
    """Read UTF-8 strictly, preserving the previous universal-newline behavior."""
    path = Path(path)
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        details = "; ".join(f"byte {offset}: {raw.hex(' ')}"
                            for offset, raw in invalid_utf8_spans(data))
        raise SourceDecodingError(
            f"Cannot decode {path} as UTF-8: {details} ({exc.reason}). "
            "Specify a verified source encoding before transcoding; no bytes were discarded."
        ) from exc
    return io.StringIO(text.replace("\r\n", "\n").replace("\r", "\n"))
