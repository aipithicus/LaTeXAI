"""Preparation consumes accepted expansion facts and preserves authored source."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper


class ExpandedRequestTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def prepare(self, body):
        self.put("main.tex", r"\documentclass{article}" + body + r"\begin{document}BODY\end{document}")
        return preprocess_paper(str(self.root))

    def test_p10_computed_package_is_loaded_and_source_is_preserved(self):
        body = r"\def\part{natbib}\edef\load{\noexpand\RequirePackage{\part}}\load"
        text, manifest, _, ledger = self.prepare(body)
        self.assertIn(body, text)
        self.assertNotIn(r"\RequirePackage{natbib}", text)
        self.assertTrue(any(p.name == "natbib" and p.binding_activated for p in manifest.packages_declared))
        self.assertEqual(manifest.unresolved, [])
        self.assertEqual(ledger.master_length, len(text))

    def test_arguments_can_come_from_the_invocation_and_aliases_keep_identity(self):
        text, manifest, _, _ = self.prepare(
            r"\let\request\RequirePackage\def\load#1{\request{#1}}\load{natbib}\citep{k}")
        self.assertIn(r"\load{natbib}", text)
        self.assertTrue(any(p.name == "natbib" and p.binding_activated for p in manifest.packages_declared))
        self.assertFalse([r for r in manifest.requirements if r["reason"] == "package_not_loaded"])

    def test_local_style_request_does_not_rewrite_its_macro_invocation(self):
        style = r"\def\part{natbib}\edef\load{\noexpand\RequirePackage{\part}}\load"
        self.put("local.sty", style)
        _, manifest, output, _ = self.prepare(r"\usepackage{local}")
        self.assertEqual((output / "local.sty").read_text(), style)
        self.assertTrue(any(p.name == "natbib" for p in manifest.packages_declared))

    def test_incomplete_probe_does_not_load_package_or_consume_following_source(self):
        text, manifest, _, _ = self.prepare(
            r"\def\load#1{\RequirePackage{#1}\unknown}\load{natbib}TAIL\usepackage{xspace}")
        self.assertIn(r"\load{natbib}TAIL", text)
        self.assertFalse(any(p.name == "natbib" for p in manifest.packages_declared))
        self.assertTrue(any(p.name == "xspace" for p in manifest.packages_declared))

    def test_shadowed_request_is_not_intercepted_by_spelling(self):
        _, manifest, _, _ = self.prepare(r"\def\RequirePackage#1{}\def\load{\RequirePackage{natbib}}\load")
        self.assertFalse(any(p.name == "natbib" for p in manifest.packages_declared))

    def test_computed_relocation_is_deferred_without_editing_the_invocation(self):
        self.put("nested/local.sty", r"\ProvidesPackage{local}")
        self.put("nested/main.tex",
                 r"\documentclass{article}\def\load{\RequirePackage{local}}\load\begin{document}BODY\end{document}")
        text, manifest, _, _ = preprocess_paper(str(self.root), root_tex="nested/main.tex")
        self.assertIn(r"\load", text)
        self.assertFalse(any(p.name == "local" for p in manifest.packages_declared))
        self.assertTrue(any(r["reason"] == "expanded_package_relocation" for r in manifest.unresolved))

    def test_predicate_uses_frozen_expanded_value_after_donor_redefinition(self):
        text, manifest, _, _ = self.prepare(
            r"\def\donor{0}\edef\flag{\donor}\def\donor{1}\if0\flag YES\else NO\fi")
        self.assertIn("YES", text)
        self.assertNotIn("NO", text)
        self.assertEqual(manifest.unresolved, [])


if __name__ == "__main__":
    unittest.main()
