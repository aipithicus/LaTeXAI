"""Reusable logging primitives: snapshots, ordering, coordinates and append safety."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.event_log import EventLogger, JsonlSink, Location, MemorySink, read_events


PROJECT = Path(__file__).resolve().parents[1]


class EventLoggerTests(unittest.TestCase):
    def test_events_are_buffered_snapshots_and_bound_context_is_shared_not_mutated(self):
        sink = MemorySink()
        context = {"document": {"id": "paper"}}
        log = EventLogger(sink, run_id="run", context=context)
        child = log.bind(stage="interpretation", unit_id="unit-1")
        data = {"values": [1]}
        identifier = child.emit("unit.started", "Unicode α\nsecond line", data=data)
        context["document"]["id"] = "changed"
        data["values"].append(2)
        self.assertEqual(sink.events, [])
        log.emit("run.checkpoint")
        child.flush()
        first, second = sink.events
        self.assertEqual(identifier, "run:1")
        self.assertEqual(first["data"], {"values": [1]})
        self.assertEqual(first["context"], {"document": {"id": "paper"}, "unit_id": "unit-1"})
        self.assertEqual(first["stage"], "interpretation")
        self.assertNotIn("unit_id", second["context"])
        first["data"]["values"].append(99)
        self.assertEqual(sink.events[0]["data"], {"values": [1]})

    def test_bound_threads_share_one_ordered_sequence(self):
        sink = MemorySink()
        log = EventLogger(sink, run_id="concurrent", buffer_bytes=1)
        def produce(worker):
            child = log.bind(stage="interpretation", worker=worker)
            for i in range(30):
                child.emit("unit.completed", data={"local_sequence": i})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(produce, range(4)))
        events = sink.events
        self.assertEqual([e["sequence"] for e in events], list(range(1, 121)))
        self.assertEqual(len({e["id"] for e in events}), 120)
        self.assertEqual({e["run_id"] for e in events}, {"concurrent"})

    def test_locations_make_master_and_raw_source_distinct(self):
        sink = MemorySink()
        log = EventLogger(sink)
        log.emit("unit.deferred", locations=(
            Location("master.tex", start=10, end=20, precision="enclosing", sha256="a" * 64),
            Location("part.tex", basis="source", start=40, end=50, occurrence=2, line=3),
            Location("bad.tex", basis="source", start=4, end=5, coordinate_domain="bytes")), flush=True)
        prepared, original, encoded = sink.events[0]["locations"]
        self.assertEqual(prepared["basis"], "artifact")
        self.assertEqual(prepared["precision"], "enclosing")
        self.assertNotIn("occurrence", prepared)
        self.assertEqual(original["occurrence"], 2)
        self.assertEqual(encoded["coordinate_domain"], "bytes")
        for kwargs in ({"start": 1}, {"start": 3, "end": 2}, {"line": 0},
                       {"occurrence": 1}, {"basis": "guess"}, {"sha256": "bad"},
                       {"precision": "exact"}, {"start": 0, "end": 1, "precision": "guess"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Location("master.tex", **kwargs)

    def test_exception_chain_does_not_capture_locals_or_read_source(self):
        sink = MemorySink()
        log = EventLogger(sink)
        secret_local = "NOT IN LOG"
        try:
            try:
                raise ValueError("inner")
            except ValueError as error:
                raise RuntimeError("outer") from error
        except RuntimeError as error:
            with patch("linecache.getline", side_effect=AssertionError("source reread")):
                log.emit("unit.failed", level="error", error=error, flush=True)
        event = sink.events[0]
        self.assertEqual(event["exception"]["cause"]["message"], "inner")
        self.assertEqual(event["exception"]["type"], "builtins.RuntimeError")
        self.assertTrue(event["exception"]["frames"])
        self.assertNotIn(secret_local, json.dumps(event))

    def test_invalid_data_does_not_consume_ids_or_change_existing_buffer(self):
        sink = MemorySink()
        log = EventLogger(sink, run_id="run")
        for data in ({1: "non-string key"}, {"n": float("nan")}, {"path": Path("x")}, []):
            with self.subTest(data=data), self.assertRaises((ValueError, TypeError)):
                log.emit("invalid", data=data)
        self.assertEqual(log.emit("valid", flush=True), "run:1")
        self.assertEqual(len(sink.events), 1)

    def test_failed_batch_is_not_retried_or_duplicated(self):
        class PartialSink:
            calls = 0
            def append(self, records):
                self.calls += 1
                raise OSError("short write after some bytes")
        sink = PartialSink()
        log = EventLogger(sink)
        log.emit("first")
        for action in (log.flush, log.flush, lambda: log.emit("second", flush=True)):
            with self.assertRaisesRegex(OSError, "short write"):
                action()
        self.assertEqual(sink.calls, 1)


class JsonlSinkTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "events.jsonl"

    def test_checkpoints_append_without_replaying_or_copying_history(self):
        first = EventLogger(JsonlSink(self.path), run_id="one")
        first.emit("started")
        self.assertFalse(self.path.exists())
        first.flush()
        before = self.path.read_bytes()
        with patch.object(Path, "read_bytes", side_effect=AssertionError("history replay")), patch.object(
                Path, "read_text", side_effect=AssertionError("history replay")):
            second = EventLogger(JsonlSink(self.path), run_id="two")
            second.emit("started", "line one\nline two α", flush=True)
        self.assertTrue(self.path.read_bytes().startswith(before))
        self.assertEqual([e["run_id"] for e in read_events(self.path)], ["one", "two"])
        self.assertEqual(len(self.path.read_bytes().splitlines()), 2)

    def test_incomplete_tail_is_preserved_and_reported(self):
        raw = b'{"interrupted":'
        self.path.write_bytes(raw)
        log = EventLogger(JsonlSink(self.path))
        with self.assertRaisesRegex(ValueError, "Incomplete JSONL tail"):
            log.emit("next", flush=True)
        self.assertEqual(self.path.read_bytes(), raw)
        with self.assertRaisesRegex(ValueError, "line 1"):
            list(read_events(self.path))

    def test_malformed_complete_record_is_not_silently_skipped(self):
        self.path.write_bytes(b'{"schema":"unknown"}\n')
        with self.assertRaisesRegex(ValueError, "unknown event schema"):
            list(read_events(self.path))

    def test_reader_reports_invalid_envelopes_and_coordinates_with_line_number(self):
        sink = MemorySink()
        EventLogger(sink).emit("valid", flush=True)
        original = sink.events[0]
        for change in ({"sequence": 0}, {"id": "wrong"}, {"time": "not a time"},
                       {"time": "2026-10-24T12:00:00"}, {"data": []},
                       {"level": "fatal"}, {"context": {"number": float("nan")}},
                       {"locations": [{"artifact": "master.tex", "start": 3, "end": 1}]}):
            with self.subTest(change=change):
                self.path.write_text(json.dumps(original) + "\n" + json.dumps({**original, **change}) + "\n",
                                     encoding="utf-8")
                events = read_events(self.path)
                self.assertEqual(next(events), original)
                with self.assertRaisesRegex(ValueError, "line 2"):
                    next(events)


if __name__ == "__main__":
    unittest.main()
