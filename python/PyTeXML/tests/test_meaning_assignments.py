"""Non-expanding let capture, copied meanings, scope, and operand protection."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import BoundMeaning, ReadingBoundary, SourceCommand, StoredDefinition, ConditionalRegion, DeferredRegion
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader, ReadEvent, TokenKind, CatCode


class MeaningAssignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, text, *, complete=True):
        resolver = BindingResolver(self.catalog)
        self.context = resolver.new_context()
        reader = TexReader(text, source_id="test.tex", occurrence_id=1,
                           catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(reader, self.context, resolver, preparation=True, source_commands=True)
        items = list(self.dispatcher)
        spans = [i.remainder if isinstance(i, ReadingBoundary) else i.span for i in items]
        self.assertEqual("".join(text[s.start:s.end] for s in spans), text)
        self.assertEqual(any(isinstance(i, ReadingBoundary) for i in items), not complete, items[-1:])
        return items

    @staticmethod
    def chars(items):
        return "".join(i.token.value for i in items if isinstance(i, ReadEvent) and i.token
                       and i.token.kind == TokenKind.CHARACTER and i.token.catcode == CatCode.LETTER)

    def test_copy_donor_now_and_restore_nested_scopes(self):
        items = self.read(r"\let\test\iftrue{\let\test=\iffalse\test X\else A\fi}"
                          r"\let\saved\test\let\test\iffalse\saved B\fi\test X\else C\fi")
        self.assertEqual(self.chars(items), "ABC")

    def test_alias_conditional_nests_while_skipping(self):
        items = self.read(r"\let\test\iftrue\let\done\fi\iffalse\test X\done\else Y\fi")
        self.assertEqual(self.chars(items), "Y")

    def test_setter_alias_keeps_its_target_and_stored_macro_is_not_expanded(self):
        items = self.read(r"\newif\ifx\let\set\xtrue\set\ifx Y\fi\def\donor{\input{hidden}}\let\saved\donor")
        self.assertEqual(self.chars(items), "Y")
        self.assertIs(self.context.lookup_meaning("saved"), self.context.lookup_meaning("donor"))
        self.assertIsInstance(self.context.lookup_meaning("saved"), StoredDefinition)

    def test_reading_handler_alias_and_frozen_profile(self):
        items = self.read(r"\let\letter\makeatletter\def\makeatletter{}\letter\def\a@b{}")
        self.assertIsNotNone(self.context.lookup_definition("a@b"))
        self.assertIsInstance(self.context.lookup_meaning("letter"), BoundMeaning)
        self.read(r"\let\v\verb\v|\input{hidden}|")

    def test_unknown_donor_does_not_execute_or_taint_unrelated_boolean(self):
        items = self.read("\\newif\\ifflag\\let % c\n\\input = % donor\n\\unknown\\ifflag X\\else Y\\fi")
        self.assertEqual(self.chars(items), "Y")
        assignment = next(i for i in items if isinstance(i, SourceCommand) and i.action == "meaning_assignment")
        self.assertFalse(assignment.metadata["donor_resolved"])
        self.assertFalse(self.context.lookup_meaning("ifflag").uncertain)
        items = self.read(r"\let\input\unknown\input{file}", complete=False)
        self.assertEqual(items[-1].reason, "uncertain_meaning")

    def test_literal_and_stored_and_skipped_assignments_are_not_installed(self):
        self.read(r"\def\saved{\let\a\input}\verb|\let\b\input|\iffalse\let\c\input\fi")
        for name in "abc":
            self.assertIsNone(self.context.lookup_meaning(name))

    def test_aliased_boolean_after_unknown_code_retains_both_branches(self):
        items = self.read(r"\let\test\iftrue\unknown\test A\else B\fi")
        self.assertTrue(any(isinstance(i, ConditionalRegion) for i in items))

    def test_unexecuted_assignment_shadows_old_dependency_grammar_in_environment(self):
        items = self.read(r"\begin{unknown}\let\input\saved\input{decoy}\end{unknown}")
        region = next(i for i in items if isinstance(i, DeferredRegion))
        self.assertFalse(any(o.command and o.command.action == "source_input"
                             for o in region.observations))
        self.assertEqual(region.observations[0].reason, "stored_macro")
        self.assertIsNone(self.context.lookup_meaning("input"))

    def test_character_donor_and_malformed_or_prefixed_assignments_are_explicit(self):
        self.read(r"\let\letter=A")
        self.assertEqual(self.context.lookup_meaning("letter").token.value, "A")
        self.assertEqual(self.read(r"\let\letter=A\letter", complete=False)[-1].reason, "character_meaning")
        for text in (r"\let", r"\let x=y", r"\let\x="):
            with self.subTest(text=text):
                self.read(text, complete=False)
                self.assertIsNone(self.context.lookup_meaning("x"))

    def test_global_assignment_cancels_scope_restoration(self):
        for text in (r"{\global\let\x\relax}", r"{\globaldefs=1\let\x\relax}"):
            with self.subTest(text=text):
                self.read(text)
                self.assertEqual(self.context.lookup_meaning("x").operation, "execution.relax")

    def test_prepare_copies_unexpanded_assignment_and_preserves_separator(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\documentclass{article}\let\saved\unknown" + "\n"
                + r"\begin{document}text\end{document}", encoding="utf-8")
            preprocess_paper(str(root))
            text = (root / "extracted/master.tex").read_text(encoding="utf-8")
            self.assertIn(r"\let\saved\unknown", text)
            self.assertNotIn(r"\unknowntext", text)


if __name__ == "__main__":
    unittest.main()
