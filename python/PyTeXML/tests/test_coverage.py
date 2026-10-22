"""Three-valued laws and integration with actual source-preserving scan results."""
from dataclasses import replace
from itertools import product
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.contracts import LiteralRegion, ReadingBoundary, StoredDefinition
from src.reading.coverage import Coverage, CoverageState, ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.spans import SourceBasis, SpanSet
from src.reading.tex_reader import EventKind, ReadEvent, ReaderState, TexReader


def cells(selection):
    return {position for span in selection for position in range(span.start, span.end)}


class CoverageTests(unittest.TestCase):
    def query(self, basis, states):
        matches = SpanSet(basis, (basis.span(i, i + 1) for i, state in enumerate(states) if state == "T"))
        unknown = SpanSet(basis, (basis.span(i, i + 1) for i, state in enumerate(states) if state == "U"))
        return Coverage(basis.whole, matches, unknown)

    def assert_states(self, query, states):
        self.assertEqual(cells(query.matches), {i for i, s in enumerate(states) if s == "T"})
        self.assertEqual(cells(query.unknown), {i for i, s in enumerate(states) if s == "U"})
        self.assertEqual(cells(query.nonmatches), {i for i, s in enumerate(states) if s == "F"})

    def test_three_valued_operations_against_truth_tables(self):
        basis = SourceBasis("truth", 0, 3)
        # Independent per-position truth tables, including the uncertain cases.
        disjoin = {"TT": "T", "TF": "T", "TU": "T", "FT": "T", "FF": "F", "FU": "U", "UT": "T", "UF": "U", "UU": "U"}
        conjoin = {"TT": "T", "TF": "F", "TU": "U", "FT": "F", "FF": "F", "FU": "F", "UT": "U", "UF": "F", "UU": "U"}
        negate = {"T": "F", "F": "T", "U": "U"}
        fixtures = [(states, self.query(basis, states)) for states in product("TFU", repeat=3)]
        for a, left in fixtures:
            self.assert_states(left.negate(), [negate[s] for s in a])
            self.assertEqual(left.negate().negate(), left)
            for b, right in fixtures:
                with self.subTest(a=a, b=b):
                    self.assert_states(left.union(right), [disjoin[x + y] for x, y in zip(a, b)])
                    self.assert_states(left.intersection(right), [conjoin[x + y] for x, y in zip(a, b)])
                    self.assert_states(left.difference(right), [conjoin[x + negate[y]] for x, y in zip(a, b)])
                    self.assertEqual(left.union(right).negate(), left.negate().intersection(right.negate()))

    def test_negation_and_self_difference_do_not_turn_unknown_into_false(self):
        basis = SourceBasis("p", 0, 3)
        query = self.query(basis, "TFU")
        self.assert_states(query.union(query.negate()), "TTU")
        self.assert_states(query.difference(query), "FFU")

    def test_constructor_requires_disjoint_coverage_within_window(self):
        basis = SourceBasis("p", 0, 5)
        window = basis.span(1, 4)
        for matches, unknown in (((0, 2), (3, 4)), ((1, 2), (3, 5)), ((1, 3), (2, 4))):
            with self.subTest(matches=matches, unknown=unknown), self.assertRaises(ValueError):
                Coverage(window, SpanSet(basis, (basis.span(*matches),)), SpanSet(basis, (basis.span(*unknown),)))
        foreign = SourceBasis("p", 0, 5)
        with self.assertRaises(ValueError):
            Coverage(window, SpanSet(foreign), SpanSet(basis))

    def test_composition_requires_same_basis_and_same_query_window(self):
        basis = SourceBasis("p", 0, 3)
        query = self.query(basis, "TFU")
        for other in (query.restrict(basis.span(1, 3)), self.query(SourceBasis("p", 0, 3), "TFU")):
            for method in ("union", "intersection", "difference"):
                with self.subTest(method=method), self.assertRaises(ValueError):
                    getattr(query, method)(other)

    def test_restriction_clips_all_three_states_and_preserves_empty_window(self):
        basis = SourceBasis("p", 0, 6)
        query = self.query(basis, "TTUFUU")
        restricted = query.restrict(basis.span(1, 5))
        self.assertEqual(cells(restricted.matches), {1})
        self.assertEqual(cells(restricted.nonmatches), {3})
        self.assertEqual(cells(restricted.unknown), {2, 4})
        empty = query.restrict(basis.span(3, 3))
        self.assertEqual(empty.partition(), ())
        self.assertEqual(empty.window.start, 3)
        with self.assertRaises(ValueError):
            restricted.restrict(basis.whole)

    def test_partition_labels_entire_window_without_gluing_across_extra_cuts(self):
        basis = SourceBasis("p", 0, 6)
        query = self.query(basis, "TTUFUU")
        parts = query.partition((1, 5, 5))
        self.assertEqual([(p.span.start, p.span.end, p.state) for p in parts],
                         [(0, 1, "match"), (1, 2, "match"), (2, 3, "unknown"),
                          (3, 4, "nonmatch"), (4, 5, "unknown"), (5, 6, "unknown")])
        self.assertTrue(all(isinstance(p.state, CoverageState) for p in parts))
        self.assertEqual([p.span.end for p in parts[:-1]], [p.span.start for p in parts[1:]])


class ReadingCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def setup_reader(self, source, *, occurrence_id=3):
        self.resolver = BindingResolver(self.catalog)
        self.context = self.resolver.new_context()
        self.reader = TexReader(source, source_id="paper.tex", occurrence_id=occurrence_id,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, self.resolver)

    def test_literal_and_definition_extents_and_bodies_are_real_consumers(self):
        source = r"a\verb|\input{x}|\def\f{\verb|inert|}z"
        self.setup_reader(source)
        items = list(self.dispatcher)
        report = ReadingCoverage(self.reader.basis, items)
        literal = next(i for i in items if isinstance(i, LiteralRegion))
        definition = next(i for i in items if isinstance(i, StoredDefinition))
        self.assertIs(report.literal_regions[0], literal)
        self.assertIs(report.stored_definitions[0], definition)
        self.assertEqual(report.query("literal").matches.spans, (literal.span,))
        self.assertEqual(report.query("definition", part="body").matches.spans, (definition.body,))
        self.assertEqual(self.reader.source_slice(literal.body), r"\input{x}")
        self.assertEqual(self.reader.source_slice(definition.body), r"\verb|inert|")
        self.assertTrue(report.query("literal").nonmatches.covers(definition.span))
        self.assertFalse(report.unknown)
        self.assertEqual(report.diagnostics, ())
        combined = report.query("literal").union(report.query("definition"))
        self.assertEqual(combined.matches.spans, (self.reader.source_span(literal.span.start, definition.span.end),))
        self.assertEqual(self.reader.text, source)

    def test_unknown_suffix_survives_queries_negation_and_composition(self):
        source = r"a\verb|known|b\unknown\verb|unestablished|"
        self.setup_reader(source)
        report = ReadingCoverage(self.reader.basis, self.dispatcher)
        boundary = report.diagnostics[0]
        suffix = self.reader.source_span(source.index(r"\unknown"), len(source))
        self.assertEqual(boundary.remainder, suffix)
        self.assertEqual(report.unknown.spans, (suffix,))
        literals, definitions = report.query("literal"), report.query("definition")
        self.assertEqual(literals.negate().unknown, report.unknown)
        self.assertFalse(literals.negate().matches.intersection(report.unknown))
        self.assertEqual(literals.union(definitions).unknown, report.unknown)
        self.assertEqual(literals.intersection(definitions).unknown, report.unknown)
        self.assertEqual(len(report.literal_regions), 1)

    def test_partial_scan_and_unobserved_gaps_stay_unknown_without_diagnostic(self):
        self.setup_reader("abcd")
        first = self.dispatcher.next_item()
        report = ReadingCoverage(self.reader.basis, (first,))
        self.assertEqual(cells(report.query("literal").nonmatches), {0})
        self.assertEqual(cells(report.unknown), {1, 2, 3})
        self.assertEqual(report.diagnostics, ())
        # A caller may supply observations from disjoint windows without proving the gap.
        last = ReadEvent(EventKind.TOKEN, self.reader.source_span(3, 4), ReaderState.MID_LINE, ReaderState.MID_LINE)
        gapped = ReadingCoverage(self.reader.basis, (first, last))
        self.assertEqual(cells(gapped.observed), {0, 3})
        self.assertEqual(cells(gapped.unknown), {1, 2})

    def test_snapshot_does_not_change_when_dispatcher_later_advances(self):
        self.setup_reader(r"\verb|a|\def\x{b}")
        snapshot = ReadingCoverage(self.reader.basis, (self.dispatcher.next_item(),))
        old_unknown = snapshot.unknown
        list(self.dispatcher)
        self.assertEqual(snapshot.unknown, old_unknown)
        self.assertEqual(snapshot.stored_definitions, ())

    def test_failed_literal_and_definition_remain_unknown_from_their_opener(self):
        for source in ("x\\verb|missing", r"x\def\foo{missing", "x\x7ftail", r"x\def\foo#2{oops}"):
            with self.subTest(source=source):
                self.setup_reader(source)
                report = ReadingCoverage(self.reader.basis, self.dispatcher)
                self.assertEqual(report.unknown.spans, (self.reader.source_span(1, len(source)),))
                self.assertFalse(report.query("literal").matches)
                self.assertFalse(report.query("definition").matches)
                self.assertEqual(len(report.diagnostics), 1)

    def test_empty_eof_residue_keeps_earlier_diagnostic_anchor_without_erasing_observations(self):
        self.setup_reader(r"{\verb|x|")
        report = ReadingCoverage(self.reader.basis, self.dispatcher)
        self.assertFalse(report.unknown)
        self.assertTrue(report.observed.covers(self.reader.basis.whole))
        self.assertEqual(report.diagnostics[0].reason, "unclosed_group")
        self.assertEqual(self.reader.source_slice(report.diagnostics[0].span), "{")
        self.assertEqual(report.diagnostics[0].remainder.start, len(self.reader.text))
        self.assertEqual(len(report.literal_regions), 1)

    def test_adjacent_regions_keep_individual_identity_and_empty_body_locations(self):
        for source, kind in ((r"\verb||\verb||", "literal"), (r"\def\a{}\def\b{}", "definition")):
            with self.subTest(kind=kind):
                self.setup_reader(source)
                items = list(self.dispatcher)
                report = ReadingCoverage(self.reader.basis, items)
                records = report.literal_regions if kind == "literal" else report.stored_definitions
                self.assertEqual(len(records), 2)
                self.assertIs(records[0], items[0])
                self.assertIs(records[1], items[1])
                self.assertNotEqual(records[0].body.start, records[1].body.start)
                self.assertEqual(report.query(kind).matches.spans, (self.reader.basis.whole,))
                self.assertFalse(report.query(kind, part="body").matches)

    def test_query_window_can_cross_observed_and_unknown_coverage(self):
        self.setup_reader(r"\verb|abc|\unknown")
        report = ReadingCoverage(self.reader.basis, self.dispatcher)
        body = report.literal_regions[0].body
        window = self.reader.source_span(body.start + 1, len(self.reader.text) - 1)
        query = report.query("literal", part="body", window=window)
        self.assertEqual(query.matches.spans, (self.reader.source_span(body.start + 1, body.end),))
        self.assertEqual(query.unknown.spans, (self.reader.source_span(body.end + 1, window.end),))
        self.assertEqual(query.nonmatches.spans, (self.reader.source_span(body.end, body.end + 1),))
        self.assertEqual(query, report.query("literal", part="body").restrict(window))

    def test_unicode_crlf_caret_spelling_and_trailing_spaces_use_source_coordinates(self):
        source = "α\\verb|🙂|\r\n\\def\\x{^^41}  "
        self.setup_reader(source)
        report = ReadingCoverage(self.reader.basis, self.dispatcher)
        self.assertEqual(self.reader.basis.length, len(source))
        self.assertEqual(report.observed.covered_length, len(source))
        self.assertEqual(report.query("literal", part="body").matches.covered_length, 1)
        self.assertEqual(report.query("definition", part="body").matches.covered_length, 4)
        parts = report.query("literal").partition()
        self.assertEqual("".join(self.reader.source_slice(part.span) for part in parts), source)

    def test_identical_read_labels_do_not_allow_cross_occurrence_coverage(self):
        source = r"\verb|x|"
        self.setup_reader(source)
        first_reader, first_items = self.reader, list(self.dispatcher)
        self.setup_reader(source)
        with self.assertRaises(ValueError):
            ReadingCoverage(self.reader.basis, first_items)
        with self.assertRaises(ValueError):
            self.reader.source_slice(first_items[0].span)
        first = ReadingCoverage(first_reader.basis, first_items).query("literal")
        second = ReadingCoverage(self.reader.basis, self.dispatcher).query("literal")
        with self.assertRaises(ValueError):
            first.union(second)

    def test_empty_source_keeps_zero_width_diagnostics_separate_from_coverage(self):
        self.setup_reader("")
        report = ReadingCoverage(self.reader.basis, self.dispatcher)
        self.assertFalse(report.unknown)
        self.assertEqual(report.query("literal").partition(), ())
        boundary = ReadingBoundary(self.reader.basis.whole, self.reader.basis.whole, "unsupported", "empty site")
        unresolved = ReadingCoverage(self.reader.basis, (boundary,))
        self.assertIs(unresolved.diagnostics[0], boundary)
        self.assertFalse(unresolved.unknown)

    def test_adapter_rejects_overlaps_invalid_parts_and_items_after_a_boundary(self):
        self.setup_reader(r"\verb|x|\unknown")
        items = list(self.dispatcher)
        literal, boundary = items[0], items[1]
        malformed = replace(literal, body=literal.span)
        for bad in ((literal, literal), (malformed,), (boundary, literal),
                    (literal, replace(boundary, remainder=self.reader.basis.whole))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ReadingCoverage(self.reader.basis, bad)
        with self.assertRaises(TypeError):
            ReadingCoverage(self.reader.basis, ("not a record",))

    def test_no_observations_prove_nothing_and_invalid_query_names_are_rejected(self):
        basis = SourceBasis("p", 0, 10)
        report = ReadingCoverage(basis, ())
        self.assertEqual(report.unknown.spans, (basis.whole,))
        self.assertFalse(report.query("literal").nonmatches)
        for kind, part in (("prose", "span"), ("literal", "missing")):
            with self.assertRaises(ValueError):
                report.query(kind, part=part)

    def test_scanning_and_coverage_after_bootstrap_perform_no_file_io(self):
        self.setup_reader(r"\verb|literal|\def\f{body}\f")
        with patch("builtins.open", side_effect=AssertionError("Unexpected I/O")), \
             patch.object(Path, "open", side_effect=AssertionError("Unexpected I/O")):
            report = ReadingCoverage(self.reader.basis, self.dispatcher)
            parts = report.query("literal").union(report.query("definition")).negate().partition()
        self.assertEqual(parts[-1].state, CoverageState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
