"""Complete write bounds, scope, call-time closure and conservative fallbacks."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from reader_support import reload_catalog
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import ConditionalRegion, DeferredRegion, ReadingBoundary, SourceCommand, UncertainMeaning
from src.reading.dispatcher import StructuralDispatcher
from src.reading.effect_summary import EffectSummary, NameSet
from src.reading.effects import definition_summary
from src.reading.mouth_profiles import ProfileError
from src.reading.options import OptionScope
from src.reading.tex_reader import TexReader


class EffectSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, text, catalog=None):
        self.resolver = BindingResolver(catalog or self.catalog)
        self.context = self.resolver.new_context()
        reader = TexReader(text, source_id="test.tex", occurrence_id=1,
                           catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(reader, self.context, self.resolver, preparation=True, source_commands=True)
        items = list(self.dispatcher)
        spans = [i.remainder if isinstance(i, ReadingBoundary) else i.span for i in items]
        self.assertEqual("".join(text[s.start:s.end] for s in spans), text)
        return items

    def contract(self, summary):
        catalog = deepcopy(self.catalog)
        catalog.engine_bindings["core_latex"]["reading"]["commands"].append({
            "name": r"\touch", "family": "source_command", "action": "summarized_effects",
            "grammar": {"handler": "source_arguments", "arguments": []},
            "metadata": {"source_reference": "test: explicit effect fixture", "requires_unshadowed": [],
                         "effect_summary": summary.record()}})
        return reload_catalog(self, catalog)

    def prepare(self, text, catalog=None):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "main.tex").write_text(text, encoding="utf-8")
        with patch("src.prepare.session.BindingResolver", side_effect=lambda _, **kw: BindingResolver(catalog or self.catalog, **kw)):
            return preprocess_paper(str(root))

    def test_pure_and_layout_bodies_preserve_unrelated_boolean_without_expanding(self):
        text = r"\newif\ifflag\flagtrue\def\paint{\widowpenalty=10000 \sloppy}\paint\ifflag YES\else NO\fi"
        items = self.read(text)
        region = next(i for i in items if isinstance(i, DeferredRegion) and i.reason == "stored_macro")
        self.assertTrue(region.effect_summary.selective)
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertFalse(any(isinstance(i, ConditionalRegion) for i in items))
        master, manifest, _, _ = self.prepare(r"\documentclass{article}" + text)
        self.assertIn(r"\paint", master)
        self.assertNotIn("NO", master)
        record = next(r for r in manifest.requirements if r["reason"] == "stored_macro")
        self.assertTrue(record["effect_summary"]["complete"])
        self.assertEqual(record["location_status"], "mapped")

    def test_bounded_boolean_setter_executes_without_invalidating_other_meanings(self):
        prefix = r"\newif\ifflag\newif\ifother\def\set{\flagtrue}\set"
        self.read(prefix)
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertTrue(self.context.lookup_meaning("ifflag").truth)
        self.assertIsNone(self.context.lookup_meaning("ifother").uncertain)
        self.assertFalse(any(isinstance(i, ConditionalRegion) for i in self.read(prefix + r"\ifflag YES\else NO\fi")))

    def test_literal_assignments_and_stored_definitions_bound_targets(self):
        self.read(r"\newif\ifflag\def\set{\def\unrelated{\unknown}\let\another\unknown}")
        effect = definition_summary(self.context.lookup_definition("set"), self.context, self.resolver)
        self.assertEqual(set(effect.meanings.names), {"unrelated", "another"})
        self.dispatcher.defer_effects(self.context.lookup_definition("set").span, summary=effect)
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertIsInstance(self.context.lookup_meaning("another"), UncertainMeaning)

    def test_local_global_and_unknown_scope_restore_correctly(self):
        for scope in ("local", "global", "unknown"):
            with self.subTest(scope=scope):
                catalog = self.contract(EffectSummary(scope=scope, meanings=NameSet(("ifflag",))))
                self.read(r"\newif\ifflag{\touch}", catalog)
                self.assertEqual(self.context.lookup_meaning("ifflag").uncertain is None, scope == "local")

    def test_namespace_barrier_does_not_match_other_names_and_restores(self):
        catalog = self.contract(EffectSummary(meanings=NameSet(prefixes=("pkg@",))))
        self.read(r"\newif\ifflag\touch", catalog)
        self.assertIsInstance(self.context.lookup_meaning("pkg@unseen"), UncertainMeaning)
        self.assertIsNone(self.context.lookup_meaning("pkgOther"))
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        copied = self.context.copy()
        self.context.push_scope()
        self.context.record_meaning("pkg@unseen", self.context.lookup_meaning("ifflag"))
        self.context.pop_scope()
        self.assertIsInstance(self.context.lookup_meaning("pkg@unseen"), UncertainMeaning)
        self.context.restore_from(copied)
        self.assertIsInstance(self.context.lookup_meaning("pkg@unseen"), UncertainMeaning)
        self.read(r"{\touch}", catalog)
        self.assertIsNone(self.context.lookup_meaning("pkg@unseen"))

    def test_explicit_write_shadows_catalog_fallback(self):
        catalog = self.contract(EffectSummary(meanings=NameSet(("input",))))
        items = self.read(r"\touch\input{hidden}", catalog)
        self.assertIsInstance(items[-1], ReadingBoundary)
        self.assertEqual(items[-1].reason, "uncertain_meaning")

    def test_options_are_independent_of_meaning_writes(self):
        self.read(r"\newif\ifflag")
        span = self.context.lookup_meaning("ifflag").span
        self.dispatcher.options = OptionScope("pkg")
        self.dispatcher.defer_effects(span, summary=EffectSummary(meanings=NameSet(("unrelated",))))
        self.assertIsNone(self.dispatcher.options.uncertain)
        self.dispatcher.defer_effects(span, summary=EffectSummary(options=NameSet(("pkg",))))
        self.assertEqual(self.dispatcher.options.uncertain, span)

    def test_repeated_write_does_not_remint_an_unchanged_uncertainty_cause(self):
        for names in (NameSet(("input",)), NameSet(prefixes=("pkg@",))):
            with self.subTest(names=names):
                self.read(r"\touch\touch", self.contract(EffectSummary(meanings=names)))
                self.assertEqual(len(self.dispatcher.units.uncertainty), 1)

    def test_retained_namespace_writes_disable_old_dependency_grammar(self):
        from src.reading.observer import observe_source
        from src.reading.contracts import SourceCommand
        catalog = self.contract(EffectSummary(meanings=NameSet(prefixes=("inp",))))
        items = self.read(r"\begin{unknown}\touch\input{decoy}\end{unknown}", catalog)
        region = next(i for i in items if isinstance(i, DeferredRegion))
        self.assertFalse(any(o.command and o.command.action == "source_input"
                             for o in region.observations))
        reader = TexReader(r"\touch\input{decoy}", catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        observations = list(observe_source(reader, self.context, self.resolver))
        self.assertFalse(any(isinstance(i, SourceCommand) and i.action == "source_input" for i in observations))

    def test_global_prefix_barrier_survives_local_restoration(self):
        catalog = self.contract(EffectSummary(scope="global", meanings=NameSet(prefixes=("pkg@",))))
        self.read(r"{\touch}", catalog)
        self.assertIsInstance(self.context.lookup_meaning("pkg@later"), UncertainMeaning)

    def test_unbounded_effect_surfaces_fall_back(self):
        for summary in (EffectSummary.unknown("computed target"), EffectSummary(catcodes=(37,)),
                        EffectSummary(hooks=("begindocument",)), EffectSummary(reader_parameters=("endlinechar",))):
            with self.subTest(summary=summary):
                self.read(r"\newif\ifflag\touch", self.contract(summary))
                self.assertIsNotNone(self.context.lookup_meaning("ifflag").uncertain)

    def test_text_emission_is_not_assumed_free_of_mode_hooks(self):
        items = self.read(r"\newif\ifflag\def\text{hello}\text")
        summary = next(i.effect_summary for i in items if isinstance(i, DeferredRegion))
        self.assertFalse(summary.complete)
        self.assertIn("hook", summary.unresolved[0])
        self.assertIsNotNone(self.context.lookup_meaning("ifflag").uncertain)

    def test_computed_targets_parameters_cycles_and_unknown_calls_remain_unknown(self):
        bodies = (r"\csname target\endcsname", r"\unknown", r"\set", r"\let\csname name\endcsname\relax")
        for body in bodies:
            with self.subTest(body=body):
                items = self.read(r"\newif\ifflag\def\set{" + body + r"}\set")
                self.assertFalse(next(i.effect_summary for i in items if isinstance(i, DeferredRegion)).complete)
                self.assertIsNotNone(self.context.lookup_meaning("ifflag").uncertain)
        items = self.read(r"\newif\ifflag\def\set#1{#1}\set{X}")
        self.assertFalse(next(i.effect_summary for i in items if isinstance(i, DeferredRegion)).complete)

    def test_transitive_reads_after_writes_cannot_use_old_meanings(self):
        items = self.read(r"\newif\ifflag\def\helper{}\def\wrapper{\helper}"
                          r"\def\set{\let\helper\unknown\wrapper}\set")
        self.assertFalse(next(i.effect_summary for i in items if isinstance(i, DeferredRegion)).complete)

    def test_call_time_meanings_are_not_cached_on_definition(self):
        items = self.read(r"\def\helper{}\def\set{\helper}\set\def\helper{\unknown}\set")
        summaries = [i.effect_summary for i in items if isinstance(i, DeferredRegion)]
        self.assertEqual([s.complete for s in summaries], [False])
        self.assertEqual(len([i for i in items if isinstance(i, SourceCommand) and i.action == "setup_program"]), 1)

    def test_acyclic_repeated_call_graph_has_a_total_work_bound(self):
        names = ["macro" + "a" * n for n in range(30)]
        source = "".join("\\def\\" + name + "{\\" + names[i + 1] + "\\" + names[i + 1] + "}"
                         for i, name in enumerate(names[:-1]))
        source += "\\def\\" + names[-1] + "{\\relax}\\" + names[0]
        items = self.read(source)
        summary = next(i.effect_summary for i in items if isinstance(i, DeferredRegion))
        self.assertFalse(summary.complete)
        self.assertIn("budget", summary.unresolved[0])

    def test_following_groups_are_not_swallowed_by_argument_free_summary(self):
        items = self.read(r"\newif\ifflag\def\empty{}\empty{\flagtrue}\ifflag NO\else YES\fi")
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertFalse(any(isinstance(i, ConditionalRegion) for i in items))

    def test_complete_package_summary_and_repeat_load_preserve_unrelated_state(self):
        catalog = deepcopy(self.catalog)
        effects = catalog.package_bindings["geometry"]["reading"]["load_effects"]
        effects["optional_inputs"] = []
        effects["summary"] = EffectSummary(meanings=NameSet(prefixes=("Gm@", "ifGm@"))).record()
        catalog = reload_catalog(self, catalog)
        text = r"\documentclass{article}\newif\ifflag\flagtrue\usepackage{geometry}\usepackage{geometry}\ifflag YES\else NO\fi"
        master, manifest, _, _ = self.prepare(text, catalog)
        self.assertNotIn("NO", master)
        self.assertEqual(len([r for r in manifest.requirements if r["reason"] == "package_load_effects"]), 1)
        # A fixture's complete declaration cannot override unknown config input.
        catalog = deepcopy(catalog)
        catalog.package_bindings["geometry"]["reading"]["load_effects"]["optional_inputs"] = ["geometry.cfg"]
        master, manifest, _, _ = self.prepare(text, reload_catalog(self, catalog))
        self.assertIn("NO", master)
        record = next(r for r in manifest.requirements if r["reason"] == "package_load_effects")
        self.assertFalse(record["effect_summary"]["complete"])

    def test_validation_rejects_typos_incomplete_claims_and_empty_prefixes(self):
        for summary in ({"complete": True, "scope": "local", "writes": {"meaning": []}},
                        {"complete": True, "scope": "local", "writes": {}, "unresolved": ["callee"]},
                        {"complete": True, "scope": "local", "writes": {"meanings": {"prefixes": [""]}}}):
            with self.subTest(summary=summary), self.assertRaises(ProfileError):
                self.catalog._validate_effect_summary(summary, Path("example.yaml"))


if __name__ == "__main__":
    unittest.main()
