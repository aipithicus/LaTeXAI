"""Preparation attempt history survives publication and rollback independently."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.event_log import EventLogger, JsonlSink, MemorySink, read_events
from src.prepare.pipeline import preprocess_paper
from src.prepare.events import record_locations
from src.prepare.session import PreparationUnresolved


PROJECT = Path(__file__).resolve().parents[1]


class PreparationLoggingTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.output = self.root / "source", self.root / "prepared"
        self.source.mkdir()
        self.journal = self.output / "preparation.jsonl"
        self.put("OLD")

    def put(self, text):
        (self.source / "main.tex").write_text("\\documentclass{article}\n" + text, encoding="utf-8")

    def prepare(self, **kwargs):
        return preprocess_paper(str(self.source), str(self.output), root_tex="main.tex", **kwargs)

    def events(self):
        return list(read_events(self.journal))

    def test_reruns_append_history_by_rename_and_retain_legacy_evidence(self):
        self.prepare()
        before, inode = self.journal.read_bytes(), self.journal.stat().st_ino
        legacy = self.output / "preparation.log"
        legacy.write_bytes(b"historical text\r\n")
        original_read = Path.read_bytes
        def read(path):
            if path.name in {"preparation.jsonl", "preparation.log"}:
                raise AssertionError("Whole-history replay")
            return original_read(path)
        self.put("NEW")
        with patch.object(Path, "read_bytes", read), patch("shutil.copyfile", side_effect=AssertionError("History copy")):
            self.prepare()
        self.assertTrue(self.journal.read_bytes().startswith(before))
        self.assertEqual(self.journal.stat().st_ino, inode)
        self.assertEqual(legacy.read_bytes(), b"historical text\r\n")
        events = self.events()
        self.assertEqual(sum(e["code"] == "attempt.started" for e in events), 2)
        self.assertEqual(sum(e["code"] == "attempt.published" for e in events), 2)
        self.assertEqual(len({e["run_id"] for e in events}), 2)
        self.assertFalse(list(self.root.glob(".pytexml-publish-*")))

    def test_failed_rerun_records_failure_without_replacing_published_payload(self):
        self.prepare()
        master = (self.output / "master.tex").read_bytes()
        manifest = (self.output / "manifest.json").read_bytes()
        self.put(r"\input{missing}")
        with self.assertRaises(PreparationUnresolved):
            self.prepare()
        failure = self.events()[-1]
        self.assertEqual(failure["code"], "attempt.failed")
        self.assertTrue(failure["data"]["previous_payload_preserved"])
        self.assertFalse(failure["data"]["payload_published"])
        self.assertIn("missing", failure["exception"]["message"])
        self.assertEqual((self.output / "master.tex").read_bytes(), master)
        self.assertEqual((self.output / "manifest.json").read_bytes(), manifest)

    def test_publication_rollback_restores_journal_and_never_claims_publish_success(self):
        self.prepare()
        inode = self.journal.stat().st_ino
        self.put("NEW")
        original = os.replace
        def fail(source, target):
            if Path(source).name == "payload":
                raise OSError("publication fault")
            return original(source, target)
        with patch("src.prepare.publication.os.replace", side_effect=fail), self.assertRaisesRegex(OSError, "publication fault"):
            self.prepare()
        events = self.events()
        latest = events[-1]["run_id"]
        self.assertNotIn("attempt.published", [e["code"] for e in events if e["run_id"] == latest])
        self.assertEqual(self.journal.stat().st_ino, inode)
        self.assertTrue(events[-1]["data"]["previous_payload_preserved"])

    def test_failed_journal_transfer_restores_previous_history(self):
        self.prepare()
        original = os.replace
        def fail(source, target):
            if Path(source).name == "preparation.jsonl" and Path(source).parent.name == "previous":
                raise OSError("journal transfer fault")
            return original(source, target)
        with patch("src.prepare.publication.os.replace", side_effect=fail), self.assertRaisesRegex(OSError, "journal transfer"):
            self.prepare()
        self.assertEqual(self.events()[-1]["code"], "attempt.failed")
        self.assertIn("OLD", (self.output / "master.tex").read_text())

    def test_failed_first_publication_has_failure_manifest_without_final_addresses(self):
        self.put("$x$")
        original = os.replace
        def fail(source, target):
            if Path(source).name == "payload":
                raise OSError("publication fault")
            return original(source, target)
        with patch("src.prepare.publication.os.replace", side_effect=fail), self.assertRaises(OSError):
            self.prepare()
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["preparation_status"], "failed")
        self.assertIsNone(manifest["entrypoint"])
        self.assertEqual(manifest["prepared_artifacts"], [])
        self.assertTrue(manifest["requirements"])
        self.assertTrue(all(not r["locations"] for r in manifest["requirements"]))
        self.assertFalse((self.output / "master.tex").exists())
        self.assertEqual(self.events()[-1]["code"], "attempt.failed")

    def test_failed_rollback_logs_at_retained_recovery_location(self):
        self.prepare()
        original = os.replace
        def fail(source, target):
            if Path(source).name in {"payload", "preparation.jsonl"} and Path(source).parent.name != "previous":
                raise OSError("publication and journal rollback fault")
            return original(source, target)
        with patch("src.prepare.publication.os.replace", side_effect=fail), self.assertRaisesRegex(RuntimeError, "rollback failed"):
            self.prepare()
        recovered = list(self.root.glob(".pytexml-publish-*/payload/preparation.jsonl"))
        self.assertEqual(len(recovered), 1)
        failure = list(read_events(recovered[0]))[-1]
        self.assertEqual(failure["code"], "attempt.failed")
        self.assertTrue(failure["data"]["recovery_needed"])
        self.assertFalse(failure["data"]["previous_payload_preserved"])
        self.assertEqual(failure["data"]["recovery_directories"], [str(recovered[0].parent.parent)])
        self.assertTrue((recovered[0].parent.parent / "previous/master.tex").is_file())

    def test_incomplete_journal_does_not_change_previous_payload_or_history(self):
        self.prepare()
        before = (self.output / "master.tex").read_bytes()
        raw = self.journal.read_bytes() + b'{"interrupted":'
        self.journal.write_bytes(raw)
        self.put("NEW")
        with self.assertRaisesRegex(ValueError, "Incomplete JSONL tail"):
            self.prepare()
        self.assertEqual(self.journal.read_bytes(), raw)
        self.assertEqual((self.output / "master.tex").read_bytes(), before)

    def test_log_projection_preserves_enclosing_precision_and_raw_fallback(self):
        prepared = record_locations({"locations": [{"artifact": "master.tex", "start": 5,
            "end": 10, "precision": "enclosing"}], "source": "raw.tex"}, {"master.tex": "a" * 64})
        self.assertEqual(prepared[0].precision, "enclosing")
        self.assertEqual(prepared[0].basis, "artifact")
        raw = record_locations({"source": "raw.tex", "start": 8, "end": 10, "occurrence": 2}, {})
        self.assertEqual(raw[0].basis, "source")
        self.assertEqual(raw[0].occurrence, 2)

    def test_supplied_logger_can_collect_preparation_and_downstream_events_without_a_local_log(self):
        sink = MemorySink()
        root = EventLogger(sink, run_id="pipeline")
        self.put(r"A $x$ \unknown{B}")
        _, manifest, _, _ = self.prepare(logger=root)
        self.assertFalse(self.journal.exists())
        requirements = [e for e in sink.events if e["code"] == "requirement.deferred"]
        self.assertTrue(requirements)
        self.assertTrue(all(e["data"]["unit_id"] for e in requirements))
        self.assertTrue(any(loc["artifact"] == "master.tex" and loc["basis"] == "artifact" and loc["sha256"]
                            for e in requirements for loc in e["locations"]))
        root.bind(stage="interpretation", unit_id="later-1").emit("unit.started", flush=True)
        self.assertEqual(sink.events[-1]["stage"], "interpretation")
        self.assertEqual({e["run_id"] for e in sink.events}, {"pipeline"})
        self.assertEqual(sink.events[-2]["data"]["preparation_status"], manifest.preparation_status)

    def test_logging_error_does_not_hide_original_failure(self):
        self.put(r"\input{missing}")
        append = JsonlSink.append
        def fail(sink, batch):
            if b'"attempt.failed"' in batch:
                raise OSError("failure log unavailable")
            return append(sink, batch)
        with patch.object(JsonlSink, "append", fail), self.assertRaises(PreparationUnresolved) as caught:
            self.prepare()
        self.assertIn("missing", str(caught.exception))
        self.assertTrue(any("failure log unavailable" in note for note in caught.exception.__notes__))

    def test_completion_log_failure_reports_that_payload_is_already_published(self):
        append = JsonlSink.append
        def fail(sink, batch):
            if b'"attempt.published"' in batch:
                raise OSError("completion log unavailable")
            return append(sink, batch)
        with patch.object(JsonlSink, "append", fail), self.assertRaisesRegex(OSError, "completion log") as caught:
            self.prepare()
        self.assertTrue((self.output / "master.tex").exists())
        self.assertTrue(any("already published" in note for note in caught.exception.__notes__))
        self.assertEqual(self.events()[-1]["code"], "publication.started")


if __name__ == "__main__":
    unittest.main()
