"""Broken-source extraction has its own gate, independent of native rendering."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.event_log import read_events
from src.prepare.pipeline import preprocess_paper, PreparationRejected
from src.prepare.session import PreparationSession
from src.source_io import SourceStore
from src.engine.resources import ResourceSearch


class ResourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def document(self, body, preamble=r"\usepackage{graphicx,listings}"):
        return self.put("main.tex", r"\documentclass{article}" + preamble +
                        "\n\\begin{document}" + body + r"\end{document}")

    def prepare(self, **kwargs):
        return preprocess_paper(str(self.root), root_tex="main.tex", tex_resource_roots=(), **kwargs)

    @staticmethod
    def failures(manifest):
        return [r for r in manifest.dependencies if r.get("recovery", {}).get("disposition") == "tombstone"]

    def test_independent_missing_items_have_output_and_log_correlations(self):
        self.document(r"BEFORE\includegraphics{first.pdf}BETWEEN\lstinputlisting{code.py}"
                      r"\input{first-input}MIDDLE\includegraphics{second.pdf}\input{second-input}AFTER")
        text, manifest, out, ledger = self.prepare()
        failures = self.failures(manifest)
        self.assertEqual([r["requested"] for r in failures],
                         ["first.pdf", "code.py", "first-input", "second.pdf", "second-input"])
        self.assertEqual({r["outcome"] for r in failures}, {"absent"})
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertEqual(manifest.original_resource_status, "unsatisfied")
        self.assertEqual(manifest.recovery_status, "complete")
        events = [e for e in read_events(out / "preparation.jsonl") if e["code"] == "resource.tombstone"]
        self.assertEqual({e["data"]["item_id"] for e in events}, {r["item_id"] for r in failures})
        for record in failures:
            self.assertIn(record["recovery"]["marker"], text)
            self.assertTrue(record["locations"])
            self.assertEqual(record["recovery"]["emission"], "placed")
            self.assertEqual(len([r for r in manifest.requirements if r.get("item_id") == record["item_id"]]), 1)
        self.assertLess(text.index("BEFORE"), text.index(failures[0]["recovery"]["marker"]))
        self.assertLess(text.index(failures[-1]["recovery"]["marker"]), text.index("AFTER"))
        self.assertIn("MIDDLE", text)
        self.assertEqual(ledger.master_length, len(text))
        self.assertFalse((out / "first.pdf").exists())
        self.assertFalse((out / "first-input.tex").exists())

    def test_authored_fallback_precedes_generated_recovery(self):
        self.document(r"\IfFileExists{intentional.pdf}{\includegraphics{intentional.pdf}}"
                      r"{FALLBACK}\includegraphics{active.pdf}AFTER")
        text, manifest, _, _ = self.prepare()
        self.assertIn("FALLBACK", text)
        self.assertEqual([r["requested"] for r in self.failures(manifest)], ["active.pdf"])
        self.assertFalse(manifest.conditional_decisions[0]["truth"])
        probe = next(r for r in manifest.dependencies if r["purpose"] == "probe")
        self.assertEqual(probe["outcome"], "absent")
        self.assertEqual(probe["recovery"]["disposition"], "authored_branch")

    def test_missing_asset_does_not_change_a_later_existence_test(self):
        self.document(r"\includegraphics{missing.pdf}"
                      r"\IfFileExists{missing.pdf}{WRONG}{STILL-ABSENT}AFTER")
        text, manifest, out, _ = self.prepare()
        self.assertIn("STILL-ABSENT", text)
        self.assertFalse(manifest.conditional_decisions[-1]["truth"])
        self.assertFalse((out / "missing.pdf").exists())

    def test_missing_input_invalidates_author_state_and_labels_later_reading(self):
        self.document(r"\def\known{OLD}\input{missing}\known TAIL")
        session = PreparationSession(self.root, root_tex="main.tex", tex_resource_roots=()).run()
        record = self.failures(session.manifest)[0]
        self.assertIn("meanings", record["affected_domains"])
        self.assertTrue(record["recovery"]["assumptions"])
        self.assertTrue(session.context.recovery_contexts)
        tail = [u for u in session.units.records.values() if u.span.start >= record["end"]]
        self.assertTrue(any(u.activity_evidence.get("recovery_context_ids") for u in tail))
        self.assertNotEqual(type(session.context.lookup_meaning("known")).__name__, "StoredDefinition")

    def test_unreadable_and_bad_encoding_are_not_absence(self):
        self.document(r"BEFORE\input{denied}\input{bad}\includegraphics{missing.pdf}AFTER")
        denied = self.put("denied.tex", "DENIED")
        bad = self.put("bad.tex", "")
        bad.write_bytes(b"\xff")
        original = SourceStore.read_bytes
        def read(store, path):
            if Path(path) == denied:
                raise PermissionError("denied witness")
            return original(store, path)
        with patch.object(SourceStore, "read_bytes", read):
            text, manifest, out, _ = self.prepare()
        self.assertEqual([r["outcome"] for r in self.failures(manifest)], ["unreadable", "failed", "absent"])
        self.assertIn("AFTER", text)
        self.assertEqual((out / "opaque-resources/bad.tex").read_bytes(), b"\xff")

    def test_unevaluated_filename_is_retained_not_absent(self):
        self.document(r"BEFORE\input{\unknown}\includegraphics{missing.pdf}AFTER")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\input{\unknown}", text)
        self.assertEqual([r["requested"] for r in self.failures(manifest)], ["missing.pdf"])
        self.assertTrue(manifest.unresolved)
        pending = next(r for r in manifest.dependencies if r["requested"] is None)
        self.assertEqual(pending["outcome"], "unresolved")
        self.assertEqual(pending["knowledge"]["name"], "unevaluated")
        self.assertEqual(pending["recovery"]["disposition"], "retained_source")

    def test_unspecified_external_search_is_not_absence(self):
        self.document(r"\includegraphics{missing.pdf}AFTER")
        text, manifest, _, _ = preprocess_paper(str(self.root), root_tex="main.tex")
        record = self.failures(manifest)[0]
        self.assertEqual(record["outcome"], "unresolved")
        self.assertFalse(record["search"]["external"]["closed"])
        self.assertIn(record["recovery"]["marker"], text)

    def test_ambiguous_lookup_keeps_candidates_and_later_failures(self):
        self.document(r"\includegraphics{plot}\includegraphics{missing.pdf}AFTER")
        self.put("plot.pdf", "PDF")
        self.put("plot.png", "PNG")
        text, manifest, _, _ = self.prepare()
        first, second = self.failures(manifest)
        self.assertEqual(first["outcome"], "ambiguous")
        self.assertEqual(set(first["search"]["candidates"]), {"plot.pdf", "plot.png"})
        self.assertEqual(second["outcome"], "absent")
        self.assertIn("AFTER", text)

    def test_rollback_preserves_failure_and_places_marker_in_retained_child(self):
        self.document(r"BEFORE\input{child}AFTER")
        self.put("child.tex", "CHILD\\includegraphics{missing.pdf}\n\\catcode`\\!=\\unknown !")
        text, manifest, out, _ = self.prepare()
        record = self.failures(manifest)[0]
        self.assertIn("AFTER", text)
        self.assertIn(record["recovery"]["marker"], (out / "child.tex").read_text())
        self.assertTrue(any(p["artifact"] == "child.tex" for p in record["locations"]))

    def test_strict_rejects_after_all_requests_and_preserves_prior_payload(self):
        self.document("ORIGINAL")
        _, _, out, _ = self.prepare()
        self.document(r"\includegraphics{one.pdf}\input{two}\includegraphics{three.pdf}AFTER")
        with self.assertRaises(PreparationRejected) as caught:
            self.prepare(recovery="strict")
        self.assertEqual(len(self.failures(caught.exception.manifest)), 3)
        self.assertEqual(caught.exception.manifest.acceptance_status, "rejected")
        self.assertTrue(caught.exception.manifest.source_survey)
        self.assertIn("ORIGINAL", (out / "master.tex").read_text())
        self.assertEqual(len([e for e in read_events(out / "preparation.jsonl")
                              if e["code"] == "resource.tombstone"]), 3)

    def test_converter_failure_does_not_cancel_other_assets(self):
        self.document(r"BEFORE\includegraphics{bad.png}\includegraphics{good.svg}AFTER")
        self.put("bad.png", "bad image")
        self.put("good.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        text, manifest, out, _ = self.prepare()
        self.assertEqual([r["outcome"] for r in self.failures(manifest)], ["failed"])
        self.assertIn("AFTER", text)
        self.assertIn(r"\includegraphics{good.svg}", text)
        self.assertTrue((out / "good.svg").exists())
        self.assertEqual(manifest.materialization_status, "partial")
        self.assertEqual(manifest.recovery_status, "complete")

    def test_output_write_error_is_not_a_source_conversion_failure(self):
        self.document(r"\includegraphics{good.svg}")
        self.put("good.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        original = Path.write_bytes
        def write(path, data):
            if path.name == "good.svg":
                raise PermissionError("output publication witness")
            return original(path, data)
        with patch.object(Path, "write_bytes", write):
            with self.assertRaisesRegex(PermissionError, "output publication witness"):
                self.prepare()

    def test_missing_package_batch_keeps_each_failure_and_other_names(self):
        self.document("BODY", preamble=r"\usepackage{first-missing,second-missing,graphicx}")
        text, manifest, _, _ = self.prepare()
        self.assertEqual([r["requested"] for r in self.failures(manifest)], ["first-missing"])
        self.assertIn(r"\usepackage{second-missing,graphicx}", text)
        self.assertTrue(any(r["reason"] == "package_load_state" and r["dependency"] == "possible"
                            for r in manifest.requirements))
        self.assertIn("BODY", text)

    def test_missing_bibliography_databases_are_all_reported(self):
        self.document(r"BEFORE\bibliography{first,available,second}AFTER")
        self.put("available.bib", "@misc{key,title={Available source}}")
        text, manifest, out, _ = self.prepare()
        self.assertEqual([r["requested"] for r in self.failures(manifest)], ["first.bib", "second.bib"])
        self.assertIn("AFTER", text)
        self.assertIn("Available source", (out / "available.bib").read_text())

    def test_retained_package_keeps_unresolved_siblings_and_projection(self):
        self.document("BODY", preamble=r"\usepackage{local}")
        self.put("local.sty", r"\RequirePackage{missing,graphicx}TAIL")
        _, manifest, out, _ = self.prepare()
        record = self.failures(manifest)[0]
        payload = (out / "local.sty").read_text()
        self.assertIn(record["recovery"]["marker"], payload)
        self.assertIn(r"\RequirePackage{graphicx}TAIL", payload)
        self.assertTrue(any(p["artifact"] == "local.sty" for p in record["locations"]))

    def test_unreadable_conditional_package_is_not_an_active_missing_item(self):
        self.document("BODY", preamble=r"\usepackage{missing,bad}")
        self.put("bad.sty", "").write_bytes(b"\xff")
        text, manifest, out, _ = self.prepare()
        self.assertEqual([r["requested"] for r in self.failures(manifest)], ["missing"])
        record = next(r for r in manifest.dependencies if r["requested"] == "bad")
        self.assertEqual(record["purpose"], "conditional_consume")
        self.assertEqual(record["recovery"]["disposition"], "retained_source")
        self.assertEqual(record["recovery"]["original_resource"], "unresolved")
        self.assertIn(r"\usepackage{bad}", text)
        self.assertEqual((out / "opaque-resources/bad.sty").read_bytes(), b"\xff")

    def test_bibliography_under_recovery_assumptions_does_not_prove_missing_entries(self):
        self.document(r"\cite{key}\bibliography{refs}AFTER", preamble=r"\usepackage{missing,natbib}")
        self.put("main.bbl", r"\begin{thebibliography}{1}\harvarditem{Author}{2000}{key}ENTRY\end{thebibliography}")
        _, manifest, _, _ = self.prepare()
        entry = next(r for r in manifest.dependencies if r["kind"] == "bibliography_entry")
        self.assertEqual(entry["outcome"], "unresolved")
        self.assertTrue(entry["activity_evidence"]["recovery_context_ids"])

    def test_unresolved_probe_keeps_the_established_name(self):
        self.document(r"\IfFileExists{named.tex}{YES}{NO}")
        _, manifest, _, _ = preprocess_paper(str(self.root), root_tex="main.tex")
        probe = next(r for r in manifest.dependencies if r["purpose"] == "probe")
        self.assertEqual(probe["requested"], "named.tex")
        self.assertEqual(probe["knowledge"]["name"], "established")
        self.assertEqual(probe["outcome"], "unresolved")

    def test_directory_access_failure_does_not_prove_absence(self):
        self.document(r"\includegraphics{locked/plot.pdf}\includegraphics{other.pdf}AFTER")
        original = SourceStore.__init__
        def initialize(store, *args, **kwargs):
            original(store, *args, **kwargs)
            store.inventory_errors.append(PermissionError(13, "denied directory", str(self.root / "locked")))
        with patch.object(SourceStore, "__init__", initialize):
            text, manifest, _, _ = self.prepare()
        self.assertEqual([r["outcome"] for r in self.failures(manifest)], ["unreadable", "absent"])
        self.assertIn("AFTER", text)

    def test_external_inventory_access_failure_does_not_prove_absence(self):
        self.document(r"\includegraphics{plot.pdf}AFTER")
        session = PreparationSession(self.root, root_tex="main.tex", tex_resource_roots=())
        external = self.root / "external"
        external.mkdir()
        def inaccessible(root, *, onerror):
            onerror(PermissionError(13, "external denied", str(root)))
            return iter(())
        with patch("src.engine.resources.os.walk", inaccessible):
            session.resources = ResourceSearch((external,))
        session.run()
        record = self.failures(session.manifest)[0]
        self.assertEqual(record["outcome"], "unreadable")
        self.assertFalse(record["search"]["external"]["inventory_complete"])

    def test_repeated_failed_occurrences_keep_distinct_identities(self):
        self.document(r"\input{child}BETWEEN\input{child}AFTER")
        self.put("child.tex", r"CHILD\includegraphics{absent.pdf}")
        text, manifest, _, _ = self.prepare()
        first, second = self.failures(manifest)
        self.assertNotEqual(first["item_id"], second["item_id"])
        self.assertNotEqual(first["occurrence"], second["occurrence"])
        self.assertEqual(text.count(first["recovery"]["marker"]), 1)
        self.assertEqual(text.count(second["recovery"]["marker"]), 1)

    def test_arbitrary_reader_bug_is_not_caught_as_a_resource_failure(self):
        self.document(r"\input{child}")
        self.put("child.tex", "CHILD")
        with patch.object(PreparationSession, "open_source", side_effect=RuntimeError("implementation witness")):
            with self.assertRaisesRegex(RuntimeError, "implementation witness"):
                self.prepare()

    def test_arbitrary_converter_bug_is_not_caught_as_a_resource_failure(self):
        self.document(r"\includegraphics{bad.pdf}")
        self.put("bad.pdf", "PDF")
        with patch("src.assets.fitz.open", side_effect=RuntimeError("converter implementation witness")):
            with self.assertRaisesRegex(RuntimeError, "converter implementation witness"):
                self.prepare()


if __name__ == "__main__":
    unittest.main()
