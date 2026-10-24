"""Prepared addresses and source accounting through the actual preparation API."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper
from src.prepare.session import PreparationSession
from src.prepare.locations import finalize_locations
from src.prepare.assets import rewrite_image_references
from src.prepare.provenance import ProvenanceLedger
from src.prepare.inventory import preflight_inventory


class ManifestLocationTests(unittest.TestCase):
    def test_eof_cursors_survive_trailing_discards_repeated_inputs_and_asset_edits(self):
        from PIL import Image
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}\input{child}A\input{child}B\input{empty}C")
        self.put("child.tex", "\\includegraphics{x.png}END% discarded\n   \n")
        self.put("empty.tex", "% only a comment\n")
        Image.new("RGB", (2, 2)).save(self.root / "x.png")
        text, manifest, _, _ = self.prepare()
        eof = [u for u in manifest.units if u["kind"] == "SourceEnd"]
        self.assertEqual(len(eof), 4)
        self.assertTrue(all(u["location_status"] == "mapped" for u in eof))
        child = [u["locations"][0] for u in eof if u["origin"]["source"] == "child.tex"]
        self.assertEqual(len(child), 2)
        self.assertLess(child[0]["start"], child[1]["start"])
        self.assertTrue(all(p["start"] == p["end"] for p in child))
        self.assertEqual(text[child[0]["start"]], "A")
        self.assertEqual(text[child[1]["start"]], "B")
        empty = next(u for u in eof if u["origin"]["source"] == "empty.tex")
        self.assertEqual(text[empty["locations"][0]["start"]], "C")

    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def prepare(self, **kwargs):
        return preprocess_paper(str(self.root), root_tex="main.tex", **kwargs)

    def assert_addresses(self, manifest, output):
        texts = {}
        for artifact in manifest.prepared_artifacts:
            raw = (output / artifact["path"]).read_bytes()
            self.assertEqual(sha256(raw).hexdigest(), artifact["sha256"])
            texts[artifact["path"]] = raw.decode("utf-8")
            self.assertEqual(len(texts[artifact["path"]]), artifact["length"])
        units = {u["id"]: u for u in manifest.units}
        self.assertEqual(len(units), len(manifest.units))
        self.assertEqual(len({r["id"] for r in manifest.requirements}), len(manifest.requirements))
        for record in [*manifest.requirements, *manifest.unresolved]:
            unit = units[record["unit_id"]]
            self.assertEqual(record["locations"], unit["locations"])
            for location in record["locations"]:
                self.assertTrue(0 <= location["start"] <= location["end"] <= len(texts[location["artifact"]]))
        return texts, units

    def assert_accounted(self, ledger):
        self.assertTrue(ledger.source_coverage)
        self.assertEqual([s for s in ledger.source_coverage if s["unaccounted"]], [])
        for t in ledger.tombstones:
            self.assertLess(t.src_start, t.src_end)
            self.assertIsNotNone(t.occurrence)

    def test_repeated_inputs_have_unique_ids_and_master_addresses_without_sidecar(self):
        main = self.put("main.tex", r"\documentclass{article}\input{child}\input{child}")
        body = "  % discard\r\n\\mystery{α😀}   \r\n"
        child = self.put("child.tex", body)
        reads, original = Counter(), Path.read_bytes
        def read(path):
            reads[path.resolve()] += 1
            return original(path)
        with patch.object(Path, "read_bytes", read):
            text, manifest, out, ledger = self.prepare(emit_provenance=False)
        self.assertIsNone(ledger)
        self.assertFalse((out / "master.provenance.json").exists())
        self.assertEqual(reads[main], 1)
        self.assertEqual(reads[child], 1)
        self.assertEqual(child.read_bytes().decode("utf-8"), body)
        texts, units = self.assert_addresses(manifest, out)
        requirements = [r for r in manifest.requirements if r["source"] == "child.tex"]
        self.assertEqual(len(requirements), 2)
        self.assertEqual({r["occurrence"] for r in requirements}, {1, 2})
        self.assertEqual(len({r["unit_id"] for r in requirements}), 2)
        locations = [r["locations"][0] for r in requirements]
        self.assertLess(locations[0]["end"], locations[1]["start"])
        for r, location in zip(requirements, locations):
            self.assertEqual(r["location_status"], "mapped")
            self.assertEqual(text[location["start"]:location["end"]], r"\mystery{α😀}")
        self.assertEqual(json.loads((out / "manifest.json").read_text())["requirements"], manifest.requirements)

    def test_inventory_has_linked_ids_without_pretending_locations_are_final(self):
        self.put("main.tex", r"\documentclass{article}\mystery{body}")
        manifest = preflight_inventory(str(self.root), root_tex="main.tex")
        ids = {u["id"] for u in manifest.units}
        self.assertTrue(manifest.requirements)
        for requirement in manifest.requirements:
            self.assertIn(requirement["unit_id"], ids)
            self.assertEqual(requirement["location_status"], "pending")
            self.assertEqual(requirement["locations"], [])
        self.assertEqual(manifest.prepared_artifacts, [])

    def test_discard_extents_and_occurrences_cover_comments_and_scanner_whitespace(self):
        self.put("main.tex", "\\documentclass{article}\n\\input child\n\\input child\n")
        body = "  % comment\r\n\\textbf  % between header and argument\r\n {B}   \r\n"
        self.put("child.tex", body)
        text, manifest, out, ledger = self.prepare()
        self.assert_accounted(ledger)
        self.assertEqual({t.occurrence for t in ledger.tombstones if t.src_file == "child.tex"}, {1, 2})
        self.assertEqual(ProvenanceLedger.load(out / "master.provenance.json").to_dict(), ledger.to_dict())
        self.assertEqual(ledger.to_dict()["version"], 3)
        for segment in ledger.segments:
            if segment["mapping"] == "copy":
                a, b = segment["source"]
                c, d = segment["generated"]
                raw = (self.root / segment["source_file"]).read_bytes().decode("utf-8")
                self.assertEqual(text[c:d], raw[a:b])
                self.assertEqual(b - a, d - c)

    def test_separators_are_synthetic_and_copied_commands_stay_exact(self):
        self.put("main.tex", r"\documentclass{article}\doublespacing" + "\nTEXT")
        text, manifest, out, ledger = self.prepare()
        self.assertIn(r"\doublespacing TEXT", text)
        separator = next(s for s in ledger.segments if s["operation"] == "SYNTHETIC_SEPARATOR")
        self.assertEqual(separator["mapping"], "insert")
        self.assertEqual(separator["source"][0], separator["source"][1])
        self.assertEqual(text[slice(*separator["generated"])], " ")
        requirement = next(r for r in manifest.requirements if "doublespacing" in r["detail"])
        self.assertEqual(text[slice(requirement["locations"][0]["start"], requirement["locations"][0]["end"])], r"\doublespacing")
        self.assert_accounted(ledger)

    def test_existing_bibliography_replacement_and_style_deletion_are_linked(self):
        source = r"\documentclass{article}\cite{x}\bibliographystyle{agsm}\bibliography{references}"
        self.put("main.tex", source)
        self.put("references.bib", "@article{x,title={Example}}")
        bbl = "  % start\n\\begin{thebibliography}{1}\n\\bibitem{x} Text \\mystery  \n\\end{thebibliography}\n"
        self.put("main.bbl", bbl)
        text, manifest, out, ledger = self.prepare()
        self.assert_accounted(ledger)
        units = {u["id"]: u for u in manifest.units}
        start = source.index(r"\bibliography{")
        unit = next(u for u in units.values() if u["origin"]["source"] == "main.tex" and u["origin"]["start"] == start)
        location, = unit["locations"]
        replacement = text[location["start"]:location["end"]]
        self.assertEqual(unit["location_status"], "mapped")
        self.assertIn(r"\begin{thebibliography}", replacement)
        self.assertIn(r"\end{thebibliography}", replacement)
        link = next(r for r in ledger.replacements if r["source"] == [start, len(source)])
        self.assertEqual(link["generated"], [[location["start"], location["end"]]])
        style = next(t for t in ledger.tombstones if "Bibliography style" in t.reason)
        self.assertEqual(source[style.src_start:style.src_end], r"\bibliographystyle{agsm}")
        self.assertTrue((out / "bibliography.bib").exists())
        self.assert_addresses(manifest, out)

    def test_native_bibliography_audit_uses_the_emitted_generated_basis(self):
        self.put("main.tex", r"\documentclass{article}\cite{x}\bibliography{references}")
        self.put("references.bib", r"@article{x,title={A \mystery{value}}}")
        text, manifest, out, ledger = self.prepare()
        requirements = [r for r in manifest.requirements if r["source"] == "bibliography.bbl"]
        self.assertTrue(requirements)
        for requirement in requirements:
            self.assertEqual(requirement["location_status"], "mapped")
            self.assertEqual({p["artifact"] for p in requirement["locations"]}, {"master.tex"})
            self.assertIn(r"\mystery", text[slice(requirement["locations"][0]["start"], requirement["locations"][0]["end"])])
        self.assert_addresses(manifest, out)
        self.assert_accounted(ledger)

    def test_retained_local_code_locations_follow_its_rebased_input(self):
        self.put("main.tex", r"\documentclass{article}\usepackage{nested/local}")
        local = r"\input{nested/helper.sty}\mystery{after}"
        self.put("nested/local.sty", local)
        self.put("nested/helper.sty", r"\def\known{K}")
        text, manifest, out, ledger = self.prepare()
        texts, _ = self.assert_addresses(manifest, out)
        requirement = next(r for r in manifest.requirements if r["source"] == "nested/local.sty")
        location, = requirement["locations"]
        self.assertEqual(location["artifact"], "nested/local.sty")
        self.assertEqual(texts[location["artifact"]][location["start"]:location["end"]], r"\mystery{after}")
        self.assert_accounted(ledger)

    def test_precise_interests_inside_rewritten_deferred_envelope(self):
        source = (r"\documentclass{article}\usepackage{graphicx}\begin{custom}"
                  r"\includegraphics{a}\caption{CAPTION}\includegraphics{b}\end{custom}")
        self.put("main.tex", source)
        for name in ("a.png", "b.png"):
            Image.new("RGB", (2, 2)).save(self.root / name)
        session = PreparationSession(self.root, root_tex="main.tex").run()
        basis = session._root_reader.basis
        start = source.index("CAPTION")
        caption = session.require(basis.span(start, start + 7), "caption_test", "Tracked interior interest")
        pieces = rewrite_image_references(session.pieces, {u.command.unit_id:
            "much/longer-name.svg" if u.path.name == "a.png" else "b.svg"
            for u in session.asset_uses.values()}, list(session.asset_uses.values()))
        master = ''.join(p.text for p in pieces)
        finalize_locations(session, pieces, master, {})
        location, = caption["locations"]
        self.assertEqual(caption["location_status"], "mapped")
        self.assertEqual(master[location["start"]:location["end"]], "CAPTION")
        self.assertGreater(location["start"], start)
        for r in session.manifest.requirements:
            if r["reason"] == "observed_asset":
                p, = r["locations"]
                self.assertEqual(r["location_status"], "mapped")
                self.assertTrue(master[p["start"]:p["end"]].startswith(r"\includegraphics{"))
                self.assertTrue(master[p["start"]:p["end"]].endswith(".svg}"))

    def test_rolled_back_child_interests_are_explicitly_unmapped(self):
        self.put("main.tex", r"\documentclass{article}\input{child}TAIL")
        self.put("child.tex", r"\mystery{retained obligation}\catcode`\%=\computed")
        text, manifest, out, ledger = self.prepare()
        self.assertIn(r"\input{child}TAIL", text)
        child = [r for r in manifest.requirements if r["source"] == "child.tex"]
        self.assertTrue(child)
        self.assertTrue(all(r["location_status"] == "unmapped" and r["locations"] == [] for r in child))
        self.assertTrue(any(s["source"] == "child.tex" and s["unaccounted"] for s in ledger.source_coverage))
        self.assert_addresses(manifest, out)

    def test_discard_observations_do_not_delete_preserved_literal_or_definition_text(self):
        preserved = "\\def\\later#1{#1% inside definition\n  value}\n\\begin{verbatim}\n % literal \n\\end{verbatim}"
        source = r"\documentclass{article}" + preserved
        self.put("main.tex", source)
        text, _, _, ledger = self.prepare()
        definition, literal = preserved.split("\n\\begin", 1)
        self.assertIn(definition, text)
        self.assertIn("\\begin" + literal, text)
        for t in ledger.tombstones:
            discarded = source[t.src_start:t.src_end]
            self.assertNotIn("inside definition", discarded)
            self.assertNotIn("literal", discarded)
        self.assert_accounted(ledger)


if __name__ == "__main__":
    unittest.main()
