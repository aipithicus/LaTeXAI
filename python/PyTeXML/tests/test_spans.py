"""Interval laws checked against independent finite sets of character positions."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.reading.spans import SourceBasis, SourceSpan, SpanSet


def cells(selection):
    return {position for span in selection for position in range(span.start, span.end)}


class SpanTests(unittest.TestCase):
    def setUp(self):
        self.basis = SourceBasis("paper.tex", 3, 10)

    def selection(self, *pairs):
        return SpanSet(self.basis, (self.basis.span(*pair) for pair in pairs))

    def test_normalization_merges_overlap_and_adjacency_but_keeps_gaps(self):
        raw = [self.basis.span(*pair) for pair in ((7, 9), (1, 3), (2, 4), (4, 4), (4, 5), (1, 3))]
        original = tuple(raw)
        coverage = SpanSet(self.basis, iter(raw))
        self.assertEqual(coverage.spans, (self.basis.span(1, 5), self.basis.span(7, 9)))
        self.assertEqual(tuple(raw), original)
        self.assertEqual(coverage.covered_length, 6)
        self.assertTrue(coverage)
        self.assertFalse(SpanSet(self.basis))

    def test_empty_span_keeps_location_but_has_no_coverage(self):
        empty = self.basis.span(6, 6)
        self.assertFalse(SpanSet(self.basis, (empty,)))
        self.assertEqual((empty.start, empty.end), (6, 6))
        self.assertTrue(self.selection().covers(empty))
        self.assertEqual(self.selection().partition((6,)), ())

    def test_spans_are_validated_at_construction(self):
        for start, end in ((-1, 0), (0, 11), (7, 6)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                SourceSpan(self.basis, start, end)
        for start, end in ((False, 1), (0, True), (0.0, 1), (0, "1")):
            with self.subTest(start=start, end=end), self.assertRaises(TypeError):
                self.basis.span(start, end)
        with self.assertRaises(TypeError):
            SourceSpan("paper.tex", 0, 1)

    def test_basis_and_coverage_reject_invalid_inputs_even_when_empty(self):
        for args, error in ((("p", 0, -1), ValueError), (("p", 0, 1.5), TypeError),
                            (("p", 0, True), TypeError), (("p", False, 2), TypeError),
                            ((None, 0, 2), TypeError)):
            with self.subTest(args=args), self.assertRaises(error):
                SourceBasis(*args)
        with self.assertRaises(TypeError):
            SpanSet(None)
        with self.assertRaises(TypeError):
            SpanSet(self.basis, ((1, 2),))
        zero = SourceBasis("empty", 0, 0)
        self.assertFalse(SpanSet(zero, (zero.whole,)))

    def test_basis_identity_is_not_filename_occurrence_number_or_length_equality(self):
        same_labels = SourceBasis("paper.tex", 3, 10)
        self.assertNotEqual(self.basis, same_labels)
        self.assertNotEqual(self.basis.whole, same_labels.whole)
        for foreign in (same_labels, SourceBasis("paper.tex", 4, 10), SourceBasis("other", 3, 10)):
            with self.subTest(foreign=foreign):
                for spans in ((foreign.whole,), (foreign.span(0, 0),)):
                    with self.assertRaises(ValueError):
                        SpanSet(self.basis, spans)
                for method in ("union", "intersection", "difference", "covers"):
                    with self.assertRaises(ValueError):
                        getattr(SpanSet(self.basis), method)(SpanSet(foreign))
                for method in ("clip", "complement", "covers"):
                    with self.assertRaises(ValueError):
                        getattr(self.selection((1, 2)), method)(foreign.span(0, 0))

    def test_basis_span_and_set_are_immutable(self):
        for record, field, value in ((self.basis, "length", 20),
                                      (self.basis.whole, "end", 20),
                                      (self.selection((1, 2)), "spans", ())):
            with self.subTest(field=field), self.assertRaises(FrozenInstanceError):
                setattr(record, field, value)

    def test_all_small_set_pairs_against_independent_position_sets(self):
        basis = SourceBasis("finite", 0, 5)
        fixtures = []
        for mask in range(1 << basis.length):
            points = {i for i in range(basis.length) if mask & (1 << i)}
            # Deliberately unordered unit intervals; normalization is not the oracle.
            spans = [basis.span(i, i + 1) for i in sorted(points, reverse=True)]
            fixtures.append((points, SpanSet(basis, spans)))
        for a, left in fixtures:
            self.assertEqual(cells(left.complement(basis.whole)), set(range(5)) - a)
            for b, right in fixtures:
                with self.subTest(a=a, b=b):
                    self.assertEqual(cells(left.union(right)), a | b)
                    self.assertEqual(cells(left.intersection(right)), a & b)
                    self.assertEqual(cells(left.difference(right)), a - b)
                    self.assertEqual(left.covers(right), b <= a)
                    self.assertEqual(left.union(right), right.union(left))
                    self.assertEqual(left.intersection(right), right.intersection(left))
                    self.assertEqual(left.difference(right).intersection(right), SpanSet(basis))
                    self.assertEqual(left.intersection(right).union(left.difference(right)), left)

    def test_clipping_and_bounded_complement_for_every_small_window(self):
        selection = self.selection((1, 4), (6, 9))
        for start in range(11):
            for end in range(start, 11):
                window = self.basis.span(start, end)
                expected_window = set(range(start, end))
                self.assertEqual(cells(selection.clip(window)), cells(selection) & expected_window)
                self.assertEqual(cells(selection.complement(window)), expected_window - cells(selection))
                self.assertEqual(selection.covers(window), expected_window <= cells(selection))

    def test_difference_handles_a_single_cut_crossing_multiple_intervals(self):
        left = self.selection((0, 2), (3, 5), (6, 8), (9, 10))
        self.assertEqual(left.difference(self.selection((1, 7))), self.selection((0, 1), (7, 8), (9, 10)))

    def test_partition_preserves_coverage_gaps_and_requested_boundaries(self):
        selection = self.selection((1, 4), (7, 10))
        pieces = selection.partition((10, 2, 9, 0, 4, 7, 3, 5, 2, 1))
        self.assertEqual([(s.start, s.end) for s in pieces], [(1, 2), (2, 3), (3, 4), (7, 9), (9, 10)])
        self.assertEqual(SpanSet(self.basis, pieces), selection)
        self.assertEqual(selection.partition(()), selection.spans)
        for bad, error in ((-1, ValueError), (11, ValueError), (True, TypeError), (1.5, TypeError)):
            with self.subTest(bad=bad), self.assertRaises(error):
                SpanSet(self.basis).partition((bad,))

    def test_large_sparse_coordinates_do_not_require_a_character_mask(self):
        basis = SourceBasis("large", 0, 10**15)
        left = SpanSet(basis, (basis.span(0, 2), basis.span(10**15 - 2, 10**15)))
        cut = SpanSet(basis, (basis.span(1, 10**15 - 1),))
        self.assertEqual(left.difference(cut).covered_length, 2)
        self.assertEqual(left.union(cut).spans, (basis.whole,))


if __name__ == "__main__":
    unittest.main()
