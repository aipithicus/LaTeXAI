# Structured events and preparation journals

[`src/event_log.py`](../src/event_log.py) provides logging primitives with no
dependency on the reader, preparation, bindings, rendering, or an XML schema.
The first consumer is preparation; downstream interpretation can use the same
interfaces and address its own artifacts directly.

## Event contract

Each UTF-8 JSONL line is an immutable snapshot with schema `pytexml-event/1`:

| Field | Meaning |
| --- | --- |
| `id` | `<run_id>:<sequence>`; unique within the owned run |
| `run_id`, `sequence` | Run identity and increasing event order starting at one |
| `time` | UTC timestamp with offset |
| `stage`, `code`, `level`, `message` | Producer-defined stage and stable event code, severity, explanatory text |
| `context` | Bound JSON data such as document, attempt, unit or requirement identity |
| `data` | Event-specific JSON object |
| `locations` | Explicit source or artifact addresses; empty when no address is known |
| `exception` | Optional type, message, traceback frame addresses, notes and cause/context chain |

Levels are `debug`, `info`, `warning`, `error`, and `critical`. Codes belong to
the producer; the logger does not interpret them or classify outcomes. Event
data requires string object keys and JSON values, without NaN or infinity.
Invalid input is rejected before consuming an event ID. Dictionaries and lists
are serialized at emission, so later mutations cannot alter queued evidence.

A `Location` names its artifact and states its basis (`source` or `artifact`).
Optional `[start, end)` offsets declare their coordinate domain:
`decoded_unicode_codepoints` by default, or `bytes`. Optional one-based `line`
and source inclusion `occurrence` support diagnostics. Artifact SHA-256 identifies
a version when available. Span `precision` can be `exact` or `enclosing`; a
containing span must not be presented as an exact address. No offset is inferred
from a filename or translated between bases by the logger.

Exception capture stores frame filenames, function names and line numbers. It
does not capture frame locals or reopen source files. Cause/context traversal is
bounded at eight exceptions; a cycle or depth limit is marked `truncated`.
Exception-group member traversal is not implemented. Exception messages and
producer-supplied data are recorded as supplied; this is not a redaction layer.

## Ownership, buffering and downstream use

`EventLogger` owns one run and sequence. `bind()` creates a child sharing that
state and sink while adding context or selecting a stage. The default run ID is
a fresh UUID; callers supplying IDs must ensure uniqueness across their runs.
Bound loggers can emit from multiple threads. The sequence orders observations
at the logger, **not** TeX source positions, semantic dependencies or causality
between asynchronous workers. Those require explicit unit/context references
in producer data. Multiple processes need separate journals or a single writer;
this module does not provide process locking or an asynchronous scheduler.

```python
from pathlib import Path
from src.event_log import EventLogger, JsonlSink, Location
from src.prepare.pipeline import preprocess_paper

# Caller-owned logs live outside the replaceable prepared payload.
log = EventLogger(JsonlSink(Path("runs/paper-events.jsonl")),
                  context={"document_id": "paper"})
_, manifest, _, _ = preprocess_paper("paper-source", logger=log)
unit = next(u for u in manifest.units if u["locations"])
hashes = {a["path"]: a["sha256"] for a in manifest.prepared_artifacts}
addresses = [Location(**loc, sha256=hashes[loc["artifact"]])
             for loc in unit["locations"]]
worker = log.bind(stage="interpretation", unit_id=unit["id"])
worker.emit("unit.started", locations=addresses)
# Interpret the unit using its finalized artifact coordinates.
log.flush()
```

This reads final artifact locations from the manifest, without consulting the
original-source provenance sidecar. A later reader over `master.tex` may supply
its own units and locations in exactly the same way. Logging does not introduce
a second unit registry or invent context snapshots that the reader lacks.

Records buffer in memory until `flush()`, `emit(..., flush=True)`, or the default
64 KiB byte threshold. A single larger event is allowed and immediately flushed.
There is no destructor or automatic final flush: the owner chooses checkpoints.
`JsonlSink` opens, appends, flushes and closes per batch; it holds no handle
between checkpoints. This is not fsync durability: a process crash can lose
buffered events, and a storage failure can leave a partial final record.

Append checks only the existing final byte, never rereads/copies the journal.
An incomplete tail is preserved and reported; there is no silent repair or
truncation. The owner must retain the evidence and choose a new journal or an
explicit recovery procedure. A sink error poisons that run's writer, preventing
automatic retry of a batch that may already have been partially written.
`read_events(path)` streams records and reports malformed JSON, invalid envelopes,
coordinates or incomplete lines with the journal path and physical line number.
It does not verify external artifact hashes or cross-record causal consistency.

`MemorySink` collects serialized snapshots without filesystem I/O. Another sink
can implement `append(records: bytes)` to accept a batch of complete JSONL lines.
An injected logger remains caller-owned; preparation flushes its checkpoints but
does not replace the sink or create an additional local journal.

## Preparation integration

[`prepare/events.py`](../src/prepare/events.py) owns the preparation vocabulary
and projects existing manifest records into events:

| Code | Evidence |
| --- | --- |
| `attempt.started` | A preparation attempt began |
| `phase.started`, `phase.completed` | Reading, bibliography, assets or emission phase boundary |
| `asset.dimensions_unavailable`, `bibliography.warning` | Existing resource diagnostics |
| `preparation.unresolved`, `preparation.warning` | Existing manifest diagnostics |
| `requirement.deferred` | Existing requirement/unit IDs, reason and remaining-work classification |
| `source.survey_unavailable` | A source could not be surveyed |
| `payload.prepared` | The payload was built in staging |
| `publication.started` | Publication is about to begin |
| `attempt.published` | Publication returned successfully, with manifest status and artifact hashes |
| `attempt.failed` | Exception evidence and whether payload publication already occurred |

An emitted `attempt.published` does not claim all reading or interpretation is
resolved. Its preparation/materialization statuses come from the manifest. The
logger has no independently mutable summary and does not replace the separate
[qualification diagnostics](qualification-diagnostics.md) rules or derived verdicts.

Preparation binds an `attempt_id` and output directory. By default each attempt
has its own run; an injected logger can group multiple attempts and downstream
events into one run. Requirement locations use finalized artifact addresses and
hashes when available, otherwise explicit source addresses. Pre-publication
events describe the attempted generation: their artifact references are usable
only if that attempt publishes, and their hashes may differ from a previous or
later generation at the same path.

Checkpoints flush at attempt start, transitions between major phases, before
publication, and on publication/failure. There is no per-token file I/O. Successful
reruns carry `preparation.jsonl` into the new payload by rename, preserving its
append history. Any older `preparation.log` is carried unchanged as historical
evidence, with no active text writer. Rendering excludes both from its input
resource set. Logs grow across attempts; automatic rotation/retention is not yet
implemented.

On a failed rerun, the previous payload and manifest remain intact while the
failure is appended. A failed first attempt may retain a failure manifest, but
never advertises an unpublished entrypoint or final addresses. Failed rollback
retains recovery directories and appends the event at the journal's actual
recovery location. A logging failure does not mask a preparation exception; it
is attached as an exception note. If completion logging fails after publication,
the exception explicitly states that the payload has already been published.
