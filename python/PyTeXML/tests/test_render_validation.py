"""Optional rendering must preserve inputs and dispose of derived resources."""
from collections import Counter
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image
import pymupdf

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.assets import raster_to_svg_wrapper
from src.validation.assets import stage_svg
from src.validation.render import (BOOTSTRAP, DRIVER_NAME, RenderConfig, compiler_environment,
                                   render_comparison, stage_project, compare_pdfs)


class RenderValidationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.original = self.root / "original"
        self.prepared = self.root / "prepared"
        self.original.mkdir()
        self.prepared.mkdir()
        self.output = self.root / "comparison"
        self.config = RenderConfig(Path(sys.executable), timeout_seconds=7)

    def put(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return path

    def pair(self):
        self.put(self.original / "paper.tex", r"\documentclass{article}\begin{document}Hello\end{document}")
        self.put(self.prepared / "master.tex", r"\documentclass{article}\begin{document}Hello\end{document}")

    def pdf(self, path, text="Hello", image=None):
        with pymupdf.open() as doc:
            page = doc.new_page(width=100, height=100)
            page.insert_text((10, 20), text, fontsize=8)
            if image:
                page.insert_image(pymupdf.Rect(10, 30, 40, 50), filename=str(image))
            doc.save(path)

    def snapshot(self, directory):
        return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.rglob("*") if p.is_file()}

    def fake_compiler(self, command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, b"Tectonic test fixture\n", b"")
        self.assertIn("--untrusted", command)
        self.assertIn("--only-cached", command)
        self.assertEqual(kwargs["timeout"], 7)
        entry = Path(command[-1])
        self.assertTrue(entry.read_bytes().startswith(BOOTSTRAP))
        self.assertEqual(kwargs["cwd"], entry.parent)
        build = Path(command[command.index("--outdir") + 1])
        self.pdf(build / (entry.stem + ".pdf"))
        kwargs["stdout"].write(b"TEST COMPILER\n")
        return subprocess.CompletedProcess(command, 0)

    def test_pair_preserves_sources_reads_once_and_removes_every_temporary_asset(self):
        self.pair()
        Image.new("RGB", (5, 4), "red").save(self.original / "figure.png")
        raster_to_svg_wrapper(self.original / "figure.png", self.prepared / "figure.svg")
        snapshots = self.snapshot(self.original), self.snapshot(self.prepared)
        reads = Counter()
        read_bytes = Path.read_bytes

        def counted(path):
            reads[path.resolve()] += 1
            return read_bytes(path)

        with patch("src.validation.render.subprocess.run", side_effect=self.fake_compiler), patch.object(Path, "read_bytes", counted):
            report = render_comparison(self.original, "paper.tex", self.prepared, self.output, self.config)
        self.assertEqual(report["status"], "rendered")
        self.assertEqual(self.snapshot(self.original), snapshots[0])
        self.assertEqual(self.snapshot(self.prepared), snapshots[1])
        for directory in (self.original, self.prepared):
            self.assertTrue(all(reads[p.resolve()] == 1 for p in directory.iterdir()))
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {"original.pdf", "prepared.pdf", "original.log", "prepared.log", "comparison.json"})
        self.assertTrue(report["temporary_inputs_removed"])
        self.assertEqual(report["original"]["inputs"]["svg_derivatives"], [])
        self.assertEqual(len(report["prepared"]["inputs"]["svg_derivatives"]), 1)
        self.assertEqual(report["comparison"]["assessment"], "observations_only")

    def test_failure_and_timeout_leave_logs_without_partial_pdf_or_inputs(self):
        self.pair()
        calls = 0

        def fail(command, **kwargs):
            nonlocal calls
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, b"test", b"")
            calls += 1
            if calls == 1:
                build = Path(command[command.index("--outdir") + 1])
                self.pdf(build / "paper.pdf")  # invalid evidence after an engine error
                kwargs["stdout"].write(b"REAL ENGINE ERROR\n")
                return subprocess.CompletedProcess(command, 1)
            raise subprocess.TimeoutExpired(command, 7)

        with patch("src.validation.render.subprocess.run", side_effect=fail):
            report = render_comparison(self.original, "paper.tex", self.prepared, self.output, self.config)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["original"]["status"], "failed")
        self.assertEqual(report["prepared"]["status"], "timeout")
        self.assertIn("REAL ENGINE ERROR", (self.output / "original.log").read_text())
        self.assertEqual({p.name for p in self.output.iterdir()}, {"original.log", "prepared.log", "comparison.json"})

    def test_staging_failure_does_not_block_the_other_side_or_leave_derivatives(self):
        self.pair()
        self.put(self.original / "bad.svg", "<broken>")
        with patch("src.validation.render.subprocess.run", side_effect=self.fake_compiler):
            report = render_comparison(self.original, "paper.tex", self.prepared, self.output, self.config)
        self.assertEqual(report["original"]["status"], "failed")
        self.assertEqual(report["prepared"]["status"], "rendered")
        self.assertFalse(any(p.is_dir() for p in self.output.iterdir()))

    def test_success_exit_without_a_readable_pdf_is_not_success(self):
        self.pair()

        def broken(command, **kwargs):
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, b"test", b"")
            entry = Path(command[-1])
            if entry.name == "master.tex":
                build = Path(command[command.index("--outdir") + 1])
                self.put(build / "master.pdf", b"%PDF-1.7\nCORRUPT")
            return subprocess.CompletedProcess(command, 0)

        with patch("src.validation.render.subprocess.run", side_effect=broken):
            report = render_comparison(self.original, "paper.tex", self.prepared, self.output, self.config)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["original"]["status"], "failed")
        self.assertEqual(report["prepared"]["status"], "failed")
        self.assertFalse(list(self.output.glob("*.pdf")))
        self.assertFalse(any(p.is_dir() for p in self.output.iterdir()))

    def test_vector_svg_stays_vector_and_bbox_describes_its_pdf(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect x="5" y="5" width="20" height="30" fill="red"/></svg>'
        target = self.root / "figure.svg"
        receipt = stage_svg(svg, target)
        self.assertEqual(target.stat().st_size, 0)
        with pymupdf.open(str(target) + ".pdf") as pdf:
            self.assertTrue(pdf[0].get_drawings())
            self.assertEqual(pdf[0].get_images(), [])
            self.assertEqual(pdf[0].rect.width, receipt["width_pt"])
            self.assertEqual(pdf[0].rect.height, receipt["height_pt"])
        self.assertIn("0 0 100.00000000 50.00000000", Path(str(target) + ".bb").read_text())

    def test_wrapped_png_retains_pixels_without_an_intermediate_png(self):
        png = self.root / "original.png"
        Image.new("RGB", (11, 7), (13, 127, 249)).save(png)
        source = self.root / "source.svg"
        raster_to_svg_wrapper(png, source)
        target = self.root / "staged" / "image.svg"
        stage_svg(source.read_bytes(), target)
        with pymupdf.open(str(target) + ".pdf") as pdf:
            xref = pdf[0].get_images()[0][0]
            pixmap = pymupdf.Pixmap(pdf, xref)
            with Image.open(png) as original:
                self.assertEqual(pixmap.samples, original.tobytes())
        self.assertEqual({p.suffix for p in target.parent.iterdir()}, {".svg", ".pdf", ".bb"})

    def test_external_svg_resources_and_derivative_collisions_are_explicit(self):
        target = self.root / "image.svg"
        with self.assertRaisesRegex(ValueError, "external resource"):
            stage_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><image href="elsewhere.png"/></svg>', target)
        self.pair()
        self.put(self.original / "image.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.put(self.original / "image.svg.pdf", b"SOURCE MUST SURVIVE")
        with self.assertRaisesRegex(ValueError, "collides"):
            stage_project(self.original, "paper.tex", self.root / "stage")
        self.assertEqual((self.original / "image.svg.pdf").read_bytes(), b"SOURCE MUST SURVIVE")

    def test_nested_main_keeps_jobname_bom_and_bbl_and_excludes_generated_output(self):
        raw = b"\xef\xbb\xbf" + br"\documentclass{article}"
        self.put(self.original / "nested/paper.tex", raw)
        self.put(self.original / "nested/paper.bbl", "ORIGINAL BIBLIOGRAPHY")
        self.put(self.original / "nested/paper.aux", "STALE")
        self.put(self.original / "extracted/master.tex", "CONTAMINATION")
        self.put(self.original / "manifest.json", "BOOKKEEPING")
        stage = self.root / "stage"
        report = stage_project(self.original, "nested/paper.tex", stage)
        self.assertEqual((stage / "nested/paper.tex").read_bytes(), b"\xef\xbb\xbf" + BOOTSTRAP + raw[3:])
        self.assertTrue((stage / "nested" / DRIVER_NAME).is_file())
        self.assertEqual({f["path"] for f in report["files"]}, {"nested/paper.tex", "nested/paper.bbl"})

    def test_new_output_cannot_overwrite_sources_or_reuse_a_stale_result(self):
        self.pair()
        with self.assertRaisesRegex(ValueError, "separate"):
            render_comparison(self.original, "paper.tex", self.prepared, self.prepared / "render", self.config)
        self.output.mkdir()
        self.put(self.output / "prepared.pdf", "STALE")
        with self.assertRaises(FileExistsError):
            render_comparison(self.original, "paper.tex", self.prepared, self.output, self.config)
        self.assertEqual((self.output / "prepared.pdf").read_text(), "STALE")
        with self.assertRaisesRegex(ValueError, "inventoried"):
            stage_project(self.original, "../prepared/master.tex", self.root / "stage")

    def test_temporary_font_configuration_is_shared_and_does_not_modify_parent_environment(self):
        self.pair()
        fonts = self.root / "fonts & extras"
        fonts.mkdir()
        config = RenderConfig(Path(sys.executable), timeout_seconds=7, font_dirs=(fonts,))
        parent_env = dict(os.environ)
        configs = []

        def compiler(command, **kwargs):
            path = Path(kwargs["env"]["FONTCONFIG_FILE"])
            xml = ET.fromstring(path.read_bytes())
            self.assertEqual(xml.find("dir").text, fonts.as_posix())
            configs.append(path)
            return self.fake_compiler(command, **kwargs)

        with patch("src.validation.render.subprocess.run", side_effect=compiler):
            report = render_comparison(self.original, "paper.tex", self.prepared, self.output, config)
        self.assertEqual(len(set(configs)), 1)
        self.assertFalse(configs[0].exists())
        self.assertEqual(dict(os.environ), parent_env)
        self.assertEqual(report["fonts"]["mode"], "temporary_config")

    def test_explicit_configuration_and_finite_timeouts_are_required(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "finite and positive"):
                RenderConfig(Path(sys.executable), timeout_seconds=timeout).validate()
        with self.assertRaisesRegex(ValueError, "not found"):
            RenderConfig(self.root / "missing.exe").validate()
        file = self.put(self.root / "fonts.conf", "<fontconfig/>")
        env, info = compiler_environment(RenderConfig(Path(sys.executable), fontconfig_file=file), self.root)
        self.assertEqual(Path(env["FONTCONFIG_FILE"]), file)
        self.assertEqual(info["mode"], "explicit_config")

    def test_pdf_comparison_reports_content_changes_without_certifying_equivalence(self):
        png = self.root / "plot.png"
        Image.new("RGB", (8, 5), "blue").save(png)
        self.pdf(self.root / "left.pdf", "alpha beta", png)
        self.pdf(self.root / "right.pdf", "alpha gamma", png)
        result = compare_pdfs(self.root / "left.pdf", self.root / "right.pdf")
        self.assertEqual(result["common_word_occurrences"], 1)
        self.assertEqual(result["matching_raster_image_occurrences"], 1)
        self.assertEqual(result["original_only_words"], [("beta", 1)])
        self.assertEqual(result["assessment"], "observations_only")

    @unittest.skipUnless(os.environ.get("PYTEXML_TEST_TECTONIC"), "explicit optional compiler not configured")
    def test_live_graphics_driver_preserves_scaling_clipping_rotation_and_nested_main(self):
        png = self.original / "nested/plot.png"
        png.parent.mkdir()
        Image.new("RGB", (80, 40), (10, 130, 240)).save(png)
        raster_to_svg_wrapper(png, self.prepared / "plot.SVG")
        document = r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
\includegraphics[width=30pt]{IMAGE}
\includegraphics[width=40pt,trim=1pt 2pt 3pt 4pt,clip]{IMAGE}
\includegraphics*[angle=90,width=40pt]{IMAGE}
\end{document}
"""
        self.put(self.original / "nested/paper.tex", document.replace("IMAGE", "plot.png"))
        self.put(self.prepared / "master.tex", document.replace("IMAGE", "plot.SVG"))
        fonts = os.environ.get("PYTEXML_TEST_FONT_DIR")
        config = RenderConfig(Path(os.environ["PYTEXML_TEST_TECTONIC"]),
                              font_dirs=(Path(fonts),) if fonts else ())
        report = render_comparison(self.original, "nested/paper.tex", self.prepared, self.output, config)
        logs = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in self.output.glob("*.log"))
        self.assertEqual(report["status"], "rendered", logs)
        self.assertEqual(report["comparison"]["matching_raster_image_occurrences"], 3)
        with pymupdf.open(self.output / "original.pdf") as left, pymupdf.open(self.output / "prepared.pdf") as right:
            self.assertEqual(len(left), 1)
            self.assertEqual(len(right), 1)
            for a, b in zip(left[0].get_image_info(), right[0].get_image_info(), strict=True):
                for original, prepared in zip(a["bbox"], b["bbox"], strict=True):
                    self.assertAlmostEqual(original, prepared, places=2)
        self.assertFalse(any(p.is_dir() for p in self.output.iterdir()))


if __name__ == "__main__":
    unittest.main()
