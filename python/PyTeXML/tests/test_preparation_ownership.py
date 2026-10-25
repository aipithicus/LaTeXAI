"""Inspection helpers work from captured data; sessions own source mutations."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.resolver import BindingResolver
from src.prepare.assets import parse_asset_use, surviving_asset_uses, rewrite_image_references
from src.prepare.citations import discover_citations
from src.prepare.emission import SourcePiece
from src.prepare.locations import PreparedLocations
from src.prepare.provenance import Tombstone
from src.prepare.session import PreparationSession, PreparationUnresolved
from src.reading.contracts import DeferredRegion, SourceCommand
from src.reading.dispatcher import StructuralDispatcher
from src.reading.spans import SourceBasis
from src.reading.tex_reader import TexReader
from src.reading.units import UnitRegistry


class PreparationOwnershipTests(unittest.TestCase):
    def scan(self, text, resolver, units, occurrence=0):
        context = resolver.new_context()
        reader = TexReader(text, source_id="part.tex", occurrence_id=occurrence,
                           catcodes=context.catcodes, endline_char=context.endlinechar)
        items = list(StructuralDispatcher(reader, context, resolver, units=units,
                                         preparation=True, source_commands=True))
        return reader, items

    def test_asset_selection_and_rewrite_preserve_occurrence_and_rollback_boundaries(self):
        resolver, units = BindingResolver(), UnitRegistry()
        resolver.load_package("graphicx")
        source = r"\includegraphics[page={2}]{figure.pdf}"
        readers, uses, pieces = [], [], []
        for occurrence in range(3):
            reader, items = self.scan(source, resolver, units, occurrence)
            command = next(i for i in items if isinstance(i, SourceCommand))
            readers.append(reader)
            uses.append(parse_asset_use(command, Path("figure.pdf")))
            pieces.append(SourcePiece(source, command.span, 1,
                "IDENTITY" if occurrence == 0 else "PRESERVE_UNRESOLVED"))
        selected = surviving_asset_uses(uses, pieces, retained_bases={readers[2].basis})
        self.assertEqual(selected, [uses[0], uses[2]])
        mapping = {u.command.unit_id: "figure_p2.svg" for u in selected}
        rewritten = rewrite_image_references(pieces, mapping, selected)
        self.assertEqual(rewritten[0].text, r"\includegraphics[page={1}]{figure_p2.svg}")
        self.assertEqual([p.text for p in rewritten[1:]], [source, source])
        self.assertEqual([p.text for p in pieces], [source] * 3)
        locations = PreparedLocations()
        locations.add("master.tex", "".join(p.text for p in rewritten), rewritten)
        target = locations.project(uses[0].command.argument("target").span)["locations"][0]
        self.assertEqual(rewritten[0].text[target["start"]:target["end"]], "figure_p2.svg")

    def test_citation_observation_returns_work_without_mutating_units_or_activation(self):
        resolver, units = BindingResolver(), UnitRegistry()
        source = r"\cite{known}\cite{\computed}\citep{candidate}$x$"
        _, items = self.scan(source, resolver, units)
        pieces = [SourcePiece(source[i.span.start:i.span.end], i.span, 1,
                    command=i if isinstance(i, SourceCommand) else None,
                    deferred=i if isinstance(i, DeferredRegion) else None)
                  for i in items if isinstance(i, (SourceCommand, DeferredRegion))]
        before = dict(units.records)
        result = discover_citations(pieces, resolver, line=lambda span: 7)
        self.assertEqual(result.keys, ["known", "candidate"])
        self.assertEqual(result.established_keys, {"known"})
        self.assertEqual(result.discovery, "partial")
        self.assertEqual(len(result.requirements), 1)
        self.assertEqual(result.requirements[0].reason, "computed_argument")
        self.assertEqual(source[result.requirements[0].span.start:result.requirements[0].span.end], r"\cite{\computed}")
        self.assertTrue(all(g["line"] == 7 for g in result.gaps))
        self.assertFalse(resolver.is_package_active("natbib"))
        self.assertEqual(units.records, before)

    def test_coverage_uses_occurrence_specific_evidence_without_a_session(self):
        text = "a%lost\nb"
        first = SourceBasis("part.tex", 0, len(text))
        second = SourceBasis("part.tex", 1, len(text))
        generated = SourceBasis("bibliography.bbl", 2, 1)
        pieces = [SourcePiece(value, basis.span(a, b), 1)
                  for basis in (first, second) for value, a, b in (("a", 0, 1), ("b", 7, 8))]
        pieces.append(SourcePiece("g", generated.whole, 1))
        locations = PreparedLocations()
        locations.add("master.tex", "ababg", pieces)
        locations.account((first, second), generated_sources=(generated,), readers={}, line=lambda span: 1,
            tombstones=[Tombstone("part.tex", 1, 7, "OMIT", "comment", occurrence=0)])
        self.assertEqual(locations.project(first.span(1, 7))["location_status"], "omitted")
        self.assertEqual(locations.project(second.span(1, 7))["location_status"], "unmapped")
        self.assertEqual([r["unaccounted"] for r in locations.source_coverage], [[], [[1, 7]], []])
        self.assertEqual(locations.source_coverage[-1]["origin_kind"], "generated")

    def test_retained_payload_rejects_conflicting_occurrences_without_rereading(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\documentclass{article}", encoding="utf-8")
            style = root / "local.sty"
            style.write_text("asset.ext", encoding="utf-8")
            session = PreparationSession(root, root_tex="main.tex")
            first, second = session.open_source(style), session.open_source(style)
            self.assertIsNot(first.basis, second.basis)
            self.assertIs(session.documents[first.basis], session.documents[second.basis])
            for reader in (first, second):
                session.edit_payload(reader.basis.span(0, 5), "new")
            with self.assertRaisesRegex(PreparationUnresolved, "context_dependent_payload"):
                session.edit_payload(second.basis.span(0, 5), "different")
            self.assertEqual(session.payload_text(style), "new.ext")
            self.assertEqual(session.store.read_paths.count("local.sty"), 1)
            self.assertEqual(style.read_text(encoding="utf-8"), "asset.ext")


if __name__ == "__main__":
    unittest.main()
