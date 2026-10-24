"""Edit correspondence and reader identities without a preparation or filesystem."""
from pathlib import Path
import sys
import unittest
import random

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bindings.resolver import BindingResolver
from src.prepare.emission import SourcePiece
from src.reading.dispatcher import StructuralDispatcher
from src.reading.edit_map import EditMap, MappingRun
from src.reading.spans import SourceBasis
from src.reading.tex_reader import TexReader
from src.reading.units import UnitRegistry
from src.reading.contracts import DeferredRegion


class EditTrackingTests(unittest.TestCase):
    def test_composed_copy_runs_equal_original_slices_after_arbitrary_edits(self):
        randomizer = random.Random(42)
        original = "αβ😀 abcdef ghi\n012345"
        basis = SourceBasis("file", 0, len(original))
        for _ in range(80):
            piece = SourcePiece(original, basis.whole, 1)
            expected = original
            for _ in range(12):
                start = randomizer.randrange(len(expected) + 1)
                end = randomizer.randrange(start, len(expected) + 1)
                replacement = "XYZ"[:randomizer.randrange(4)]
                piece = piece.edited(start, end, replacement, "TEST_EDIT")
                expected = expected[:start] + replacement + expected[end:]
                self.assertEqual(piece.text, expected)
                self.assertEqual(piece.mapping.length, len(expected))
                for run in piece.mapping.runs:
                    if run.kind == "copy":
                        self.assertEqual(expected[run.start:run.end], original[run.source.start:run.source.end])

    def test_composed_edits_relocate_an_unchanged_suffix_exactly(self):
        text = "prefix old-name caption tail"
        basis = SourceBasis("main.tex", 1, len(text))
        piece = SourcePiece(text, basis.whole, 1)
        filename = basis.span(7, 15)
        caption = basis.span(16, 23)
        piece = piece.edit_source(filename, "much-longer-name.svg", "IMAGE")
        piece = piece.edit_source(basis.span(0, 6), "P", "COMPACT")
        location, = piece.mapping.project(caption)
        self.assertEqual(piece.text[location.start:location.end], "caption")
        self.assertEqual(location.relation, "copy")
        replaced, = piece.mapping.project(filename)
        self.assertEqual(piece.text[replaced.start:replaced.end], "much-longer-name.svg")
        self.assertEqual(replaced.relation, "replace")

    def test_subrange_inside_replacement_is_enclosing_not_interpolated(self):
        basis = SourceBasis("file", 0, 10)
        mapping = EditMap.copied(basis.whole).edit(2, 8, 3)
        projected, = mapping.project(basis.span(4, 5))
        self.assertEqual((projected.start, projected.end, projected.relation), (2, 5, "enclosing"))
        whole = mapping.project(basis.whole)
        self.assertFalse(any(p.relation == "enclosing" for p in whole))

    def test_insertion_affinity_and_deletion_preserve_source_extents(self):
        basis = SourceBasis("file", 0, 6)
        mapping = EditMap.copied(basis.whole).edit(6, 6, 1)
        self.assertEqual([(p.start, p.end) for p in mapping.project(basis.whole)], [(0, 6)])
        mapping = mapping.edit(2, 2, 3)
        projected = mapping.project(basis.whole)
        self.assertEqual(sorted((p.start, p.end) for p in projected), [(0, 2), (2, 5), (5, 9)])
        mapping = mapping.edit(5, 7, 0)
        removed, = mapping.project(basis.span(2, 4))
        self.assertEqual((removed.start, removed.end, removed.relation), (5, 5, "replace"))

    def test_later_partial_replacement_cannot_restore_lost_correspondence(self):
        basis = SourceBasis("file", 0, 10)
        mapping = EditMap.copied(basis.whole).edit(2, 8, 6).edit(3, 4, 10)
        projected, = mapping.project(basis.span(4, 5))
        self.assertEqual((projected.start, projected.end, projected.relation), (2, 17, "enclosing"))
        self.assertEqual(mapping.length, 19)

    def test_invalid_copy_and_ambiguous_source_edit_are_rejected(self):
        basis = SourceBasis("file", 0, 6)
        with self.assertRaises(ValueError):
            MappingRun(basis.whole, 0, 7)
        piece = SourcePiece("abcdef", basis.whole, 1).edited(1, 5, "X", "REPLACE")
        with self.assertRaises(ValueError):
            piece.edit_source(basis.span(2, 3), "Y", "REPLACE")

    def test_two_equal_source_names_are_not_the_same_occurrence(self):
        first, second = SourceBasis("file", 0, 6), SourceBasis("file", 1, 6)
        self.assertEqual(EditMap.copied(first.whole).project(second.whole), ())

    def test_dispatcher_ids_work_on_master_and_shared_readers(self):
        registry = UnitRegistry()
        observed = []
        for occurrence, name in enumerate(("raw.tex", "master.tex")):
            resolver = BindingResolver()
            context = resolver.new_context()
            reader = TexReader(r"\begin{custom}\includegraphics{a.png}\end{custom}", source_id=name,
                occurrence_id=occurrence, catcodes=context.catcodes, endline_char=context.endlinechar)
            dispatcher = StructuralDispatcher(reader, context, resolver, units=registry,
                source_commands=True, preparation=True)
            region = next(i for i in dispatcher if isinstance(i, DeferredRegion))
            child, = region.observations
            self.assertEqual(child.command.unit_id, child.unit_id)
            self.assertEqual(registry.records[child.unit_id].parent_id, region.unit_id)
            observed.append(region.unit_id)
        self.assertEqual(len(set(observed)), 2)
        self.assertEqual(len(registry.records), len(set(registry.records)))


if __name__ == "__main__":
    unittest.main()
