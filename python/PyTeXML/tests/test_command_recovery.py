"""Recovery acceptance: failed attempts undo effects, not committed evidence."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.assets import AssetConversionError
from src.event_log import read_events
from src.prepare.pipeline import preprocess_paper
from src.prepare.recovery import ResourceFailure
from src.prepare.recovery import _record_recovery
from src.prepare.session import PreparationSession
from src.reading.contracts import ReadingIssue, SourceCommand, TokenListMeaning
from src.reading.options import OptionScope


class CommandRecoveryTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def prepare(self):
        return preprocess_paper(str(self.root), root_tex="main.tex", tex_resource_roots=())

    def test_failed_command_rolls_back_all_participants_and_resumes_once(self):
        self.put("good.tex", r"GOOD\gdef\keep{K}")
        self.put("main.tex", r"\documentclass{article}\usepackage{listings}"
                 r"\input{good}BEFORE\lstinputlisting{missing.py}AFTER"
                 r"\def\expected{K}\ifx\keep\expected RIGHT\else WRONG\fi\input{good}TAIL")
        original = PreparationSession._command
        visited, sessions = [], []
        def command(session, item):
            if item.action != "external_literal":
                return original(session, item)
            visited.append(item.span)
            sessions.append(session)
            session.context.push_scope()
            session.context.endlinechar = -1
            session.context.record_meaning("leaked", TokenListMeaning(item.span, ()))
            session.dispatcher.loads.record("package", "phantom", item.unit_id, session.context, item.span)
            session.dispatcher.options = OptionScope("phantom", (), (), False, session.context.scope_depth)
            session.dispatcher._pending.append(item)
            session.frames[-1].packages.append(("phantom", [], item, False))
            session.forwarded_options["phantom"] = ()
            session.resolver.load_package("graphicx")
            session.require(item.span, "speculative", "must disappear", unit_id=item.unit_id)
            session.manifest.warnings.append({"detail": "speculative"})
            session.emit(item.span, "LEAKED-OUTPUT")
            session.edit_payload(item.span, "LEAKED-PAYLOAD")
            raise ResourceFailure("injected_partial_failure", "after mutation", requested="missing.py", outcome="failed")
        with patch.object(PreparationSession, "_command", command):
            text, manifest, output, _ = self.prepare()
        session = sessions[0]
        self.assertEqual(len(visited), 1)
        self.assertEqual(text.count("GOOD"), 2)
        self.assertIn("AFTER", text)
        self.assertIn("RIGHT", text)
        self.assertNotIn("WRONG", text)
        self.assertNotIn("LEAKED", text)
        self.assertIn("TAIL", text)
        self.assertIsNone(session.context.lookup_meaning("leaked"))
        self.assertEqual(session.context.scope_depth, 0)
        self.assertEqual(session.context.endlinechar, 13)
        self.assertNotIn("phantom", session.forwarded_options)
        self.assertNotIn("graphicx", session.resolver.active_packages)
        self.assertFalse(session.dispatcher._pending)
        self.assertFalse(session.payload_edits)
        self.assertFalse(any(r["reason"] == "speculative" for r in manifest.requirements))
        self.assertFalse(manifest.warnings)
        self.assertNotIn(("package", "phantom"), session.dispatcher.loads.loaded)
        failures = [r for r in manifest.dependencies if r["outcome"] == "failed"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["recovery"]["checkpoint"], "command")
        events = [e for e in read_events(output / "preparation.jsonl") if e["code"] == "resource.tombstone"]
        self.assertEqual([e["data"]["item_id"] for e in events], [failures[0]["item_id"]])

    def test_failure_after_expansion_restores_constructed_name_and_earlier_write(self):
        self.put("main.tex", r"\documentclass{article}\let\earlier\relax"
                 r"\expandafter\let\csname fresh\endcsname=\relax"
                 r"\def\later{L}TAIL")
        original = PreparationSession._command
        sessions, earlier = [], []
        restored = []
        def command(session, item):
            if item.action == "meaning_assignment" and session.raw(item.span).startswith(r"\expandafter"):
                self.assertIsNotNone(session.context.lookup_meaning("fresh"))
                sessions.append(session)
                earlier.append(session.context.lookup_meaning("earlier"))
                raise ReadingIssue("injected_owner_failure", "reject after expansion and assignment")
            return original(session, item)
        def record(session, item, error, **options):
            if error.reason == "injected_owner_failure":
                self.assertIsNone(session.context.lookup_meaning("fresh"))
                self.assertEqual(session.context.lookup_meaning("earlier"), earlier[0])
                restored.append(True)
            return _record_recovery(session, item, error, **options)
        with patch.object(PreparationSession, "_command", command), patch(
                "src.prepare.recovery._record_recovery", side_effect=record):
            text, manifest, _, _ = self.prepare()
        self.assertTrue(any(r["reason"] == "injected_owner_failure" for r in manifest.unresolved))
        self.assertIsNone(sessions[0].context.lookup_meaning("fresh"))
        self.assertEqual(restored, [True])
        self.assertTrue(sessions[0].context.recovery_contexts)
        self.assertIsNotNone(sessions[0].context.lookup_definition("later"))
        self.assertIn("TAIL", text)

    def test_failed_request_with_changed_input_retains_whole_region(self):
        self.put("main.tex", r"\documentclass{article}\usepackage{comment}\includecomment{keep}" +
                 "\nBEFORE\\begin{keep}\nINSIDE\n\\end{keep}\nAFTER")
        original = PreparationSession._command
        visited = []
        def command(session, item):
            if item.action == "transparent_begin":
                visited.append(item.span)
                raise ReadingIssue("injected_replay_failure", "replay input has no scanned caller continuation")
            return original(session, item)
        with patch.object(PreparationSession, "_command", command):
            text, manifest, _, _ = self.prepare()
        self.assertEqual(len(visited), 1)
        self.assertIn("BEFORE", text)
        self.assertIn("\\begin{keep}\nINSIDE\n\\end{keep}\nAFTER", text)
        self.assertTrue(manifest.preserved_source_spans)
        self.assertTrue(any(r["reason"] == "injected_replay_failure" for r in manifest.unresolved))

    def test_nested_rollback_preserves_one_correlated_failure_and_assumption(self):
        self.put("main.tex", r"\input{missing}AFTER")
        session = PreparationSession(self.root, root_tex="main.tex", tex_resource_roots=())
        outer = session.recovery.begin(language=True, preparation=True, boundary="enclosing_input")
        item = session.dispatcher.next_item()
        self.assertIsInstance(item, SourceCommand)
        inner = session.dispatcher.command_attempt
        error = ResourceFailure("missing_dependency", "absent", requested="missing", outcome="absent")
        record = session.recovery.recover(inner, item, error)
        self.assertIs(session.recovery.recover(inner, item, error), record)
        outer.rollback()
        self.assertEqual([r["item_id"] for r in session.manifest.dependencies], [record["item_id"]])
        self.assertEqual(len(session.manifest.requirements), 1)
        self.assertEqual(len(session.recovery_items), 1)
        self.assertEqual(len(session.units.uncertainty), 1)
        self.assertEqual(session.context.recovery_contexts, tuple(record["recovery"]["assumptions"]))
        self.assertIn(item.unit_id, session.units.records)
        self.assertIs(session.manifest.dependencies[0], session.recovery_items[0][1])

    def test_partial_asset_output_is_rolled_back_and_later_asset_commits(self):
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}"
                 r"\includegraphics{bad.pdf}BETWEEN\includegraphics{good.pdf}AFTER")
        self.put("bad.pdf", "bad")
        self.put("good.pdf", "good")
        def convert(source, target, **kwargs):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("partial" if source.name == "bad.pdf" else "<svg/>", encoding="utf-8")
            if source.name == "bad.pdf":
                raise AssetConversionError("failed after writing")
            return True
        with patch("src.prepare.assets.convert_asset_to_svg", convert):
            text, manifest, output, _ = self.prepare()
        self.assertFalse((output / "bad.svg").exists())
        self.assertEqual((output / "good.svg").read_text(encoding="utf-8"), "<svg/>")
        self.assertIn("BETWEEN", text)
        self.assertIn("AFTER", text)
        failed = next(r for r in manifest.dependencies if r["outcome"] == "failed")
        self.assertEqual(failed["recovery"]["checkpoint"], "asset_conversion")

    def test_failed_after_hook_keeps_attempt_evidence_outside_input_rollback(self):
        self.put("child.tex", "CHILD")
        self.put("main.tex", r"\documentclass{article}"
                 r"\AddToHook{file/child.tex/after}{\typeout{AFTER-DONE}}"
                 r"\AddToHook{file/after}{\unknown}BEFORE\input{child}TAIL")
        text, manifest, output, _ = self.prepare()
        self.assertIn("BEFORE", text)
        self.assertIn("TAIL", text)
        self.assertIn(r"\input{child.tex}", text)
        self.assertEqual((output / "child.tex").read_text(encoding="utf-8"), "CHILD")
        event, = manifest.file_events
        self.assertEqual(event["status"], "retained")
        completed = next(e for e in event["events"] if e["hook"] == "file/child.tex/after")
        self.assertEqual(completed["diagnostics"], ["AFTER-DONE"])


if __name__ == "__main__":
    unittest.main()
