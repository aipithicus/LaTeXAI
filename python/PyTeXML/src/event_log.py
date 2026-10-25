"""Buffered structured events, independent of readers, preparation and rendering.

One logger owns a run and sequence; bound loggers share that state and sink.
Thread-safe within that ownership boundary. Multiple processes must use distinct
journals or send events to one writer; this module does not claim process locking.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
import traceback
from typing import Protocol
from uuid import uuid4


SCHEMA = "pytexml-event/1"
LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})


@dataclass(frozen=True, slots=True)
class Location:
    """An explicit coordinate basis; never infer master offsets from raw source."""
    artifact: str
    basis: str = "artifact"  # artifact (e.g. master.tex), or original source
    start: int | None = None
    end: int | None = None
    coordinate_domain: str = "decoded_unicode_codepoints"
    sha256: str | None = None
    occurrence: int | None = None
    line: int | None = None
    precision: str | None = None

    def __post_init__(self):
        if not isinstance(self.artifact, str) or not self.artifact:
            raise ValueError("Log location requires an artifact name")
        if self.basis not in {"artifact", "source"}:
            raise ValueError("Log location basis must be artifact or source")
        if self.coordinate_domain not in {"decoded_unicode_codepoints", "bytes"}:
            raise ValueError("Log location has an unknown coordinate domain")
        if (self.start is None) != (self.end is None):
            raise ValueError("Log span requires both start and end")
        if self.start is not None and (type(self.start) is not int or type(self.end) is not int
                                      or not 0 <= self.start <= self.end):
            raise ValueError("Log span must be a nonnegative half-open interval")
        if self.line is not None and (type(self.line) is not int or self.line < 1):
            raise ValueError("Log line must be positive")
        if self.precision is not None and (self.precision not in {"exact", "enclosing"} or self.start is None):
            raise ValueError("Log span precision requires an exact or enclosing interval")
        if self.occurrence is not None and (self.basis != "source" or type(self.occurrence) is not int
                                          or self.occurrence < 0):
            raise ValueError("Only source locations carry a nonnegative occurrence")
        if self.sha256 is not None and (not isinstance(self.sha256, str) or len(self.sha256) != 64
                                      or any(c not in "0123456789abcdef" for c in self.sha256)):
            raise ValueError("Log artifact SHA-256 must be 64 lowercase hexadecimal digits")

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}


class EventSink(Protocol):
    def append(self, records: bytes) -> None:
        """Append a complete batch of UTF-8 JSONL records, or raise."""


class JsonlSink:
    """Append with no history replay and no file handle held between checkpoints.

    path can be rebound by an owner relocating its journal during recovery.
    Only the last byte is read to detect an interrupted record before appending.
    A damaged tail is preserved and reported, never silently truncated/repaired.
    """
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = RLock()

    def append(self, records: bytes) -> None:
        if not records:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+b") as stream:
                stream.seek(0, 2)
                if stream.tell():
                    stream.seek(-1, 2)
                    if stream.read(1) != b"\n":
                        raise ValueError(f"Incomplete JSONL tail in {self.path}; history was not changed")
                stream.write(records)
                stream.flush()


class MemorySink:
    """Collect encoded snapshots without I/O, useful for embedding and tests."""
    def __init__(self):
        self._batches = []
        self._lock = RLock()

    def append(self, records: bytes) -> None:
        with self._lock:
            self._batches.append(records)

    @property
    def events(self):
        with self._lock:
            return [json.loads(line) for batch in self._batches for line in batch.splitlines()]


def exception_details(error: BaseException, *, depth=8):
    """Capture exception chains without locals, source-file reads or live frames."""
    seen = set()
    def capture(current, remaining):
        if id(current) in seen or not remaining:
            return {"truncated": True}
        seen.add(id(current))
        result = {"type": f"{type(current).__module__}.{type(current).__qualname__}",
                  "message": str(current), "frames": [
                      {"file": frame.f_code.co_filename, "line": line, "function": frame.f_code.co_name}
                      for frame, line in traceback.walk_tb(current.__traceback__)]}
        if getattr(current, "__notes__", None):
            result["notes"] = list(current.__notes__)
        if current.__cause__ is not None:
            result["cause"] = capture(current.__cause__, remaining - 1)
        elif current.__context__ is not None and not current.__suppress_context__:
            result["context"] = capture(current.__context__, remaining - 1)
        return result
    return capture(error, depth)


def _json(value):
    # JSON object keys must be strings; json.dumps otherwise coerces some types.
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise TypeError("Event data requires string object keys")
            for child in item.values():
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)
    check(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


class _Run:
    def __init__(self, sink, run_id, buffer_bytes):
        self.sink, self.run_id, self.buffer_bytes = sink, run_id, buffer_bytes
        self.sequence, self.pending, self.failure = 0, bytearray(), None
        self.lock = RLock()

    def flush(self):
        if self.failure is not None:
            raise self.failure
        if self.pending:
            try:
                self.sink.append(bytes(self.pending))
            except Exception as error:
                # A sink may already have appended a prefix. Never retry this
                # batch automatically and duplicate the successfully written part.
                self.failure = error
                raise
            self.pending.clear()


class EventLogger:
    """Small event API: bind context, emit snapshots, flush at owned checkpoints.

    No automatic success/failure verdicts. Producers own event codes and outcomes.
    Buffered events are not crash-durable; flush closes the file but does not fsync.
    """
    def __init__(self, sink: EventSink, *, run_id=None, stage="", context=None, buffer_bytes=65536):
        run_id = uuid4().hex if run_id is None else run_id
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a nonempty string")
        if type(buffer_bytes) is not int or buffer_bytes < 1:
            raise ValueError("buffer_bytes must be positive")
        if not isinstance(stage, str) or (context is not None and not isinstance(context, dict)):
            raise TypeError("Logger stage must be a string and context an object")
        self._run = _Run(sink, run_id, buffer_bytes)
        self.stage = stage
        self._context = _json(context or {})

    @property
    def run_id(self):
        return self._run.run_id

    def bind(self, *, stage=None, **context):
        if stage is not None and not isinstance(stage, str):
            raise TypeError("Logger stage must be a string")
        child = object.__new__(EventLogger)
        child._run = self._run
        child.stage = self.stage if stage is None else stage
        child._context = _json({**json.loads(self._context), **context})
        return child

    def emit(self, code: str, message: str = "", *, level="info", data=None,
             locations=(), error: BaseException | None = None, flush=False) -> str:
        if level not in LEVELS or not isinstance(code, str) or not code:
            raise ValueError("Events require a known level and nonempty code")
        if not isinstance(message, str) or not isinstance(self.stage, str):
            raise TypeError("Event message and stage must be strings")
        if data is not None and not isinstance(data, dict):
            raise TypeError("Event data must be an object")
        with self._run.lock:
            if self._run.failure is not None:
                raise self._run.failure
            sequence = self._run.sequence + 1
            identifier = f"{self.run_id}:{sequence}"
            record = {"schema": SCHEMA, "id": identifier, "run_id": self.run_id, "sequence": sequence,
                      "time": datetime.now(timezone.utc).isoformat(), "level": level,
                      "stage": self.stage, "code": code, "message": message,
                      "context": json.loads(self._context), "data": {} if data is None else data,
                      "locations": [location.to_dict() for location in locations]}
            if error is not None:
                record["exception"] = exception_details(error)
            encoded = _json(record) + b"\n"
            self._run.pending.extend(encoded)
            self._run.sequence = sequence
            if flush or len(self._run.pending) >= self._run.buffer_bytes:
                self._run.flush()
            return identifier

    def flush(self):
        with self._run.lock:
            self._run.flush()


def read_events(path: Path | str):
    """Stream strict records for inspection; malformed history stays visible."""
    def reject_constant(value):
        raise ValueError(f"Non-JSON number: {value}")

    path = Path(path)
    with path.open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            try:
                if not raw.endswith(b"\n"):
                    raise ValueError("incomplete record")
                event = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
                if not isinstance(event, dict) or event.get("schema") != SCHEMA:
                    raise ValueError("unknown event schema")
                for key in ("id", "run_id", "time", "code"):
                    if not isinstance(event.get(key), str) or not event[key]:
                        raise ValueError(f"missing or invalid {key}")
                if type(event.get("sequence")) is not int or event["sequence"] < 1:
                    raise ValueError("invalid event sequence")
                if event["id"] != f"{event['run_id']}:{event['sequence']}":
                    raise ValueError("event id does not match run and sequence")
                if event.get("level") not in LEVELS:
                    raise ValueError("unknown event level")
                if datetime.fromisoformat(event["time"]).utcoffset() != timezone.utc.utcoffset(None):
                    raise ValueError("event time must be UTC")
                for key in ("message", "stage"):
                    if not isinstance(event.get(key), str):
                        raise ValueError(f"invalid {key}")
                for key in ("context", "data"):
                    if not isinstance(event.get(key), dict):
                        raise ValueError(f"invalid {key}")
                if not isinstance(event.get("locations"), list):
                    raise ValueError("invalid locations")
                for location in event["locations"]:
                    Location(**location)
                if "exception" in event and not isinstance(event["exception"], dict):
                    raise ValueError("invalid exception")
            except (ValueError, TypeError) as error:
                raise ValueError(f"Invalid event in {path} at line {line}: {error}") from error
            yield event
