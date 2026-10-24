"""Declared databases are cumulative resources, not competing bibliographies."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper


class MultiDatabaseBibliographyTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def prepare(self):
        return preprocess_paper(str(self.root), root_tex="paper/main.tex")

    def test_joint_selection_strings_crossrefs_duplicates_and_enrichment(self):
        self.put("paper/main.tex", r"\documentclass{article}\begin{document}"
            r"\cite{later,child,shared}\bibliography{first,second,first}\end{document}")
        first = '@string{journal="Journal"}\n@inproceedings{child,title={Child},crossref={parent}}\n' \
                '@misc{shared,title={Shared},year=2026}\n@misc{uncited,title={Enrichment}}'
        second = '@article{later,title={Later},journal=journal}\n@proceedings{parent,title={Parent}}\n' \
                 '@misc{shared,year=2026,title={Shared}}'
        self.put("paper/first.bib", first)
        self.put("paper/second.bib", second)
        text, manifest, out, _ = self.prepare()
        self.assertEqual(manifest.bibliography.bib_files, ["paper/first.bib", "paper/second.bib"])
        self.assertEqual(manifest.bibliography.citations_count, 4)
        keys = ["later", "child", "parent", "shared"]
        positions = [text.index(r"\bibitem{" + key + "}") for key in keys]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count(r"\bibitem{shared}"), 1)
        self.assertIn("Journal", text)
        self.assertNotIn("Enrichment", text)
        canonical = (out / "bibliography.bib").read_text()
        self.assertEqual(canonical, first + "\n\n" + second + "\n")
        self.assertEqual((out / "bibliography.bbl").read_text().count(r"\bibitem{"), 4)
        self.assertEqual(manifest.source_reads.count("paper/first.bib"), 1)

    def test_cross_database_conflict_retains_all_records_and_rebases_request(self):
        self.put("paper/main.tex", r"\documentclass{article}\cite{a}\bibliography{one,two}")
        self.put("paper/one.bib", "@misc{a,title={One}}")
        self.put("paper/two.bib", "@misc{a,title={Two}}")
        text, manifest, out, _ = self.prepare()
        self.assertIn(r"\bibliography{bibliography}", text)
        self.assertNotIn(r"\bibitem{a}", text)
        self.assertEqual(manifest.bibliography.preparation_backend, "deferred-conflict")
        self.assertIn("{One}", (out / "bibliography.bib").read_text())
        self.assertIn("{Two}", (out / "bibliography.bib").read_text())


if __name__ == "__main__":
    unittest.main()
