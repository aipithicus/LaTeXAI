"""Structured candidates remain available after an execution-reading barrier."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.observer import observe_source
from src.reading.contracts import SourceCommand, StoredDefinition, LiteralRegion
from src.reading.tex_reader import TexReader
from src.prepare.pipeline import preprocess_paper


class SourceObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def observe(self, text):
        resolver = BindingResolver(self.catalog)
        self.context = resolver.new_context()
        reader = TexReader(text, catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        return list(observe_source(reader, self.context, resolver))

    def test_headers_beyond_options_keep_branches_as_data(self):
        text = r"\DeclareOption{x}{\input{stored}}\ProcessOptions\InputIfFileExists{local.cfg}{\input{yes}}{\input{no}}"
        items = self.observe(text)
        commands = [i for i in items if isinstance(i, SourceCommand)]
        self.assertEqual([c.action for c in commands], ["declare_option", "process_options", "optional_source_input"])
        self.assertEqual(commands[-1].value("target"), "local.cfg")
        self.assertEqual(text[commands[-1].span.start:commands[-1].span.end], text[text.index(r"\InputIfFileExists"):])
        self.assertEqual(commands[-1].argument("then").role, "branch")

    def test_definition_literal_and_assignment_operands_are_protected(self):
        items = self.observe(r"\def\saved{\input{hidden}}\verb|\input{fake}|"
            r"\begin{verbatim}\input{fake}\end{verbatim}\let\x\input\input{real}")
        commands = [i for i in items if isinstance(i, SourceCommand)]
        self.assertEqual([c.action for c in commands], ["meaning_assignment", "source_input"])
        self.assertEqual(commands[-1].value("target"), "real")
        self.assertEqual(sum(isinstance(i, LiteralRegion) for i in items), 2)
        self.assertEqual(sum(isinstance(i, StoredDefinition) for i in items), 1)
        self.assertIsNone(self.context.lookup_meaning("x"))
        self.assertIsNone(self.context.lookup_definition("saved"))

    def test_survey_exposes_optional_lookup_without_promoting_it_to_active(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\documentclass{article}BODY", encoding="utf-8")
            (root / "unused.sty").write_text(r"\DeclareOption{x}{}\ProcessOptions"
                r"\InputIfFileExists{local.cfg}{}{}\InputIfFileExists{missing.cfg}{}{}", encoding="utf-8")
            (root / "local.cfg").write_text("LOCAL", encoding="utf-8")
            text, manifest, _, _ = preprocess_paper(str(root), root_tex="main.tex")
            self.assertNotIn("LOCAL", text)
            self.assertEqual(manifest.dependencies, [])
            report = next(r for r in manifest.source_survey if r["source"] == "unused.sty")
            calls = [c for c in report["commands"] if c.get("action") == "optional_source_input"]
            self.assertEqual(len(calls), 2)
            self.assertEqual([c["arguments"]["target"]["literal"] for c in calls], ["local.cfg", "missing.cfg"])
            self.assertTrue(all(c["activity"] == "unresolved" for c in calls))
            self.assertEqual(calls[0]["lookup"]["matches"], ["local.cfg"])
            self.assertEqual(calls[1]["lookup"]["status"], "not_in_inventory")
            self.assertEqual(len(manifest.source_reads), len(set(manifest.source_reads)))

    def test_present_empty_branch_inputs_inline_repeated_occurrences_and_nested_input(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\documentclass{article}\InputIfFileExists{local.cfg}{}{}"
                r"\InputIfFileExists{local.cfg}{}{}", encoding="utf-8")
            (root / "local.cfg").write_text(r"LOCAL\input{child}", encoding="utf-8")
            (root / "child.tex").write_text("CHILD", encoding="utf-8")
            text, manifest, _, _ = preprocess_paper(str(root), root_tex="main.tex")
            self.assertEqual(text.count("LOCAL"), 2)
            self.assertEqual(text.count("CHILD"), 2)
            self.assertNotIn("InputIfFileExists", text)
            self.assertEqual(manifest.source_reads.count("local.cfg"), 1)

    def test_missing_computed_and_nonempty_branches_remain_explicit(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "local.cfg").write_text("LOCAL", encoding="utf-8")
            for target, branch in (("missing.cfg", ""), (r"\computed", ""), ("local.cfg", r"\input{missing}")):
                with self.subTest(target=target, branch=branch):
                    source = r"\InputIfFileExists{" + target + "}{" + branch + "}{}"
                    (root / "main.tex").write_text(r"\documentclass{article}" + source + "TAIL", encoding="utf-8")
                    text, manifest, _, _ = preprocess_paper(str(root), root_tex="main.tex")
                    self.assertIn(source, text)
                    self.assertIn("TAIL", text)
                    self.assertNotIn("LOCAL", text)
                    self.assertEqual(manifest.preparation_status, "partial")


if __name__ == "__main__":
    unittest.main()
