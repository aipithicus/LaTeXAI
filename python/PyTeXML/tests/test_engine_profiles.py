"""Native vocabulary, selected environment and mutable meanings stay separate."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.engine.catalog import CORE_OPERATIONS
from src.engine.profiles import COMMON_PRIMITIVES, EXTENSIONS, EngineProfile
from src.engine.primitive import PrimitiveMeaning
from src.reading.contracts import ReadingBoundary, UndefinedMeaning, UnresolvedBindingResult
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader, TokenKind
from src.prepare.pipeline import preprocess_paper


class EngineProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def test_default_is_etex_and_pdftex_explicitly_exposes_output(self):
        default = BindingResolver(self.catalog).new_context()
        alternate = BindingResolver(self.catalog, engine_profile="pdftex").new_context()
        self.assertEqual(default.engine_profile.name, "etex")
        self.assertEqual(alternate.engine_profile.lookup("pdfoutput").operand, "pdfoutput")
        self.assertIsInstance(default.engine_profile.lookup("pdfoutput"), UndefinedMeaning)
        self.assertIsNone(alternate.engine_profile.lookup("arbitrary_unknown"))
        self.assertIsInstance(alternate.engine_profile.lookup("expanded"), PrimitiveMeaning)

    def test_native_vocabulary_has_operations_and_no_yaml_authority(self):
        resolver = BindingResolver(self.catalog, engine_profile="pdftex")
        context = resolver.new_context()
        for name, meaning in dict(COMMON_PRIMITIVES, **EXTENSIONS).items():
            with self.subTest(name=name):
                self.assertIn(meaning.operation, CORE_OPERATIONS)
                self.assertIsInstance(resolver.resolve_command(name), UnresolvedBindingResult)
                self.assertEqual(context.resolve_meaning(resolver, name), meaning)
        with self.assertRaises(TypeError):
            COMMON_PRIMITIVES["def"] = None
        with self.assertRaises(FrozenInstanceError):
            context.engine_profile.name = "other"

    def test_explicit_writes_and_scope_restoration_override_selected_environment(self):
        resolver = BindingResolver(self.catalog, engine_profile="etex")
        context = resolver.new_context()
        context.push_scope()
        context.record_meaning("pdfoutput", COMMON_PRIMITIVES["relax"])
        self.assertEqual(context.resolve_meaning(resolver, "pdfoutput"), COMMON_PRIMITIVES["relax"])
        context.pop_scope()
        self.assertIsInstance(context.resolve_meaning(resolver, "pdfoutput"), UndefinedMeaning)
        self.assertIsNone(context.resolve_meaning(resolver, "def", TokenKind.ACTIVE_CHARACTER))
        self.assertEqual(context.copy().engine_profile, context.engine_profile)
        with self.assertRaises(ValueError):
            context.restore_from(BindingResolver(self.catalog, engine_profile="pdftex").new_context())

    def test_custom_profile_rejects_contradictory_or_unknown_extensions(self):
        with self.assertRaises(ValueError):
            EngineProfile("bad", frozenset({"invented"}))
        with self.assertRaises(ValueError):
            EngineProfile("bad", absent=frozenset({"def"}))
        with self.assertRaises(ValueError):
            EngineProfile("bad", frozenset({"pdfoutput"}), frozenset({"pdfoutput"}))
        custom = EngineProfile("custom", frozenset({"pdfoutput"}), frozenset({"myAbsent"}))
        context = BindingResolver(self.catalog, engine_profile=custom).new_context()
        self.assertIsInstance(context.engine_profile.lookup("myAbsent"), UndefinedMeaning)

    def test_edef_preserves_unexpandable_def_and_let_tokens(self):
        resolver = BindingResolver(self.catalog)
        context = resolver.new_context()
        reader = TexReader(r"\edef\saved{\def\let}", catcodes=context.catcodes, endline_char=context.endlinechar)
        items = list(StructuralDispatcher(reader, context, resolver))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items), items)
        self.assertEqual([t.value for t in context.lookup_definition("saved").replacement_tokens], ["def", "let"])

    def test_profile_reaches_preparation_manifest_and_independent_source_survey(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\pdfoutput=1 \documentclass{article}TEXT", encoding="utf-8")
            text, manifest, _, _ = preprocess_paper(str(root), root_tex="main.tex", engine_profile="etex")
            self.assertIn(r"\pdfoutput=1", text)
            self.assertEqual(manifest.engine_profile["name"], "etex")
            self.assertEqual(manifest.unresolved, [])
            self.assertEqual(manifest.source_survey[0]["boundaries"], [])

    def test_foreign_setup_is_captured_without_creating_a_parameter_or_meaning(self):
        resolver = BindingResolver(self.catalog)
        context = resolver.new_context()
        reader = TexReader(r"\pdfoutput=1 ", catcodes=context.catcodes, endline_char=context.endlinechar)
        items = list(StructuralDispatcher(reader, context, resolver, preparation=True))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
        self.assertIsNone(context.lookup_meaning("pdfoutput"))
        self.assertIsInstance(context.resolve_meaning(resolver, "pdfoutput"), UndefinedMeaning)
        command, = (i for i in items if getattr(i, "action", None) == "external_engine_setup")
        self.assertFalse(command.metadata["executed"])


if __name__ == "__main__":
    unittest.main()
