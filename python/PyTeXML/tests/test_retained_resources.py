"""Retained TeX closes over captured resource references without activating them."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper


class RetainedResourceTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def prepare(self, body, *, root="paper.tex"):
        self.put(root, r"\documentclass{article}\AddToHook{file/body.tex/before}[unsupported]{X}"
                       r"\input{body}")
        self.put("body.tex", body)
        return preprocess_paper(str(self.root), root_tex=root)

    @staticmethod
    def resources(manifest):
        return [resource for report in manifest.source_survey for command in report["commands"]
                for resource in command.get("retained_resources", ())]

    def test_classic_resources_and_root_job_bbl_survive_retention_and_reread(self):
        self.put("refs.bib", "@book{one,title={One}}\r\n")
        self.put("extra.bib", "@book{two,title={Two}}\n")
        self.put("local.bst", "STYLE\n")
        self.put("paper.bbl", r"\input{bib/entries}")
        self.put("bib/entries.tex", "ENTRIES")
        self.put("body.bbl", "WRONG JOB")
        body = r"\bibliographystyle{local}\bibliography{refs,extra}"
        _, manifest, output, _ = self.prepare(body)
        for name in ("refs.bib", "extra.bib", "local.bst", "bib/entries.tex"):
            self.assertEqual((output / name).read_bytes(), (self.root / name).read_bytes())
        self.assertEqual((output / "master.bbl").read_bytes(), (self.root / "paper.bbl").read_bytes())
        self.assertFalse((output / "body.bbl").exists())
        self.assertFalse((output / "bibliography.bbl").exists())
        self.assertFalse((output / "bibliography.bib").exists())
        self.assertFalse(manifest.bibliography.canonical_bib)
        self.assertEqual(manifest.source_dependency_closure, "unresolved")
        self.assertTrue(all(r["activity"] == "unresolved" for r in self.resources(manifest)))
        self.assertFalse(any(d["kind"] in {"bibliography", "formatted_bibliography"} for d in manifest.dependencies))
        artifacts = {a["path"] for a in manifest.prepared_artifacts}
        self.assertTrue({"refs.bib", "extra.bib", "master.bbl", "local.bst"} <= artifacts)
        _, reread, again, _ = preprocess_paper(str(output), root_tex="master.tex",
                                              output_dir=str(self.root / "again"))
        self.assertEqual((again / "master.bbl").read_bytes(), (output / "master.bbl").read_bytes())
        self.assertEqual((again / "refs.bib").read_bytes(), (output / "refs.bib").read_bytes())
        self.assertEqual(reread.source_dependency_closure, "unresolved")

    def test_biblatex_resources_are_copied_without_claiming_formatting(self):
        self.put("data/refs.bib", "@book{x,title={X}}")
        self.put("paper.bbl", "BIBLATEX BBL")
        _, manifest, output, _ = self.prepare(r"\addbibresource[location=local]{data/refs.bib}\printbibliography")
        self.assertTrue((output / "data/refs.bib").is_file())
        self.assertEqual((output / "master.bbl").read_text(), "BIBLATEX BBL")
        self.assertFalse(manifest.bibliography.prepared_bbl)
        self.assertTrue(all(r["status"] == "prepared" for r in self.resources(manifest)))

    def test_missing_computed_and_excluded_resources_are_not_guessed(self):
        self.put("decoy.bib", "DECOY")
        _, manifest, output, _ = self.prepare(
            r"\def\stored{\bibliography{decoy}}"
            r"\iffalse\bibliography{decoy}\fi"
            r"\bibliography{missing}\bibliography{\computed}")
        self.assertFalse((output / "decoy.bib").exists())
        resources = self.resources(manifest)
        self.assertTrue(all(r["status"] == "unresolved" for r in resources))
        self.assertTrue(any(r["reason"] == "computed_resource" for r in resources))
        self.assertTrue(any(r["requested"] == "missing" for r in resources))

    def test_optional_retained_source_and_resource_cycles_terminate(self):
        self.put("config.cfg", r"\input{body}\bibliography{refs}")
        self.put("refs.bib", "@book{x,title={X}}")
        _, manifest, output, _ = self.prepare(r"\InputIfFileExists{config.cfg}{}{}")
        self.assertTrue((output / "config.cfg").is_file())
        self.assertTrue((output / "refs.bib").is_file())
        self.assertEqual(len([a for a in manifest.prepared_artifacts if a["path"] == "refs.bib"]), 1)

    def test_same_source_can_have_explicit_and_jobname_addresses(self):
        self.put("paper.bbl", "ENTRIES")
        self.put("refs.bib", "@book{x,title={X}}")
        _, manifest, output, _ = self.prepare(r"\input{paper.bbl}\bibliography{refs}")
        artifacts = {a["path"] for a in manifest.prepared_artifacts}
        self.assertTrue({"paper.bbl", "master.bbl"} <= artifacts)
        self.assertEqual((output / "paper.bbl").read_bytes(), (output / "master.bbl").read_bytes())

    def test_jobname_collision_fails_without_overwriting_previous_payload(self):
        self.put("paper.bbl", "JOB BBL")
        self.put("master.bbl", "EXPLICIT INPUT BBL")
        self.put("refs.bib", "@book{x,title={X}}")
        self.put("extracted/master.tex", "PREVIOUS PAYLOAD")
        with self.assertRaisesRegex(ValueError, "Retained resource conflicts"):
            self.prepare(r"\input{master.bbl}\bibliography{refs}")
        self.assertEqual((self.root / "extracted/master.tex").read_text(), "PREVIOUS PAYLOAD")


if __name__ == "__main__":
    unittest.main()
