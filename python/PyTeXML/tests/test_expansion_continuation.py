"""Expansion changes input order; a capture is never a substitute for execution."""
from pathlib import Path
import json
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.engine.expansion import ExpansionCursor
from src.reading.contracts import ConditionalRegion, ReadingBoundary, UndefinedMeaning
from src.reading.dispatcher import StructuralDispatcher
from src.reading.coverage import ReadingCoverage
from src.reading.tex_reader import TexReader


class ExpansionContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, source, *, complete=True):
        resolver = BindingResolver(self.catalog)
        context = resolver.new_context()
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        self.host = StructuralDispatcher(reader, context, resolver, preparation=True)
        self.items = list(self.host)
        if complete:
            self.assertFalse(any(isinstance(i, ReadingBoundary) for i in self.items), self.items[-1:])
            ReadingCoverage(reader.basis, self.items)
        return context

    def body(self, name):
        return "".join(t.value for t in self.host.context.lookup_definition(name).replacement_tokens)

    def test_constructed_definition_target_does_not_redefine_csname(self):
        source = r"\expandafter\def\csname ver@gmfake.sty\endcsname{}"
        context = self.read(source)
        self.assertIsNotNone(context.lookup_definition("ver@gmfake.sty"))
        self.assertIsNone(context.lookup_meaning("csname"))
        self.assertEqual(source[self.items[0].span.start:self.items[0].span.end], source)

    def test_unknown_constructed_meaning_keeps_entire_conditional(self):
        source = r"\expandafter\ifx\csname urlstyle\endcsname\relax A\else B\fi"
        self.read(source)
        region, = (i for i in self.items if isinstance(i, ConditionalRegion))
        self.assertEqual(source[region.span.start:region.span.end], source)
        self.assertEqual(self.host.decisions, [])

    def test_known_constructed_meaning_selects_branch(self):
        self.read(r"\let\known\relax\expandafter\ifx\csname known\endcsname\relax"
                  r"\def\chosen{YES}\else\def\chosen{NO}\fi")
        self.assertEqual(self.body("chosen"), "YES")

    def test_csname_relax_assignment_is_local_and_rolled_back_on_failure(self):
        context = self.read(r"{\expandafter\let\csname undefined\endcsname\relax}")
        self.assertIsInstance(context.resolve_meaning(self.host.knowledge, "undefined"), UndefinedMeaning)
        context = self.read(r"\expandafter\unknown\csname undefined\endcsname", complete=False)
        self.assertIsInstance(self.items[-1], ReadingBoundary)
        self.assertIsInstance(context.resolve_meaning(self.host.knowledge, "undefined"), UndefinedMeaning)
        self.assertEqual(self.items[-1].remainder.start, 0)

    def test_failed_definition_does_not_publish_target_or_redefine_primitive(self):
        context = self.read(r"\expandafter\def\csname target\endcsname{unclosed", complete=False)
        self.assertIsNone(context.lookup_meaning("target"))
        self.assertIsNone(context.lookup_meaning("csname"))
        self.assertEqual(self.items[-1].remainder.start, 0)

    def test_expandafter_expands_second_once_not_to_completion(self):
        self.read(r"\def\a{\b}\def\b{Y}\edef\result{\expandafter\noexpand\a}")
        self.assertEqual(self.body("result"), "b")

    def test_expanded_reinserts_result_into_same_cursor(self):
        self.read(r"\def\a{X}\edef\result{A\expanded{{\a}B}C}")
        self.assertEqual(self.body("result"), "A{X}BC")
        self.read(r"\def\a{X}\edef\result{\expanded{\noexpand\a}}")
        self.assertEqual(self.body("result"), "X")

    def test_expanded_can_feed_one_definition_but_not_drop_pending_text(self):
        self.read(r"\expanded{\def\noexpand\a{X}}")
        self.assertEqual(self.body("a"), "X")
        context = self.read(r"\expanded{\def\noexpand\a{X}UNCONSUMED}", complete=False)
        self.assertIsNone(context.lookup_meaning("a"))
        self.assertEqual(self.items[-1].reason, "expansion_continuation")
        self.assertEqual(self.items[-1].remainder.start, 0)
        self.assertFalse(any(u.kind == "StoredDefinition" for u in self.host.units.records.values()))

    def test_nested_primitive_expansion_has_a_finite_budget(self):
        context = self.read(r"\def\loop{\expandafter\loop\loop}\edef\a{\loop}", complete=False)
        self.assertEqual(self.items[-1].reason, "expansion_budget")
        self.assertIsNone(context.lookup_meaning("a"))

    def test_independent_oracle_fixture_witnesses(self):
        fixture = PROJECT / "tests/fixtures/engine/expansion-continuation"
        source = fixture.with_suffix(".tex").read_text().split("\n", 1)[1].split(r"\typeout", 1)[0]
        self.read(source)
        for name, expected in json.loads(fixture.with_suffix(".expected.json").read_text()).items():
            self.assertEqual(self.body("PyWitness" + name), expected, name)


if __name__ == "__main__":
    unittest.main()
