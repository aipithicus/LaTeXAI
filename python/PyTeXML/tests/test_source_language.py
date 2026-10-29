"""Source-driven macro grammar, expansion and physical-file continuation."""
import unittest
from src.bindings.resolver import BindingResolver
from src.reading.contracts import ReadingBoundary
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader
from src.engine.programs import evaluate, SETUP
from src.reading.contracts import LiteralRegion


class SourceLanguageTests(unittest.TestCase):
    def read(self, source, *, complete=True):
        resolver = BindingResolver()
        context = resolver.new_context()
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        self.host = StructuralDispatcher(reader, context, resolver, preparation=True, source_commands=True)
        self.items = list(self.host)
        if complete:
            self.assertFalse([x for x in self.items if isinstance(x, ReadingBoundary)], self.items[-1:])
            ReadingCoverage(reader.basis, self.items)
        return context

    def value(self, name):
        return "".join(t.value for t in self.host.context.lookup_definition(name).replacement_tokens)

    def test_delimiter_matching_ignores_groups_and_preserves_overlaps(self):
        self.read(r"\def\f#1aba#2!{#1/#2}\edef\out{\f {aba}ababa!}")
        self.assertEqual(self.value("out"), "aba/ba")

    def test_literal_prefix_and_hash_brace(self):
        self.read(r"\def\f X#1#{[#1]}\edef\out{\f Xabc{Z}}")
        self.assertEqual(self.value("out"), "[abc]{Z}")

    def test_failed_delimiter_does_not_install_an_expanded_definition(self):
        context = self.read(r"\def\f#1!{#1}\edef\out{\f no delimiter}", complete=False)
        self.assertIsNone(context.lookup_definition("out"))

    def test_string_uses_raw_identity_and_scoped_escape_character(self):
        self.read(r"\def\foo{EXPANDED}\edef\a{\string\foo}"
                  r"{\escapechar=-1 \xdef\b{\string\foo}}\edef\c{\string\foo}")
        self.assertEqual((self.value("a"), self.value("b"), self.value("c")), ("\\foo", "foo", "\\foo"))

    def test_integer_and_definedness_conditionals_in_expanded_definition(self):
        self.read(r"\def\yes{}\edef\out{\ifdefined\yes Y\else N\fi"
                  r"\ifnum12>3 A\else B\fi\ifodd4 C\else D\fi}")
        self.assertEqual(self.value("out"), "YAD")

    def test_failed_expansion_restores_conditional_frames_and_name_assignments(self):
        self.read(r"\edef\out{\iftrue\csname pdfoutput\endcsname\unknown}", complete=False)
        self.assertIsNone(self.host.context.lookup_definition("out"))
        self.assertIsNone(self.host.context.lookup_meaning("pdfoutput"))
        self.assertFalse(self.host._conditionals)
        self.assertFalse(self.host.decisions)

    def test_ifcsname_does_not_create_a_missing_name(self):
        self.read(r"\edef\out{\ifcsname pdfoutput\endcsname Y\else N\fi}")
        self.assertEqual(self.value("out"), "N")
        self.assertIsNone(self.host.context.lookup_meaning("pdfoutput"))

    def test_protected_definition_survives_edef_and_expanded_collection(self):
        self.read(r"\protected\def\p{EXPANDED}\edef\out{\expanded{\p}}")
        self.assertEqual(self.value("out"), "p")
        self.assertEqual(self.host.context.lookup_definition("out").replacement_tokens[0].kind.value,
                         "control_sequence")

    def test_scantokens_failure_rolls_back_definitions_and_generated_provenance(self):
        self.read(r"\scantokens{\def\created{yes}\catcode64=11 }", complete=False)
        self.assertEqual(self.items[-1].reason, "rescan_effect")
        self.assertIsNone(self.host.context.lookup_definition("created"))
        self.assertEqual(int(self.host.context.catcodes['@']), 12)
        self.assertFalse(self.host.program_sources)

    def test_expandafter_closes_conditional_before_endinput(self):
        self.read("\\def\\seen{}\\ifdefined\\seen\\expandafter\\endinput\\fi SAME\nLOST")
        self.assertFalse(self.host._conditionals)
        spans = "".join(self.host.reader.text[x.span.start:x.span.end] for x in self.items
                        if getattr(x, "token", None) is not None)
        self.assertIn("SAME", spans)
        self.assertNotIn("LOST", spans)

    def test_number_uses_integer_expansion(self):
        self.read(r"\def\n{17}\edef\out{\number\n}")
        self.assertEqual(self.value("out"), "17")

    def test_typed_dimension_cells_supply_scaled_integers(self):
        self.read(r"\dimendef\zero=12 \dimen12=--.5pt \edef\a{\number\zero}"
                  r"{\dimen12=-1.9sp \xdef\b{\number\zero}}\edef\c{\number\zero}")
        self.assertEqual((self.value('a'), self.value('b'), self.value('c')), ('32768', '-1', '32768'))

    def test_prefixes_and_negative_globaldefs_restore_local_values(self):
        self.read(r"\def\a{old}{\global\long\def\a#1!{#1}}"
                  r"\def\b{old}{\globaldefs=-1 \gdef\b{local}}")
        self.assertTrue(self.host.context.lookup_definition("a").long)
        self.assertEqual(self.value("b"), "old")

    def test_global_reading_assignments_cancel_nested_scope_restoration(self):
        for prefix in (r"\global", r"\globaldefs=1 "):
            with self.subTest(prefix=prefix):
                self.read(r"{\catcode64=11 {" + prefix + r"\catcode64=13 }}")
                self.assertEqual(int(self.host.context.catcodes['@']), 13)
        self.read(r"{\endlinechar=32 {\global\endlinechar=-1 }}")
        self.assertEqual(self.host.context.endlinechar, -1)
        self.assertEqual(self.host.reader.endline_char, -1)

    def test_unknown_globaldefs_preserves_current_definition_but_not_restored_state(self):
        from src.reading.contracts import UncertainMeaning
        self.read(r"\unknown\relax{\def\a{NEW}\let\b\a\edef\inside{\a}}")
        definitions = [item for item in self.items if getattr(item, 'target', None) is not None]
        self.assertTrue(any(item.target.value == 'inside' and
                            ''.join(t.value for t in item.replacement_tokens) == 'NEW' for item in definitions))
        for name in ('a', 'b', 'inside'):
            self.assertIsInstance(self.host.context.lookup_meaning(name), UncertainMeaning)

    def test_later_global_definition_clears_uncertain_restoration(self):
        self.read(r"\unknown\relax{\def\a{MAYBE}\globaldefs=0 \gdef\a{FINAL}}", complete=False)
        # Re-establishing globaldefs itself still needs register-scope support.
        self.assertEqual(self.items[-1].reason, 'uncertain_integer')
        self.read(r"\unknown\relax{\def\a{MAYBE}}\gdef\a{FINAL}")
        self.assertEqual(self.value('a'), 'FINAL')

    def test_unknown_scope_invalidates_each_enclosing_restoration(self):
        from src.reading.contracts import ConditionalRegion, UncertainMeaning
        self.read(r"\unknown\relax{\def\a{OUTER}{\def\a{INNER}}"
                  r"\ifx\a\relax LEFT\else RIGHT\fi}")
        self.assertTrue(any(isinstance(item, ConditionalRegion) for item in self.items))
        self.assertIsInstance(self.host.context.lookup_meaning('a'), UncertainMeaning)

    def test_setup_execution_rejects_unknown_assignment_scope(self):
        from src.reading.contracts import ReadingIssue
        self.read(r"\unknown\relax")
        self.host.begin_group('brace', self.host.reader.basis.span(0, 0))
        reader = TexReader(r'\def\a{NEW}', catcodes=self.host.context.catcodes,
                           endline_char=self.host.context.endlinechar)
        with self.assertRaises(ReadingIssue) as raised:
            evaluate(self.host, tuple(reader), reader.basis.whole, policy=SETUP)
        self.assertEqual(raised.exception.reason, 'uncertain_integer')
        self.assertIsNone(self.host.context.lookup_definition('a'))

    def test_frozen_program_futurelet_keeps_the_looked_at_token(self):
        self.read("")
        context = self.host.context
        source = r"\def\check{\ifx\saved X\gdef\result{yes}\else\gdef\result{no}\fi}\futurelet\saved\check X"
        reader = TexReader(source, catcodes=context.catcodes, endline_char=-1)
        from src.engine.programs import HOOK_BODY
        evaluate(self.host, tuple(reader), reader.basis.whole, policy=HOOK_BODY)
        self.assertEqual(self.value("result"), "yes")

    def test_lstinline_header_and_first_brace_terminator_are_literal(self):
        resolver = BindingResolver()
        resolver.load_package("listings")
        context = resolver.new_context()
        source = r'\lstinline[language=Python]|%\input{never}|\lstinline{a{b}TAIL'
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        host = StructuralDispatcher(reader, context, resolver, preparation=True, source_commands=True)
        items = list(host)
        self.assertFalse([x for x in items if isinstance(x, ReadingBoundary)], items[-1:])
        regions = [x for x in items if isinstance(x, LiteralRegion)]
        self.assertEqual([source[r.body.start:r.body.end] for r in regions], [r'%\input{never}', 'a{b'])


if __name__ == "__main__":
    unittest.main()
