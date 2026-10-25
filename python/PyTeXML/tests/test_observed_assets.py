"""Deferred environments can expose asset headers without becoming executable."""
import base64
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.resolver import BindingResolver
from src.reading.contracts import DeferredRegion, ReadingBoundary, SourceCommand
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader
from src.prepare.pipeline import preprocess_paper
from src.assets import convert_asset_to_svg


class ObservedAssetTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def image(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (3, 2), "red").save(path)
        return path

    def prepare(self):
        return preprocess_paper(str(self.root), root_tex="main.tex")

    def test_image_in_one_float_does_not_hide_a_later_assetless_float(self):
        self.image("plot.png")
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}"
                 r"\begin{figure}\input{image}\end{figure}"
                 r"\begin{figure*}LATENT\end{figure*}")
        self.put("image.tex", r"\includegraphics{plot.png}")
        text, manifest, _, _ = self.prepare()
        self.assertIn(r"\includegraphics{plot.svg}", text)
        self.assertIn(r"\begin{figure*}LATENT\end{figure*}", text)
        self.assertEqual(manifest.implicit_graphics_count, 1)
        graphic, = manifest.implicit_graphics
        self.assertEqual(graphic.kind, "assetless_float")
        self.assertEqual(graphic.preview, r"\begin{figure*}")
        self.assertTrue(graphic.is_floating)

    def test_author_environment_assets_across_repeated_cached_inputs(self):
        declaration = (r"\newenvironment{suppfigure}{\refstepcounter{supfigure}"
                       r"\renewcommand\thefigure{\thesupfigure}\begin{figure}}{\end{figure}}")
        body = ("\\begin{suppfigure}[H]\n  % preserve this comment\n"
                r"\includegraphics[width=.75\linewidth]{LN.png}" "\n"
                r"\includegraphics*{MSEvsloss.png}" "\n\\end{suppfigure}\n")
        main = self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}" + declaration +
                        r"\input{figures}\input{figures}")
        child = self.put("figures.tex", body)
        originals = {name: self.image(name).read_bytes() for name in ("LN.png", "MSEvsloss.png")}
        reads = Counter()
        read_bytes = Path.read_bytes

        def read(path):
            reads[path.resolve()] += 1
            return read_bytes(path)

        with patch.object(Path, "read_bytes", read), patch(
                "src.prepare.assets.convert_asset_to_svg", wraps=convert_asset_to_svg) as convert:
            text, manifest, out, ledger = self.prepare()
        expected = body.replace("LN.png", "LN.svg").replace("MSEvsloss.png", "MSEvsloss.svg")
        self.assertEqual(text.count(expected.rstrip("\n")), 2)
        self.assertIn(declaration, text)
        self.assertEqual(convert.call_count, 2)
        self.assertEqual(manifest.active_images, [])
        self.assertEqual({i.rel_path for i in manifest.candidate_images}, set(originals))
        self.assertEqual([d["kind"] for d in manifest.dependencies], ["input", "input"])
        self.assertEqual(len(manifest.candidate_dependencies), 4)
        self.assertEqual({d["occurrence"] for d in manifest.candidate_dependencies}, {1, 2})
        self.assertTrue(all(d["status"] == "prepared" for d in manifest.candidate_dependencies))
        self.assertEqual(manifest.source_dependency_closure, "complete")
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.materialization_status, "complete")
        self.assertEqual(manifest.dependency_closure, "unresolved")
        self.assertEqual(reads[main], 1)
        self.assertEqual(reads[child], 1)
        self.assertEqual(child.read_text(), body)
        for name, original in originals.items():
            svg = out / Path(name).with_suffix(".svg")
            image = ET.fromstring(svg.read_text()).find("{http://www.w3.org/2000/svg}image")
            self.assertEqual(base64.b64decode(image.attrib["href"].split(",", 1)[1]), original)
            self.assertFalse((out / name).exists())
        self.assertEqual(ledger.master_length, len(text))
        previous = 0
        for segment in ledger.segments:
            a, b = segment["generated"]
            self.assertEqual(a, previous)
            previous = b
            if segment["operation"] == "REWRITE_IMAGE":
                self.assertEqual(segment["source_file"], "figures.tex")
                start, end = segment["source"]
                self.assertEqual(text[a:b], body[start:end].replace("LN.png", "LN.svg")
                                 .replace("MSEvsloss.png", "MSEvsloss.svg"))
        self.assertEqual(previous, len(text))

    def test_comments_literals_math_definitions_and_arguments_do_not_supply_images(self):
        protected = ("% \\includegraphics{comment.png}\n"
                     r"\verb|\end{custom}\includegraphics{verb.png}|"
                     r"\begin{verbatim}\includegraphics{literal.png}\end{custom}\end{verbatim}"
                     r"\def\later{\includegraphics{definition.png}}"
                     r"\ordinary{\includegraphics{argument.png}}"
                     r"\textbf{\includegraphics{known_argument.png}}"
                     r"$\end{custom}\includegraphics{math.png}$")
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}"
                 r"\iffalse\begin{custom}\includegraphics{skipped.png}\end{custom}\fi"
                 r"\begin{custom}" + protected + r"\includegraphics{real.png}\end{custom}\input{tail}")
        self.image("real.png")
        self.put("tail.tex", "TAIL")
        text, manifest, out, _ = self.prepare()
        self.assertIn(protected, text)
        self.assertIn("TAIL", text)
        self.assertNotIn("skipped.png", text)
        self.assertEqual([d["target"] for d in manifest.candidate_dependencies if d["status"] == "prepared"], ["real.png"])
        self.assertTrue(all(d.get("reason") == "missing_dependency"
                            for d in manifest.candidate_dependencies if d["status"] != "prepared"))
        self.assertEqual([p.name for p in out.glob("*.svg")], ["real.svg"])

    def test_missing_computed_ambiguous_and_unsupported_page_observations_stay_local(self):
        bad = (r"\includegraphics{missing.png}\includegraphics{\computed}"
               r"\includegraphics{ambiguous}\includegraphics[page=2]{real.png}")
        self.put("main.tex", r"\documentclass{article}\begin{custom}" + bad +
                 r"\includegraphics{real.png}\end{custom}\input{tail}")
        self.image("real.png")
        self.image("ambiguous.png")
        self.image("ambiguous.jpg")
        self.put("tail.tex", "TAIL")
        text, manifest, out, _ = self.prepare()
        self.assertIn(bad, text)
        self.assertIn(r"\includegraphics{real.svg}", text)
        self.assertIn("TAIL", text)
        candidates = manifest.candidate_dependencies
        self.assertEqual([c.get("reason") for c in candidates[:-1]],
                         ["missing_dependency", "computed_argument", "ambiguous_dependency", "asset_page"])
        self.assertEqual(candidates[-1]["status"], "prepared")
        self.assertEqual(manifest.unresolved, [])
        self.assertEqual([p.name for p in out.glob("*.svg")], ["real.svg"])

    def test_known_search_paths_and_shared_active_image_use_one_derivative(self):
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}\graphicspath{{figs/}}"
                 r"\includegraphics{real}\begin{custom}\includegraphics{real}\end{custom}")
        self.image("figs/real.png")
        with patch("src.prepare.assets.convert_asset_to_svg", wraps=convert_asset_to_svg) as convert:
            text, manifest, out, _ = self.prepare()
        self.assertEqual(convert.call_count, 1)
        self.assertEqual(text.count("{figs/real.svg}"), 2)
        self.assertEqual([i.rel_path for i in manifest.active_images], ["figs/real.png"])
        self.assertEqual(manifest.candidate_images, [])
        self.assertEqual(manifest.candidate_dependencies[0]["payload"], "figs/real.svg")
        self.assertTrue((out / "figs/real.svg").exists())

    def test_unexecuted_search_path_change_does_not_resolve_against_stale_paths(self):
        body = r"\begin{custom}\graphicspath{{other/}}\includegraphics{same.png}\end{custom}"
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}" + body)
        self.image("same.png")
        self.image("other/same.png")
        text, manifest, out, _ = self.prepare()
        self.assertIn(body, text)
        self.assertEqual(manifest.candidate_dependencies[0]["reason"], "asset_search_context")
        self.assertEqual(manifest.candidate_images, [])
        self.assertEqual(list(out.rglob("*.svg")), [])

    def test_shadowed_asset_command_is_not_resolved_with_old_grammar(self):
        body = r"\begin{custom}\def\includegraphics#1{ignored}\includegraphics{fake.png}\end{custom}"
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}" + body +
                 r"\includegraphics{real.png}")
        self.image("real.png")
        text, manifest, _, _ = self.prepare()
        self.assertIn(body, text)
        self.assertEqual(manifest.candidate_dependencies, [])
        # No definition from the unexecuted body leaked into the caller context.
        self.assertIn(r"\includegraphics{real.svg}", text)

    def test_rolled_back_input_does_not_publish_observed_assets(self):
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}\input{child}TAIL")
        self.put("child.tex", r"\begin{custom}\includegraphics{real.png}\end{custom}"
                 r"\catcode`\%=\computed")
        self.image("real.png")
        text, manifest, out, _ = self.prepare()
        self.assertIn(r"\input{child}TAIL", text)
        self.assertEqual(manifest.candidate_dependencies, [])
        self.assertEqual(manifest.candidate_images, [])
        self.assertEqual(list(out.glob("*.svg")), [])

    def test_reading_boundary_does_not_certify_an_unfinished_environment(self):
        body = r"\begin{custom}\includegraphics{real.png}\iffalse hidden\fi\end{custom}"
        self.put("main.tex", r"\documentclass{article}\usepackage{graphicx}" + body)
        self.image("real.png")
        text, manifest, out, _ = self.prepare()
        self.assertIn(body, text)
        self.assertEqual(manifest.unresolved[0]["reason"], "environment_reading")
        self.assertEqual(manifest.candidate_dependencies, [])
        self.assertEqual(list(out.glob("*.svg")), [])

    def test_dispatcher_observes_headers_without_activation_execution_or_known_coverage(self):
        source = r"\begin{custom}\includegraphics[width=.5\linewidth]{real.png}\end{custom}"
        resolver = BindingResolver()
        context = resolver.new_context()
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        items = list(StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True))
        self.assertFalse(any(isinstance(i, (SourceCommand, ReadingBoundary)) for i in items))
        region = next(i for i in items if isinstance(i, DeferredRegion))
        self.assertEqual(source[region.span.start:region.span.end], source)
        observed, = region.observations
        self.assertEqual(observed.command.value("target"), "real.png")
        self.assertEqual(observed.command.span.basis, reader.basis)
        self.assertEqual(resolver.active_packages, [])
        self.assertTrue(ReadingCoverage(reader.basis, items).unknown.covers(region.span))


if __name__ == "__main__":
    unittest.main()
