"""Page derivatives and captured asset uses share one preparation route."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import fitz
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.assets import convert_asset_to_svg, pdf_to_svg
from src.prepare.pipeline import preprocess_paper


class AssetFidelityTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def pdf(self):
        with fitz.open() as doc:
            for width in (100, 200, 300):
                doc.new_page(width=width, height=120).insert_text((10, 20), str(width))
            doc.save(self.root / "figure.pdf")

    def prepare(self):
        return preprocess_paper(str(self.root), root_tex="main.tex")

    def test_page_variants_shared_across_active_deferred_and_repeated_inputs(self):
        self.pdf()
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}"
            r"\includegraphics{figure.pdf}\input{child}\input{child}"
            r"\unknown{\includegraphics[page={3},width=.5\linewidth]{figure.pdf}}")
        self.put("child.tex", r"\includegraphics[page=2,angle=30]{figure.pdf}"
            r"\includegraphics[page=1]{figure.pdf}")
        with patch("src.prepare.assets.convert_asset_to_svg", wraps=convert_asset_to_svg) as convert:
            text, manifest, out, _ = self.prepare()
        self.assertEqual(convert.call_count, 3)
        self.assertEqual(text.count("{figure_p1.svg}"), 3)
        self.assertEqual(text.count("[page=1,angle=30]{figure_p2.svg}"), 2)
        self.assertIn(r"[page={1},width=.5\linewidth]{figure_p3.svg}", text)
        for page, width in ((1, 100), (2, 200), (3, 300)):
            svg = ET.parse(out / f"figure_p{page}.svg").getroot()
            self.assertEqual(float(svg.attrib["viewBox"].split()[2]), width)
        self.assertFalse((out / "figure.pdf").exists())
        observed = [d for d in manifest.candidate_dependencies if d.get("page") == 3]
        self.assertEqual(observed[0]["payload"], "figure_p3.svg")
        self.assertEqual(observed[0]["activity"], "unresolved")

    def test_literal_assets_in_retained_local_commands_and_hooks(self):
        Image.new("RGB", (2, 3)).save(self.root / "logo.png")
        body = r"\AtBeginDocument{\includegraphics{logo.png}}"
        self.put("local.sty", body)
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx,local}"
            r"\unknown{\includegraphics{logo.png}}")
        with patch("src.prepare.assets.convert_asset_to_svg", wraps=convert_asset_to_svg) as convert:
            text, manifest, out, _ = self.prepare()
        self.assertEqual(convert.call_count, 1)
        self.assertIn(r"\unknown{\includegraphics{logo.svg}}", text)
        self.assertEqual((out / "local.sty").read_text(), body.replace("logo.png", "logo.svg"))
        self.assertEqual((self.root / "local.sty").read_text(), body)
        self.assertTrue(all(d["status"] == "prepared" for d in manifest.candidate_dependencies))

    def test_page_output_name_cannot_overwrite_another_asset(self):
        self.pdf()
        self.put("figure_p2.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="5"/>')
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}"
            r"\includegraphics[page=2]{figure.pdf}\includegraphics{figure_p2.svg}")
        text, _, out, _ = self.prepare()
        self.assertIn("{figure.pdf_p2.svg}", text)
        self.assertIn("{figure_p2.svg.svg}", text)
        self.assertEqual(len(list(out.glob("*.svg"))), 2)

    def test_page_out_of_bounds_never_substitutes_first_page(self):
        self.pdf()
        for page_index in (-1, 3):
            with self.subTest(page_index=page_index), self.assertRaisesRegex(RuntimeError, "Requested page"):
                pdf_to_svg(self.root / "figure.pdf", self.root / "wrong.svg", page_index)
        self.assertFalse((self.root / "wrong.svg").exists())

    def test_inactive_provider_can_package_a_literal_reference_without_activation(self):
        Image.new("RGB", (2, 3)).save(self.root / "logo.png")
        self.put("main.tex", r"\documentclass{article}\includegraphics{logo.png}TAIL")
        text, manifest, out, _ = self.prepare()
        self.assertIn(r"\includegraphics{logo.svg}", text)
        self.assertIn("TAIL", text)
        self.assertTrue((out / "logo.svg").exists())
        self.assertTrue(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))
        self.assertEqual(manifest.candidate_dependencies[0]["status"], "prepared")

    def test_inline_literal_inside_deferred_argument_does_not_supply_a_fake_asset(self):
        Image.new("RGB", (2, 3)).save(self.root / "fake.png")
        source = r"\documentclass{article}\unknown{\verb|\includegraphics{fake.png}|}TAIL"
        self.put("main.tex", source)
        text, manifest, out, _ = self.prepare()
        self.assertIn(r"\verb|\includegraphics{fake.png}|", text)
        self.assertEqual(manifest.candidate_dependencies, [])
        self.assertEqual(list(out.glob("*.svg")), [])

    def test_deferred_search_changes_and_local_shadowing_do_not_use_entry_meanings(self):
        Image.new("RGB", (2, 3)).save(self.root / "logo.png")
        body = r"\unknown{\graphicspath{{other/}}\includegraphics{logo.png}}"
        shadowed = r"\unknown{\def\includegraphics#1{nothing}\includegraphics{logo.png}}"
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}" + body + shadowed)
        text, manifest, out, _ = self.prepare()
        self.assertIn(body + shadowed, text)
        self.assertEqual(len(manifest.candidate_dependencies), 1)
        self.assertEqual(manifest.candidate_dependencies[0]["reason"], "asset_search_context")
        self.assertEqual(list(out.glob("*.svg")), [])

    def test_admitted_argument_asset_survives_a_later_reading_boundary(self):
        Image.new("RGB", (2, 3)).save(self.root / "logo.png")
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}"
            r"\unknown{\includegraphics{logo.png}}\input{child}TAIL")
        self.put("child.tex", r"\catcode`\%=\computed")
        text, manifest, out, _ = self.prepare()
        self.assertIn(r"\unknown{\includegraphics{logo.svg}}", text)
        self.assertIn(r"\input{child}TAIL", text)
        self.assertTrue((out / "logo.svg").is_file())
        self.assertEqual(manifest.candidate_dependencies[0]["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
