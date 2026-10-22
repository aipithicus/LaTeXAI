"""Reusable BibTeX data parsing and selection, independent of preparation."""
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bibtex import Database, BibTeXError


class BibTeXTests(unittest.TestCase):
    def test_native_reader_keeps_dependency_records_and_citation_order(self):
        db = Database()
        db.read("@inproceedings{child,title={Child},crossref={parent}}\n"
                "@proceedings{parent,title={Parent},year=2025}\n"
                "@misc{other,title={Other}}")
        self.assertEqual([x.key for x in db.selected(["other", "child", "other"])],
                         ["other", "child", "parent"])
        self.assertEqual([(name, value.resolve()) for name, value in db.entries["child"][0].fields],
                         [("title", "Child"), ("crossref", "parent")])
        self.assertEqual([x.key for x in db.selected(["*"])], ["child", "parent", "other"])

    def test_native_reader_rejects_ambiguous_or_incomplete_data(self):
        cases = [
            ("@misc{a,title={Unclosed}", "Expected"),
            ("@misc{a,title={Unclosed", "Unterminated"),
            ('@misc{a,title="Unclosed}', "Unbalanced"),
        ]
        for text, message in cases:
            with self.subTest(text=text), self.assertRaisesRegex(BibTeXError, message):
                Database().read(text, "refs.bib")
        db = Database()
        db.read("@misc{a,crossref={b}} @misc{b,crossref={a}}")
        with self.assertRaisesRegex(BibTeXError, "Cyclic"):
            db.selected(["a"])
        with self.assertRaisesRegex(BibTeXError, "missing"):
            db.selected(["missing"])

    def test_duplicate_keys_are_retained_but_conflicting_citations_fail(self):
        db = Database()
        db.read("@misc{a,title={One}} @misc{a,title={Two}} @misc{b,title={Unique}}")
        self.assertEqual(len(db.entries["a"]), 2)
        self.assertEqual([x.key for x in db.selected(["b"])], ["b"])
        with self.assertRaisesRegex(BibTeXError, "Conflicting"):
            db.selected(["a"])
        with self.assertRaisesRegex(BibTeXError, "Conflicting"):
            db.selected(["*"])
        identical = Database()
        identical.read("@misc{a,title={One}} @misc{a,title={One}}")
        self.assertEqual(len(identical.selected(["a"])), 1)


if __name__ == "__main__":
    unittest.main()
