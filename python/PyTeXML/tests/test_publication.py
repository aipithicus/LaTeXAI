"""Preparation errors and publication errors leave the last good payload intact."""
from pathlib import Path
from contextlib import chdir
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper
from src.event_log import read_events


class PublicationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "raw"
        self.source.mkdir()
        self.out = self.root / "prepared"
        self.put("OLD")

    def put(self, text):
        (self.source / "main.tex").write_text(r"\documentclass{article}" + text, encoding="utf-8")

    def prepare(self, **kwargs):
        return preprocess_paper(str(self.source), output_dir=str(self.out), root_tex="main.tex", **kwargs)

    def snapshot(self):
        return {p.relative_to(self.out).as_posix(): p.read_bytes() for p in self.out.rglob("*")
                if p.is_file() and p.name != "preparation.jsonl"}

    def test_write_error_after_manifest_keeps_every_previous_artifact(self):
        self.prepare()
        before = self.snapshot()
        self.put("NEW")
        write = Path.write_text
        def fail(path, *args, **kwargs):
            if path.name == "master.tex":
                raise OSError("injected master write failure")
            return write(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail), self.assertRaisesRegex(OSError, "injected"):
            self.prepare()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.root.glob(".pytexml-publish-*")))

    def test_publish_rename_failure_restores_old_directory(self):
        self.prepare()
        before = self.snapshot()
        self.put("NEW")
        replace = os.replace
        def fail(source, destination):
            if Path(source).name == "payload":
                raise OSError("injected rename failure")
            return replace(source, destination)
        with patch("src.prepare.publication.os.replace", side_effect=fail), self.assertRaisesRegex(OSError, "injected"):
            self.prepare()
        self.assertEqual(self.snapshot(), before)

    def test_secondary_failure_rolls_back_both_publications(self):
        secondary = self.root / "copy.tex"
        self.prepare(output_file=str(secondary))
        before, copy = self.snapshot(), secondary.read_bytes()
        self.put("NEW")
        replace = os.replace
        def fail(source, destination):
            if Path(source).name == "output":
                raise OSError("injected secondary failure")
            return replace(source, destination)
        with patch("src.prepare.publication.os.replace", side_effect=fail), self.assertRaisesRegex(OSError, "injected"):
            self.prepare(output_file=str(secondary))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(secondary.read_bytes(), copy)

    def test_success_replaces_stale_assets_and_excludes_staging_from_discovery(self):
        self.prepare()
        (self.out / "stale.svg").write_text("OLD")
        self.put("NEW")
        text, manifest, out, _ = self.prepare(output_file=str(self.out / "nested/copy.tex"))
        self.assertEqual(out, self.out)
        self.assertIn("NEW", text)
        self.assertNotIn("OLD", text)
        self.assertFalse((out / "stale.svg").exists())
        self.assertEqual((out / "nested/copy.tex").read_text(), text)
        self.assertEqual(manifest.source_reads, ["main.tex"])
        self.assertFalse(list(self.root.glob(".pytexml-publish-*")))

    def test_relative_paths_return_published_destination_and_keep_source_intact(self):
        before = (self.source / "main.tex").read_bytes()
        with chdir(self.root):
            text, manifest, output, ledger = preprocess_paper(
                "raw", "raw/../prepared", "copies/master.tex", "main.tex")
        self.assertEqual(output, self.out)
        self.assertEqual((self.root / "copies/master.tex").read_text(), text)
        self.assertEqual((output / "master.tex").read_text(), text)
        self.assertEqual((self.source / "main.tex").read_bytes(), before)
        self.assertEqual(manifest.source_reads, ["main.tex"])
        self.assertIsNotNone(ledger)

    def test_invalid_public_paths_fail_before_attempt_without_touching_sources(self):
        before = (self.source / "main.tex").read_bytes()
        for options, message in (
                ({"project_dir": str(self.root / "missing")}, "Project directory not found"),
                ({"output_dir": str(self.source)}, "Output directory must not contain"),
                ({"output_dir": str(self.root)}, "Output directory must not contain"),
                ({"output_file": str(self.source / "main.tex")}, "additional output inside the project")):
            with self.subTest(options=options), \
                    patch("src.prepare.pipeline.OutputTransaction", side_effect=AssertionError("Unexpected transaction")), \
                    self.assertRaisesRegex((FileNotFoundError, ValueError), message):
                preprocess_paper(**{"project_dir": str(self.source), "output_dir": str(self.out), **options})
        self.assertEqual((self.source / "main.tex").read_bytes(), before)
        self.assertFalse(self.out.exists())

    def test_retired_options_still_log_rejected_attempt_and_preserve_payload(self):
        self.prepare()
        before = self.snapshot()
        for options in ({"execute_probe": True}, {"drop_commands": ["bad"]},
                        {"keep_content_commands": ["bad"]}, {"drop_environments": ["bad"]},
                        {"clean_styles": True}):
            with self.subTest(options=options), \
                    patch("src.prepare.pipeline.PreparationSession", side_effect=AssertionError("Unexpected reading")), \
                    self.assertRaisesRegex(ValueError, "External execution probes|Custom cleanup"):
                self.prepare(**options)
            events = list(read_events(self.out / "preparation.jsonl"))
            attempt = events[-1]["run_id"]
            self.assertEqual([e["code"] for e in events if e["run_id"] == attempt],
                             ["attempt.started", "attempt.failed"])
            self.assertTrue(events[-1]["data"]["previous_payload_preserved"])
            self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.root.glob(".pytexml-publish-*")))

    def test_optional_files_do_not_control_manifest_finalization(self):
        text, manifest, output, ledger = self.prepare(emit_manifest_json=False, emit_provenance=False,
            convert_images_to_svg=False, copy_local_dependencies=False)
        self.assertIsNone(ledger)
        self.assertFalse((output / "manifest.json").exists())
        self.assertFalse((output / "master.provenance.json").exists())
        self.assertEqual((output / "master.tex").read_text(), text)
        self.assertEqual(manifest.entrypoint, "master.tex")
        self.assertTrue(manifest.prepared_artifacts)

    def test_local_dependency_check_remains_after_discovery_and_preserves_old_payload(self):
        self.prepare()
        before = self.snapshot()
        self.put(r"\usepackage{local}NEW")
        (self.source / "local.sty").write_text(r"\ProvidesPackage{local}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Local code dependencies must be emitted"):
            self.prepare(copy_local_dependencies=False)
        self.assertEqual(self.snapshot(), before)
        failure = list(read_events(self.out / "preparation.jsonl"))[-1]
        self.assertTrue(failure["data"]["previous_payload_preserved"])


if __name__ == "__main__":
    unittest.main()
