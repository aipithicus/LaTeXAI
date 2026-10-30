"""The doc-trace expansion core: native language behavior through shared state."""
from pathlib import Path
import sys
import unittest
import json
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.contracts import ReadingBoundary
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader
from src.engine.read_streams import ReadSource


class ExpansionCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def run_source(self, source, *, complete=True, profile="pdftex", context=None):
        resolver = BindingResolver(self.catalog, engine_profile=profile)
        context = context or resolver.new_context(primitive_initial_state=True)
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        host = StructuralDispatcher(reader, context, resolver, preparation=True, source_commands=True)
        items = list(host)
        if complete:
            self.assertFalse([i for i in items if isinstance(i, ReadingBoundary)], items[-1:])
        return host, items

    def body(self, host, name="result"):
        return "".join(t.value for t in host.context.lookup_meaning(name).replacement_tokens)

    def stream_context(self, text, name="data.txt"):
        context = BindingResolver(self.catalog, engine_profile="pdftex").new_context(primitive_initial_state=True)
        context.read_streams.configure({name: ReadSource.from_text(name, text)})
        return context

    def test_roman_positive_zero_negative_alias_and_expanded_operand(self):
        for number, expected in ((1, "i"), (4, "iv"), (9, "ix"), (49, "xlix"),
                                 (1994, "mcmxciv"), (4000, "mmmm"), (0, ""), (-9, "")):
            with self.subTest(number=number):
                host, _ = self.run_source(r"\let\roman\romannumeral\def\n{" + str(number) +
                                          r"}\edef\result{\roman\n X}")
                self.assertEqual(self.body(host), expected + "X")
                self.assertTrue(all(t.catcode == CatCode.OTHER for t in
                                   host.context.lookup_definition("result").replacement_tokens[:-1]))

    def test_roman_zero_still_expands_operand_and_preserves_next_token(self):
        host, _ = self.run_source(r"\def\zero{0}\edef\result{\romannumeral\zero\iftrue X\else Y\fi}")
        self.assertEqual(self.body(host), "X")

    def test_roman_budget_rolls_back_definition(self):
        host, items = self.run_source(r"\edef\result{\romannumeral2147483647}", complete=False)
        self.assertEqual(items[-1].reason, "expansion_budget")
        self.assertIsNone(host.context.lookup_definition("result"))

    def test_case_expansion_all_branches_negative_and_nested(self):
        for index, expected in ((0, "A"), (1, "B"), (2, "C"), (-1, "D"), (3, "D")):
            with self.subTest(index=index):
                host, _ = self.run_source(r"\let\choose\ifcase\edef\result{\choose " + str(index) +
                    r" A\or\iftrue B\else BAD\fi\or C\else D\fi}")
                self.assertEqual(self.body(host), expected)
                self.assertEqual(host._conditionals, [])

    def test_case_execution_skips_unexpanded_code_and_keeps_scope(self):
        host, _ = self.run_source(r"\ifcase2 \unknown\or\def\result{BAD}\or"
                                  r"\def\result{YES}\or\unknown\else\unknown\fi")
        self.assertEqual(self.body(host), "YES")
        host, _ = self.run_source(r"\ifcase-1 \unknown\or\unknown\fi\def\result{AFTER}")
        self.assertEqual(self.body(host), "AFTER")

    def test_abs_compare_uses_current_primitive_meaning_and_profile(self):
        host, _ = self.run_source(r"\let\test\ifpdfabsnum\edef\result{\test-12>3 A\else B\fi"
                                  r"\test-3=3 C\else D\fi\test2<-3 E\else F\fi}")
        self.assertEqual(self.body(host), "ACE")
        host, _ = self.run_source(r"\edef\result{\ifdefined\ifpdfabsnum YES\else NO\fi}", profile="etex")
        self.assertEqual(self.body(host), "NO")

    def test_advance_aliases_optional_by_scope_and_dimension_conversion(self):
        host, _ = self.run_source(r"\countdef\n=23 \n=5 {\advance\n by 2 \xdef\inside{\the\n}}"
                                  r"\advance\n -3 \dimen0=1.5pt \advance\dimen0 by -1sp "
                                  r"\edef\result{\inside,\the\n,\the\dimen0,\number\dimen0}")
        self.assertEqual(self.body(host), "7,2,1.49998pt,98303")

    def test_advance_overflow_is_atomic(self):
        host, items = self.run_source(r"\count0=2147483647 \advance\count0 by 1 ", complete=False)
        self.assertEqual(items[-1].reason, "arithmetic_overflow")
        self.assertEqual(host.context.integer_parameters.read("count:0"), 2147483647)

    def test_fontdimen_alias_internal_dimension_and_global_array(self):
        host, _ = self.run_source(r"\let\f\nullfont {\fontdimen8\f=13sp}"
                                  r"\dimen0=\fontdimen8\f\advance\dimen0 by 2sp "
                                  r"\edef\result{\number\fontdimen8\f,\the\dimen0}")
        self.assertEqual(self.body(host), "13,0.00023pt")

    def test_fontdimen_unestablished_and_invalid_index_stay_boundaries(self):
        host, items = self.run_source(r"\fontdimen0\nullfont=1pt ", complete=False)
        self.assertEqual(items[-1].reason, "font_parameter_index")
        self.assertEqual(host.context.fonts.parameters("nullfont"), (0,) * 7)

    def test_token_register_copy_scope_and_unexpanded_insertion(self):
        host, _ = self.run_source(r"\def\x{OLD}\toksdef\t=7 \t={\x#1}\toks8=\t "
                                  r"{\t={LOCAL}\global\toks9=\t}\def\x{NEW}"
                                  r"\edef\result{\the\toks8}\edef\local{\the\toks9}")
        self.assertEqual(self.body(host), "x##1")
        self.assertEqual(self.body(host, "local"), "LOCAL")
        self.assertEqual(len(host.context.token_registers.read("toks:7")), 3)

    def test_read_balanced_lines_literal_parameters_and_file_origins(self):
        context = self.stream_context("{A\nB} #1\\unknown\n")
        host, _ = self.run_source(r"\openin0=data.txt \read0 to\result", context=context)
        self.assertEqual(self.body(host), "{A B} #1unknown")
        tokens = context.lookup_meaning("result").replacement_tokens
        self.assertTrue(all(t.span.basis is context.read_streams.sources["data.txt"].basis for t in tokens))
        self.assertFalse(context.read_streams.eof(0))

    def test_read_eof_extra_line_close_missing_file_and_alias(self):
        context = self.stream_context("A\n")
        host, _ = self.run_source(r"\let\get\read\let\done\ifeof\openin1=data.txt "
            r"\get1 to\first\edef\before{\done1 Y\else N\fi}"
            r"\get1 to\last\edef\after{\done1 Y\else N\fi}"
            r"\openin2=absent.txt \edef\missing{\done2 Y\else N\fi}"
            r"\closein1", context=context)
        self.assertEqual(self.body(host, "first"), "A ")
        self.assertEqual(self.body(host, "last"), "par")
        self.assertEqual(self.body(host, "before"), "N")
        self.assertEqual(self.body(host, "after"), "Y")
        self.assertEqual(self.body(host, "missing"), "Y")

    def test_read_current_catcodes_endline_and_global_definition(self):
        context = self.stream_context("#x\n#y\n")
        host, _ = self.run_source(r"\openin0=data.txt {\catcode35=12 \endlinechar=-1 "
                                  r"\global\read0 to\first}\read0 to\result", context=context)
        self.assertEqual(self.body(host, "first"), "#x")
        self.assertEqual(context.lookup_meaning("first").replacement_tokens[0].catcode, CatCode.OTHER)
        self.assertEqual(context.lookup_meaning("result").replacement_tokens[0].catcode, CatCode.PARAMETER)

    def test_read_failure_restores_stream_and_previous_meaning(self):
        context = self.stream_context("{never closes\n")
        host, items = self.run_source(r"\def\result{OLD}\openin0=data.txt \read0 to\result",
                                     context=context, complete=False)
        self.assertEqual(items[-1].reason, "unbalanced_read")
        self.assertEqual(self.body(host), "OLD")
        self.assertEqual(context.read_streams.streams[0].position, 0)

    def test_read_unmatched_closing_brace_discards_rest_of_line(self):
        context = self.stream_context("A}discard\nB\n")
        host, _ = self.run_source(r"\openin0=data.txt \read0 to\first\read0 to\result", context=context)
        self.assertEqual(self.body(host, "first"), "A")
        self.assertEqual(self.body(host), "B ")

    def test_openin_requires_explicit_inventory_and_closed_read_never_prompts(self):
        _, items = self.run_source(r"\openin0=data.txt ", complete=False)
        self.assertEqual(items[-1].reason, "input_inventory")
        _, items = self.run_source(r"\read0 to\result", complete=False)
        self.assertEqual(items[-1].reason, "terminal_input")

    def test_shared_core_program_matches_pinned_pdftex(self):
        fixture = PROJECT / "tests/fixtures/engine"
        expected = json.loads((fixture / "expansion-core.expected.json").read_text())["observations"]
        context = self.stream_context((fixture / "expansion-core-data.txt").read_text(), "expansion-core-data.txt")
        host, _ = self.run_source((fixture / "expansion-core-source.tex").read_text(), context=context)
        self.assertEqual({name: self.body(host, name) for name in expected}, expected)

    def test_setup_program_failure_rolls_back_stream_position_and_global_font_array(self):
        from src.engine.programs import evaluate, SETUP
        from src.reading.contracts import ReadingIssue
        context = self.stream_context("A\n")
        host, _ = self.run_source(r"\openin0=data.txt ", context=context)
        reader = TexReader(r"\read0 to\readvalue\fontdimen8\nullfont=12sp\unknown",
                           catcodes=context.catcodes, endline_char=context.endlinechar)
        with self.assertRaises(ReadingIssue):
            evaluate(host, tuple(reader), reader.basis.whole, policy=SETUP)
        self.assertEqual(context.read_streams.streams[0].position, 0)
        self.assertEqual(context.fonts.parameters("nullfont"), (0,) * 7)
        self.assertIsNone(context.lookup_meaning("readvalue"))

    def test_case_coverage_and_activity_identify_the_selected_ordinal(self):
        from src.reading.coverage import ReadingCoverage
        host, items = self.run_source(r"\ifcase2 A\or B\or\def\result{C}\or D\else E\fi")
        coverage = ReadingCoverage(host.reader.basis, items)
        self.assertFalse(coverage.unknown)
        self.assertEqual([r.branch for r in coverage.skipped_regions], ["case:0", "case:1", "remaining_cases"])
        definition = host.context.lookup_definition("result")
        self.assertEqual(host.units.records[definition.unit_id].activity_evidence["branch"], "case:2")

    def test_all_doc_trace_primitives_have_executable_catalog_roles(self):
        from src.engine.catalog import CORE_OPERATIONS
        resolver = BindingResolver(self.catalog, engine_profile="pdftex")
        context = resolver.new_context(primitive_initial_state=True)
        names = "expandafter csname ifx fi if romannumeral ifnum detokenize number edef the else expanded noexpand iffalse string ifdefined fontdimen ifeof let def ifpdfabsnum read ifodd long ifcsname global ifcase or gdef advance".split()
        self.assertEqual(len(names), 31)
        for name in names:
            with self.subTest(name=name):
                meaning = context.resolve_meaning(resolver, name)
                operation = CORE_OPERATIONS[meaning.operation]
                self.assertNotIn("unsupported", operation.identity)
                self.assertFalse(operation.expansion_unavailable)
                self.assertTrue(operation.handler is not None or operation.expansion is not None)

    def test_font_extension_requires_latest_identity(self):
        from src.engine.primitive import PrimitiveMeaning
        context = BindingResolver(self.catalog, engine_profile="pdftex").new_context(primitive_initial_state=True)
        context.fonts.establish("metric-A", (0,) * 7)
        context.fonts.establish("metric-B", (0,) * 7)
        context.record_meaning("oldfont", PrimitiveMeaning("font.identifier", "metric-A"))
        host, items = self.run_source(r"\fontdimen8\oldfont=1sp", context=context, complete=False)
        self.assertEqual(items[-1].reason, "font_parameter_index")
        self.assertEqual(context.fonts.parameters("metric-A"), (0,) * 7)

    def test_unknown_effects_invalidate_unread_empty_token_cells(self):
        from src.reading.contracts import ReadingIssue
        host, _ = self.run_source(r"\toks0={KNOWN}")
        context = host.context
        context.invalidate_observed_meanings(host.reader.basis.whole)
        with self.assertRaises(ReadingIssue) as error:
            context.token_registers.read("toks:199")
        self.assertEqual(error.exception.reason, "uncertain_tokens")

    def test_preparation_preserves_case_ordinals_and_token_copy_separator(self):
        from src.prepare.pipeline import preprocess_paper
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            root = Path(folder)
            (root / "main.tex").write_text(r"\documentclass{article}\ifcase1 BAD\or GOOD\else BAD\fi"
                r"\toks0={X}\toksdef\t=0 \toks1=\t" + "\nTEXT", encoding="utf-8")
            text, manifest, _, _ = preprocess_paper(str(root))
            self.assertFalse(manifest.unresolved)
            self.assertNotIn("BAD", text)
            self.assertIn(r"\or GOOD", text)
            self.assertIn(r"\toks1=\t TEXT", text)

    def test_invalid_file_character_keeps_caller_and_file_provenance_separate(self):
        from src.reading.coverage import ReadingCoverage
        context = self.stream_context("A\x7f\n")
        host, items = self.run_source(r"\openin0=data.txt \read0 to\result", context=context, complete=False)
        self.assertEqual(items[-1].reason, "invalid_read_character")
        self.assertIs(items[-1].span.basis, host.reader.basis)
        self.assertEqual(context.read_streams.streams[0].position, 0)
        self.assertIsNone(context.lookup_meaning("result"))
        self.assertTrue(ReadingCoverage(host.reader.basis, items).diagnostics)


if __name__ == "__main__":
    unittest.main()
