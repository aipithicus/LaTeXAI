"""Expanded integer operands, mutable format constants and safe continuation."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.engine.expansion import ExpansionCursor
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import ReadingBoundary, SourceCommand
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader, TokenKind


class IntegerExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()
        cls.oracle = json.loads((PROJECT / "tests/fixtures/engine/integer-expansion.expected.json").read_text())

    def host(self, source, *, preparation=False):
        knowledge = BindingResolver(self.catalog)
        context = knowledge.new_context()
        reader = TexReader(source, source_id="numbers.tex", catcodes=context.catcodes,
                           endline_char=context.endlinechar)
        return StructuralDispatcher(reader, context, knowledge, preparation=preparation)

    def read(self, source, **kwargs):
        host = self.host(source, **kwargs)
        items = list(host)
        self.assertFalse([i for i in items if isinstance(i, ReadingBoundary)], items)
        return host, items

    def test_active_is_a_format_meaning_with_no_fabricated_source_span(self):
        host, _ = self.read(r"\chardef\saved=\active")
        active = host.context.lookup_meaning("active")
        self.assertEqual(active.value, self.oracle["active"])
        self.assertIsNone(active.span)
        self.assertIn("ltplain.dtx", active.format_origin)
        self.assertEqual(host.context.lookup_meaning("saved").value, self.oracle["copied_active"])

    def test_format_constants_copy_shadow_and_restore_through_normal_meanings(self):
        host, items = self.read(
            r"\let\saved\active{\chardef\active=11 \chardef\inner=\active}\chardef\outer=\saved")
        values = [i.metadata["value"] for i in items
                  if isinstance(i, SourceCommand) and i.action == "character_code_assignment"]
        self.assertEqual(values, [self.oracle["inner_active"], self.oracle["inner_active"],
                                  self.oracle["restored_active"]])
        self.assertIs(host.context.lookup_meaning("active"), host.context.lookup_meaning("saved"))
        self.assertIsNone(host.context.lookup_meaning("inner"))

    def test_macro_shadow_of_format_constant_is_expanded_instead_of_ignored(self):
        host, _ = self.read(r"{\def\active{11}\catcode64=\active}")
        self.assertEqual(host.context.catcodes["@"], CatCode.OTHER)
        self.assertEqual(host.context.lookup_meaning("active").value, 13)

    def test_unknown_effects_do_not_restore_format_values_by_spelling(self):
        host = self.host(r"\unknown\chardef\saved=\active", preparation=True)
        items = list(host)
        self.assertEqual(items[-1].reason, "uncertain_meaning")
        self.assertIsNotNone(host.context.lookup_meaning("active").uncertain)
        self.assertIsNone(host.context.lookup_meaning("saved"))

    def test_macro_produced_signs_radix_and_arguments(self):
        host, _ = self.read(
            r"\def\identity#1{#1}\def\sign{--+}\chardef\saved=\sign\identity{'17} ")
        self.assertEqual(host.context.lookup_meaning("saved").value, self.oracle["expanded_octal"])

    def test_one_replacement_can_supply_both_assignment_operands_and_equals(self):
        host, _ = self.read(r"\def\args{64=11}\catcode\args\relax")
        self.assertEqual(int(host.context.catcodes["@"]), self.oracle["supplied_operands"])

    def test_expanded_internal_value_does_not_execute_its_assignment_role(self):
        host, _ = self.read(r"\def\index{64}\def\value{\catcode\index}\chardef\saved=\value ")
        self.assertEqual(host.context.lookup_meaning("saved").value, self.oracle["internal_value"])
        self.assertEqual(host.context.catcodes["@"], CatCode.OTHER)

    def test_raw_backtick_operand_is_not_expanded_inside_replacement(self):
        host, _ = self.read(r"\def\x{BAD}\def\value{`\x}\chardef\saved=\value\relax")
        self.assertEqual(host.context.lookup_meaning("saved").value, self.oracle["raw_backtick"])

    def test_source_lookahead_keeps_old_category_but_later_source_is_lazy(self):
        host, items = self.read(r"\def\value{11}\catcode64=\value @ @")
        ats = [i.token for i in items if getattr(i, "token", None) and i.token.value == "@"]
        self.assertEqual([t.catcode.name for t in ats], self.oracle["lookahead"])
        self.assertEqual(host.context.catcodes["@"], CatCode.LETTER)

    def test_replacement_space_ends_number_before_reading_following_source(self):
        _, items = self.read(r"\def\value{11 }\catcode64=\value @")
        ats = [i.token for i in items if getattr(i, "token", None) and i.token.value == "@"]
        self.assertEqual([t.catcode for t in ats], [CatCode.LETTER])

    def test_noexpand_can_end_a_literal_number_without_resolving_its_token(self):
        host = self.host(r"\def\value{99}\chardef\saved=12\noexpand\value")
        host.next_item()
        command = host.next_item()
        self.assertIsInstance(command, SourceCommand)
        self.assertEqual(host.context.lookup_meaning("saved").value, self.oracle["noexpand_terminator"])
        self.assertEqual(host.reader.next_token().value, "value")

    def test_optional_equals_reexpands_a_returned_suppressed_macro(self):
        host, _ = self.read(r"\def\numeric{99}\chardef\value\noexpand\numeric")
        self.assertEqual(host.context.lookup_meaning("value").value, self.oracle["optional_equals_reexpands"])

    def test_optional_equals_accepts_an_expanded_equals_sign(self):
        host, _ = self.read(r"\def\equals{=}\chardef\value\equals13")
        self.assertEqual(host.context.lookup_meaning("value").value, self.oracle["expanded_equals"])

    def test_provisional_relax_stops_expansion_of_the_chardef_target(self):
        host = self.host(r"\def\value{99}\chardef\value=12\value")
        host.next_item()
        host.next_item()
        self.assertEqual(host.context.lookup_meaning("value").value, self.oracle["provisional_relax"])
        self.assertEqual(host.reader.next_token().value, "value")

    def test_gauntlet_t15_fragment_captures_active_tokens_and_restores_category(self):
        style = (PROJECT / "tests/fixtures/specimens/gauntlet-master/gmstyle.sty").read_text()
        fragment = style[style.index("% [T15]"):style.index("% [T16]")]
        host, _ = self.read(r"\makeatletter" + fragment)
        active_definition = host.context.lookup_meaning("gm@activedq")
        quotes = [t for t in active_definition.replacement_tokens if t.value == '"' and t.kind != TokenKind.CONTROL_SEQUENCE]
        self.assertEqual([t.kind for t in quotes], [TokenKind.ACTIVE_CHARACTER])
        self.assertEqual(host.context.catcodes['"'], CatCode.OTHER)
        self.assertIsNotNone(host.context.lookup_meaning("gmdqon"))
        self.assertIsNotNone(host.context.lookup_meaning("gmdqoff"))

    def test_noexpand_does_not_make_a_macro_an_internal_integer(self):
        # The sign places noexpand in integer scanning, after optional equals.
        host = self.host(r"\def\value{13}\chardef\saved=+\noexpand\value")
        items = list(host)
        self.assertEqual(items[-1].reason, "computed_assignment")
        self.assertIsNone(host.context.lookup_meaning("saved"))

    def test_leftover_replacement_tokens_are_a_boundary_before_publication(self):
        for replacement in (r"11\relax", r"11 X", r"\active X"):
            with self.subTest(replacement=replacement):
                host = self.host(r"\def\value{" + replacement + r"}\catcode64=\value")
                items = list(host)
                self.assertEqual(items[-1].reason, "integer_continuation")
                self.assertEqual(host.context.catcodes["@"], CatCode.OTHER)

    def test_recursive_or_unknown_numeric_expansion_preserves_previous_value(self):
        for definition, reason in ((r"\def\value{\value}", "expansion_budget"),
                                   (r"\def\value{\unknown}", "expansion_required")):
            with self.subTest(definition=definition):
                host = self.host(r"\chardef\saved=9 " + definition + r"\chardef\saved=\value")
                items = list(host)
                self.assertEqual(items[-1].reason, reason)
                self.assertEqual(host.context.lookup_meaning("saved").value, 9)

    def test_expansion_cursor_checkpoint_restores_source_after_raw_pushback(self):
        host = self.host("12")
        cursor = ExpansionCursor(host.reader, host.context, host.knowledge, host.operations)
        first = cursor.next_token()
        saved = cursor.checkpoint()
        cursor.unread_token(first)
        self.assertEqual(cursor.source_tokens, [])
        cursor.restore(saved)
        self.assertEqual(cursor.source_tokens, [first])
        self.assertEqual(cursor.next_expanded().value, "2")

    def test_preparation_preserves_macro_spelling_and_required_word_separator(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        source = r"\documentclass{article}\def\value{11 }\catcode64=\value" + "\nTEXT"
        (root / "main.tex").write_text(source, encoding="utf-8", newline="\n")
        text, manifest, _, _ = preprocess_paper(str(root))
        self.assertIn(r"\catcode64=\value TEXT", text)
        self.assertEqual(manifest.unresolved, [])

    def test_unproven_numeric_separator_retains_child_source(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "main.tex").write_text(r"\documentclass{article}\input{child}", encoding="utf-8")
        child = r"\def\value{12 }\catcode32=\value" + "\nTEXT"
        (root / "child.tex").write_text(child, encoding="utf-8", newline="\n")
        text, manifest, output, _ = preprocess_paper(str(root))
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertEqual(manifest.unresolved[0]["reason"], "assignment_separator")
        self.assertIn(r"\input{child.tex}", text)
        self.assertEqual((output / "child.tex").read_text(), child)


if __name__ == "__main__":
    unittest.main()
