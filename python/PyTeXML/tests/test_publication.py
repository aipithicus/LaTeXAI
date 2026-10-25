"""Preparation errors and publication errors leave the last good payload intact."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper


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


if __name__ == "__main__":
    unittest.main()
