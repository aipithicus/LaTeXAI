"""Source control flow, binding knowledge and payload delivery are independent."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.contracts import ConditionalRegion, ReadingBoundary, SourceCommand, StoredDefinition, SkippedRegion
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader, CatCode
from src.prepare.pipeline import preprocess_paper


class ActivityPreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)


    def put(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8", newline="")
        return path


    def prepare(self, source):
        self.put("main.tex", r"\documentclass{article}" + source)
        return preprocess_paper(str(self.root), root_tex="main.tex")


    def test_nearest_style_recovery_keeps_caller_declarations_and_siblings(self):
        outer = r"\RequirePackage{middle}\RequirePackage{natbib}\input{outer-tail.tex}"
        middle = r"\RequirePackage{inner}\RequirePackage{graphicx}\input{middle-tail.tex}"
        inner = r"{\catcode\computed=12 \RequirePackage{never}"
        for name, text in (("outer.sty", outer), ("middle.sty", middle), ("inner.sty", inner),
                ("middle-tail.tex", "MIDDLE"), ("outer-tail.tex", "OUTER"), ("tail.tex", "TAIL")):
            self.put(name, text)
        text, manifest, output, _ = self.prepare(r"\usepackage{outer}\citep{a}\input{tail}")
        self.assertIn("TAIL", text)
        self.assertEqual([p.name for p in manifest.packages_declared],
                         ["article", "outer", "middle", "inner", "graphicx", "natbib"])
        self.assertEqual((output / "inner.sty").read_text(), inner)
        self.assertEqual((output / "outer.sty").read_text(), outer)
        self.assertTrue({"middle-tail.tex", "outer-tail.tex"} <= set(manifest.code_inputs))
        self.assertFalse(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))
        requirement, = (r for r in manifest.requirements if r["reason"] == "retained_code_reading")
        self.assertIn("'inner.sty'", requirement["detail"])
        self.assertEqual(requirement["materialization"], "prepared")
        self.assertEqual(manifest.materialization_status, "complete")
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertEqual(len(manifest.source_reads), len(set(manifest.source_reads)))


    def test_local_bound_package_activates_knowledge_and_still_discovers_source_dependencies(self):
        self.put("natbib.sty", r"\RequirePackage{child}\DeclareOption{\computed}{\input{hidden}}")
        self.put("child.sty", "% known local dependency\n")
        _, manifest, output, _ = self.prepare(r"\usepackage{natbib}\citep{a}")
        usage = next(p for p in manifest.packages_declared if p.name == "natbib")
        self.assertTrue(usage.is_local and usage.binding_available and usage.binding_activated)
        self.assertTrue((output / "child.sty").is_file())
        self.assertFalse(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))
        self.assertTrue(any(r["reason"] == "retained_code_reading" for r in manifest.requirements))


    def test_unknown_citation_provider_is_not_unfinished_payload_work(self):
        text, manifest, _, _ = self.prepare(r"\usepackage{notbound}\citep{a} AFTER")
        requirement, = (r for r in manifest.requirements if r["reason"] == "package_not_loaded")
        self.assertEqual(requirement["stage"], "binding")
        self.assertEqual(requirement["activity"], "reached")
        self.assertEqual(requirement["materialization"], "not_required")
        package = next(p for p in manifest.packages_declared if p.name == "notbound")
        self.assertEqual(package.activity, "reached")
        self.assertFalse(package.binding_available)
        self.assertFalse(package.binding_activated)
        self.assertEqual(manifest.materialization_status, "complete")
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.dependency_closure, "unresolved")
        self.assertIn(r"\citep{a}", text)


    def test_inactive_resource_provider_retains_pending_materialization(self):
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        _, manifest, _, _ = self.prepare(r"\includegraphics{plot.svg}\usepackage{graphicx}")
        requirement = next(r for r in manifest.requirements if r["reason"] == "package_not_loaded")
        self.assertEqual(requirement["stage"], "binding")
        self.assertEqual(requirement["materialization"], "pending")
        self.assertEqual(manifest.materialization_status, "pending")
        self.assertEqual(manifest.preparation_status, "partial")


    def test_prepared_candidate_asset_keeps_unknown_activity_not_pending_work(self):
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>')
        _, manifest, output, _ = self.prepare(
            r"\usepackage{graphicx}\begin{unbound}\includegraphics{plot.svg}\end{unbound}")
        requirement, = (r for r in manifest.requirements if r["reason"] == "observed_asset")
        self.assertEqual(requirement["activity"], "unresolved")
        self.assertEqual(requirement["materialization"], "prepared")
        self.assertEqual(requirement["stage"], "interpretation")
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.dependency_closure, "unresolved")
        self.assertEqual(manifest.active_images, [])
        self.assertEqual(len(manifest.candidate_images), 1)
        self.assertTrue((output / "plot.svg").is_file())


    def test_failed_asset_conversion_never_claims_completed_materialization(self):
        import json
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>')
        with patch("src.prepare.assets.convert_asset_to_svg", return_value=False), self.assertRaises(RuntimeError):
            self.prepare(r"\usepackage{graphicx}\includegraphics{plot.svg}")
        manifest = json.loads((self.root / "extracted/manifest.json").read_text())
        self.assertEqual(manifest["materialization_status"], "failed")
        self.assertIsNone(manifest["entrypoint"])



if __name__ == "__main__":
    unittest.main()
