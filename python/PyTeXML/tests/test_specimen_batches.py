"""Development checkpoints retain honest outcomes without duplicating sources."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import yaml

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.validation.specimens import (identifier, load_catalog, run_batch, source_fingerprint,
    share_resources, refresh_index, render_specimen, read_json, write_json, summarize)


class SpecimenBatchTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.specimens = self.root / "specimens"
        self.specimens.mkdir()
        self.runs = self.root / "runs"
        self.catalog = self.specimens / "catalog.yaml"
        self.records = {}
        identity = patch("src.validation.specimens.code_identity", return_value={"commit": "fixture", "sha256": "abc"})
        identity.start()
        self.addCleanup(identity.stop)
        self.add_specimen("one")

    def add_specimen(self, name):
        source = self.specimens / name
        source.mkdir()
        (source / "paper.tex").write_text(r"\documentclass{article}\begin{document}Hello\end{document}", encoding="utf-8")
        self.records[name] = {"title": name + " paper", "source": name, "main": "paper.tex"}
        self.catalog.write_text(yaml.safe_dump({"schema": "pytexml-specimens/1", "specimens": self.records}), encoding="utf-8")
        return source

    def fake_prepare(self, command, **kwargs):
        source, prepared = Path(command[-3]), Path(command[-2])
        prepared.mkdir()
        (prepared / "master.tex").write_bytes((source / "paper.tex").read_bytes())
        (prepared / "plot.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        write_json(prepared / "manifest.json", {"preparation_status": "partial",
                   "requirements": [{"stage": "interpretation"}], "source_reads": ["paper.tex"]})
        kwargs["stdout"].write(b"fixture console\n")
        return subprocess.CompletedProcess(command, 0)

    def run_fake(self, name, selected=()):
        with patch("src.validation.specimens.subprocess.run", side_effect=self.fake_prepare):
            return run_batch(self.catalog, self.runs, name, "Test iteration", selected)

    def test_real_preparation_entrypoint_produces_a_navigable_checkpoint(self):
        source = self.specimens / "one"
        Image.new("RGB", (3, 2), "red").save(source / "plot.png")
        (source / "paper.tex").write_text(r"\documentclass{article}\usepackage{graphicx}\begin{document}\includegraphics{plot.png}\end{document}", encoding="utf-8")
        before = source_fingerprint(source)
        result = run_batch(self.catalog, self.runs, "baseline", "Exercise the public preparation entry point")
        self.assertEqual(result["status"], "finished")
        item = result["results"]["one"]
        self.assertTrue(item["master"])
        self.assertEqual(item["summary"]["svg_assets"], 1)
        self.assertEqual(source_fingerprint(source), before)
        self.assertIn("baseline/README.md", (self.runs / "INDEX.md").read_text(encoding="utf-8"))
        self.assertIn("one/prepared/master.tex", (self.runs / "baseline/README.md").read_text(encoding="utf-8"))
        self.assertFalse((self.runs / "baseline/one/prepared/plot.png").exists())

    def test_identical_generated_assets_are_read_only_hard_links_but_masters_are_independent(self):
        first = self.run_fake("first")
        second = self.run_fake("second")
        left = self.runs / "first/one/prepared"
        right = self.runs / "second/one/prepared"
        self.assertTrue(os.path.samefile(left / "plot.svg", right / "plot.svg"))
        self.assertFalse(os.path.samefile(left / "master.tex", right / "master.tex"))
        self.assertFalse((right / "plot.svg").stat().st_mode & stat.S_IWRITE)
        self.assertEqual(second["results"]["one"]["storage"]["reused_files"], 1)
        self.assertEqual(second["results"]["one"]["changes"]["changed"], [])
        self.assertEqual(first["results"]["one"]["storage"]["reused_files"], 0)
        self.assertEqual(len(list((self.runs / "resources").iterdir())), 1)

    def test_source_change_is_explicit_and_master_diff_is_retained(self):
        self.run_fake("before")
        (self.specimens / "one/paper.tex").write_text("CHANGED\n", encoding="utf-8")
        result = self.run_fake("after")
        changes = result["results"]["one"]["changes"]
        self.assertFalse(changes["same_source"])
        self.assertEqual(changes["previous_batch"], "before")
        self.assertIn("master.tex", changes["changed"])
        self.assertIn("+CHANGED", (self.runs / "after/one/master.diff").read_text())

    def test_existing_batch_cannot_be_overwritten(self):
        self.run_fake("same")
        before = (self.runs / "same/run.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_fake("same")
        self.assertEqual((self.runs / "same/run.json").read_bytes(), before)

    def test_failed_and_timed_out_papers_do_not_prevent_later_preparation(self):
        self.add_specimen("two")
        self.add_specimen("three")

        def prepare(command, **kwargs):
            source = Path(command[-3]).name
            if source == "one":
                kwargs["stdout"].write(b"REAL FAILURE\n")
                return subprocess.CompletedProcess(command, 1)
            if source == "two":
                raise subprocess.TimeoutExpired(command, 180)
            return self.fake_prepare(command, **kwargs)

        with patch("src.validation.specimens.subprocess.run", side_effect=prepare):
            result = run_batch(self.catalog, self.runs, "mixed", "Keep independent outcomes", ["one", "two", "three"])
        self.assertEqual(result["status"], "finished_with_failures")
        self.assertEqual([r["status"] for r in result["results"].values()], ["failed", "timeout", "partial"])
        self.assertIn("REAL FAILURE", (self.runs / "mixed/one/console.log").read_text())
        self.assertTrue((self.runs / "mixed/three/prepared/master.tex").is_file())

    def test_subset_runs_keep_unselected_specimens_visible_in_index_and_preserve_notes(self):
        self.add_specimen("two")
        self.run_fake("all")
        notes = self.runs / "all/NOTES.md"
        notes.write_text("MY INVESTIGATION\n", encoding="utf-8")
        self.run_fake("subset", ["one"])
        refresh_index(self.runs)
        text = (self.runs / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("one — one paper | [subset]", text)
        self.assertIn("two — two paper | [all]", text)
        self.assertEqual(notes.read_text(), "MY INVESTIGATION\n")

    def test_generated_extracted_tree_is_excluded_from_source_identity(self):
        source = self.specimens / "one"
        before = source_fingerprint(source)
        (source / "extracted").mkdir()
        (source / "extracted/master.tex").write_text("historical output")
        self.assertEqual(source_fingerprint(source), before)

    def test_summary_uses_validated_bibliography_count_instead_of_command_spelling(self):
        prepared = self.root / "prepared"
        prepared.mkdir()
        (prepared / "master.tex").write_text(r"\harvarditem{Author}{2000}{key}", encoding="utf-8")
        write_json(prepared / "manifest.json", {"bibliography": {"citations_count": 1}})
        self.assertEqual(summarize(prepared)["bibitems"], 1)

    def test_catalog_rejects_escaping_main_and_duplicate_yaml_keys(self):
        self.records["one"]["main"] = "../catalog.yaml"
        self.catalog.write_text(yaml.safe_dump({"schema": "pytexml-specimens/1", "specimens": self.records}))
        with self.assertRaisesRegex(ValueError, "main"):
            load_catalog(self.catalog)
        self.catalog.write_text("schema: pytexml-specimens/1\nschema: duplicate\nspecimens: {}\n")
        with self.assertRaisesRegex(ValueError, "Duplicate YAML"):
            load_catalog(self.catalog)

    def test_invalid_labels_output_locations_and_selections_are_rejected(self):
        for name in ("../escape", "CON", "a/b", ".hidden", "trailing."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                identifier(name)
        for selected in (["missing"], ["one", "one"]):
            with self.assertRaisesRegex(ValueError, "distinct"):
                run_batch(self.catalog, self.runs, "bad", "test", selected)
        with self.assertRaisesRegex(ValueError, "separate"):
            run_batch(self.catalog, self.specimens / "one/runs", "bad", "test")

    def test_render_rejects_changed_sources_or_modified_prepared_checkpoint(self):
        self.run_fake("baseline")
        source = self.specimens / "one/paper.tex"
        original = source.read_bytes()
        source.write_text("altered")
        with self.assertRaisesRegex(ValueError, "Original source changed"):
            render_specimen(self.runs, "baseline", "one", "validation", None)
        source.write_bytes(original)
        (self.runs / "baseline/one/prepared/master.tex").write_text("altered")
        with self.assertRaisesRegex(ValueError, "Prepared checkpoint changed"):
            render_specimen(self.runs, "baseline", "one", "validation", None)

    def test_moved_source_is_found_through_the_catalog_only_while_its_bytes_match(self):
        self.run_fake("baseline")
        (self.specimens / "one").rename(self.specimens / "moved")
        self.records["one"]["source"] = "moved"
        self.catalog.write_text(yaml.safe_dump({"schema": "pytexml-specimens/1", "specimens": self.records}),
                                encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Recorded source is missing"):
            render_specimen(self.runs, "baseline", "one", "validation", None)
        seen = []
        with patch("src.validation.render.render_comparison",
                   side_effect=lambda source, *rest: seen.append(source) or {"status": "rendered"}):
            render_specimen(self.runs, "baseline", "one", "validation", None, catalog=self.catalog)
        self.assertEqual([Path(p).resolve() for p in seen], [(self.specimens / "moved").resolve()])
        (self.specimens / "moved/paper.tex").write_text("altered")
        with self.assertRaisesRegex(ValueError, "Original source changed"):
            render_specimen(self.runs, "baseline", "one", "validation", None, catalog=self.catalog)

    def test_changed_shared_resource_is_reported_not_reused(self):
        self.run_fake("first")
        resource = next((self.runs / "resources").iterdir())
        resource.chmod(stat.S_IREAD | stat.S_IWRITE)
        resource.write_text("corrupt")
        result = self.run_fake("second")
        self.assertEqual(result["results"]["one"]["status"], "failed")
        self.assertIn("Shared resource changed", result["results"]["one"]["error"])


if __name__ == "__main__":
    unittest.main()
