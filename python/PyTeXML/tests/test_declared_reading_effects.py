"""Source-backed layout summaries must preserve reading state without no-op shims."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import ReadingBoundary, SourceCommand, BoundMeaning, DeferredRegion
from src.reading.dispatcher import StructuralDispatcher
from src.reading.mouth_profiles import ProfileError
from src.reading.tex_reader import TexReader


class DeclaredEffectsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, text):
        resolver = BindingResolver(self.catalog)
        self.context = resolver.new_context()
        reader = TexReader(text, catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        return list(StructuralDispatcher(reader, self.context, resolver, preparation=True, source_commands=True))

    def test_integer_values_and_formatting_preserve_booleans(self):
        items = self.read("\\newif\\ifflag\\flagtrue\\widowpenalty=10000\n\\clubpenalty - - 10000\n"
                          r"\flushbottom\sloppy\ifflag A\else B\fi")
        self.assertFalse(any(isinstance(i, (ReadingBoundary, DeferredRegion)) for i in items))
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertEqual([i.metadata["value"] for i in items if isinstance(i, SourceCommand) and i.action == "integer_parameter_assignment"], [10000, 10000])

    def test_flushbottom_assigns_real_scoped_meanings(self):
        self.read(r"\makeatletter\def\@textbottom{BEFORE}{\flushbottom}\makeatother")
        self.assertIsNotNone(self.context.lookup_definition("@textbottom"))
        self.read(r"\flushbottom")
        from src.engine.primitive import PrimitiveMeaning
        self.assertIsInstance(self.context.lookup_meaning("@textbottom"), PrimitiveMeaning)
        self.assertEqual(self.context.lookup_meaning("@textbottom").operation, "execution.relax")

    def test_shadowing_and_computed_values_do_not_use_summary(self):
        items = self.read(r"\def\sloppy{\catcode`\%=12}\sloppy")
        self.assertTrue(any(isinstance(i, SourceCommand) and i.action == "setup_program" for i in items))
        self.assertEqual(self.context.catcodes["%"], 12)
        for text in (r"\def\tolerance{}\sloppy", r"\widowpenalty\computed", r"\clubpenalty2147483648 "):
            with self.subTest(text=text):
                self.assertTrue(any(isinstance(i, ReadingBoundary) for i in self.read(text)))

    def test_invalid_effect_contracts_are_rejected(self):
        reading = deepcopy(self.catalog.engine_bindings["core_latex"]["reading"])
        command = next(c for c in reading["commands"] if c.get("action") == "declared_effects")
        command["metadata"]["meaning_copies"]["bad"] = "unverified"
        with self.assertRaises(ProfileError):
            self.catalog._validate_reading(reading, Path("core_latex.yaml"))
        with self.assertRaises(ProfileError):
            self.catalog._validate_reading({"load_effects": {"status": "pure"}}, Path("geometry.yaml"))

    def test_geometry_binding_does_not_assert_load_purity(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\documentclass{article}\newif\ifflag\flagtrue"
                r"\usepackage[verbose=true,letterpaper]{geometry}\ifflag YES\else NO\fi", encoding="utf-8")
            text, manifest, _, _ = preprocess_paper(str(root))
            usage = next(p for p in manifest.packages_declared if p.name == "geometry")
            self.assertTrue(usage.binding_available)
            self.assertTrue(usage.binding_activated)
            requirement = next(r for r in manifest.requirements if r["reason"] == "package_load_effects")
            self.assertEqual(requirement["evidence"]["optional_inputs"][0]["name"], "geometry.cfg")
            self.assertIn("YES", text)
            self.assertIn("NO", text)


if __name__ == "__main__":
    unittest.main()
