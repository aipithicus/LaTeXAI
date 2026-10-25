"""Source control flow, binding knowledge and payload delivery are independent."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from reader_support import reload_catalog
from src.bindings.resolver import BindingResolver
from src.reading.contracts import ConditionalRegion, ReadingBoundary, SourceCommand, StoredDefinition, SkippedRegion
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader, CatCode
from src.prepare.pipeline import preprocess_paper


class PredicateTests(unittest.TestCase):
    def scan(self, source, *, resolver=None):
        resolver = resolver or BindingResolver()
        context = resolver.new_context()
        reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
        dispatcher = StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True)
        items = list(dispatcher)
        return reader, dispatcher, items

    def decisions(self, items):
        return [i for i in items if isinstance(i, SourceCommand) and i.action == "conditional_test"]

    def test_literal_character_and_category_tests(self):
        for predicate, operands, truth in ((r"\if", "00", True), (r"\if", "01", False),
                (r"\ifcat", "ab", True), (r"\ifcat", "a0", False)):
            with self.subTest(predicate=predicate, operands=operands):
                reader, dispatcher, items = self.scan(predicate + " " + operands + r" THEN\else ELSE\fi AFTER")
                self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
                decision, = self.decisions(items)
                self.assertEqual(decision.metadata["truth"], truth)
                self.assertEqual(reader.source_slice(decision.span), predicate + " " + operands)
                skipped, = (i for i in items if isinstance(i, SkippedRegion))
                self.assertIn("ELSE" if truth else "THEN", reader.source_slice(skipped.span))
                self.assertEqual(dispatcher.units.records[skipped.unit_id].activity, "skipped")

    def test_captured_constant_chain_and_scoped_redefinition(self):
        source = (r"\newcommand{\blind}{0}\def\alias{\blind}"
                  r"{\renewcommand{\blind}{1}\if1\alias YES\else NO\fi}"
                  r"\if0\alias YES\else NO\fi\blind")
        reader, _, items = self.scan(source)
        decisions = self.decisions(items)
        self.assertEqual([d.metadata["truth"] for d in decisions], [True, True])
        definitions = {i.unit_id for i in items if isinstance(i, StoredDefinition)}
        self.assertTrue(all(set(d.metadata["definition_unit_ids"]) <= definitions for d in decisions))
        # Outside a predicate, the original invocation still awaits interpretation.
        self.assertTrue(any(getattr(i, "reason", None) == "stored_macro" for i in items))
        self.assertEqual([reader.source_slice(d.span) for d in decisions], [r"\if1\alias", r"\if0\alias"])

    def test_definition_time_categories_survive_catcode_changes(self):
        source = r"\catcode`\@=11 \def\saved{@}\catcode`\@=12 \ifcat\saved @ YES\else NO\fi"
        _, _, items = self.scan(source)
        self.assertEqual([d.metadata["truth"] for d in self.decisions(items)], [False])

    def test_unsupported_operands_restore_cursor_and_remain_unresolved(self):
        for definition, operand in ((r"\def\x#1{0}", r"\x"), (r"\def\x{01}", r"\x"),
                (r"\def\x{}", r"\x"), (r"\def\x{\y}\def\y{\x}", r"\x"),
                (r"\def\x z{0}", r"\x"), ("", r"\missing")):
            source = definition + r"\if0" + operand + r" THEN\else ELSE\fi AFTER"
            with self.subTest(source=source):
                reader, _, items = self.scan(source)
                self.assertFalse(self.decisions(items))
                region, = (i for i in items if isinstance(i, ConditionalRegion))
                self.assertEqual(reader.source_slice(region.span), source[len(definition):source.index(" AFTER")])
                self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_skipping_does_not_evaluate_or_expand_predicates(self):
        source = r"\iffalse\if\missing\other\fi\fi AFTER"
        _, _, items = self.scan(source)
        self.assertFalse(self.decisions(items))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_unexecuted_definition_invalidates_old_constant(self):
        source = r"\def\x{0}\if q\missing\def\x{1}\fi\if0\x YES\else NO\fi"
        _, _, items = self.scan(source)
        self.assertFalse(self.decisions(items))
        self.assertEqual(sum(isinstance(i, ConditionalRegion) for i in items), 2)

    def test_environment_local_definition_does_not_replace_callers_constant(self):
        source = r"\def\x{0}\begin{unbound}\def\x{1}\end{unbound}\if0\x YES\else NO\fi"
        _, _, items = self.scan(source)
        self.assertEqual([d.metadata["truth"] for d in self.decisions(items)], [True])
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))

    def test_deep_definition_chain_is_iterative_and_does_no_io(self):
        # Names use letters only, so every target is one control-sequence token.
        names = ["c" + chr(97 + i // 26) + chr(97 + i % 26) for i in range(600)]
        source = "".join("\\def\\" + a + "{\\" + b + "}" for a, b in zip(names, names[1:]))
        source += "\\def\\" + names[-1] + "{0}\\if0\\" + names[0] + r" YES\else NO\fi"
        resolver = BindingResolver()
        with patch.object(Path, "open", side_effect=AssertionError("Unexpected I/O")):
            _, _, items = self.scan(source, resolver=resolver)
        self.assertEqual([d.metadata["truth"] for d in self.decisions(items)], [True])
        self.assertEqual(len(self.decisions(items)[0].metadata["definition_unit_ids"]), 600)

    def test_yaml_selects_comparison_without_python_command_spelling(self):
        catalog = BindingCatalog()
        spec = next(s for s in catalog.engine_bindings["core_latex"]["reading"]["conditionals"] if s["name"] == r"\if")
        catalog.engine_bindings["core_latex"]["reading"]["conditionals"].append({**spec, "name": r"\samechar"})
        _, _, items = self.scan(r"\samechar aa YES\else NO\fi", resolver=BindingResolver(reload_catalog(self, catalog)))
        self.assertEqual([d.metadata["truth"] for d in self.decisions(items)], [True])

    def test_kernel_conditional_role_does_not_invent_its_truth(self):
        source = r"\makeatletter\if@twoside LEFT\else RIGHT\fi\makeatother AFTER"
        reader, _, items = self.scan(source)
        self.assertFalse(self.decisions(items))
        region, = (i for i in items if isinstance(i, ConditionalRegion))
        self.assertEqual(reader.source_slice(region.span), r"\if@twoside LEFT\else RIGHT\fi")
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))


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

    def test_known_nesting_in_local_code_allows_later_package_load(self):
        self.put("local.sty", r"\if@twoside\fancyhead{LEFT}\else\fancyhead{RIGHT}\fi\RequirePackage{natbib}")
        _, manifest, _, _ = self.prepare(r"\usepackage{local}\citep{a}")
        self.assertFalse(manifest.unresolved)
        self.assertTrue(next(p for p in manifest.packages_declared if p.name == "natbib").binding_activated)
        self.assertFalse(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))

    def test_local_bound_package_activates_knowledge_and_still_discovers_source_dependencies(self):
        self.put("natbib.sty", r"\RequirePackage{child}\DeclareOption{\computed}{\input{hidden}}")
        self.put("child.sty", "% known local dependency\n")
        _, manifest, output, _ = self.prepare(r"\usepackage{natbib}\citep{a}")
        usage = next(p for p in manifest.packages_declared if p.name == "natbib")
        self.assertTrue(usage.is_local and usage.binding_available and usage.binding_activated)
        self.assertTrue((output / "child.sty").is_file())
        self.assertFalse(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))
        self.assertTrue(any(r["reason"] == "retained_code_reading" for r in manifest.requirements))

    def test_selected_branch_with_overloaded_metadata_keeps_later_inputs(self):
        self.put("tail.tex", "TAIL")
        header = r"\author[1]{Name \input{not-executed}}"
        text, manifest, _, _ = self.prepare(r"\newcommand{\blind}{0}\if0\blind" + header + r"\fi\input{tail}")
        self.assertIn(header, text)
        self.assertIn("TAIL", text)
        self.assertFalse(manifest.unresolved)
        self.assertEqual([d["target"] for d in manifest.dependencies], ["tail.tex"])
        self.assertTrue(any(r["reason"] == "deferred_dependency" for r in manifest.requirements))
        self.assertTrue(manifest.conditional_decisions[0]["truth"])

    def test_source_constants_select_dependencies_without_expanding_output(self):
        self.put("yes.tex", "YES")
        self.put("after.tex", "AFTER")
        source = (r"\newcommand{\blind}{0}\if0\blind\input{yes}\else\input{absent}\fi"
                  r"\if1\blind\input{also-absent}\fi\input{after}")
        text, manifest, _, ledger = self.prepare(source)
        self.assertIn(r"\newcommand{\blind}{0}", text)
        self.assertIn(r"\if0\blind YES", text)
        self.assertNotIn("absent", text)
        self.assertIn("AFTER", text)
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual({d["target"] for d in manifest.dependencies}, {"yes.tex", "after.tex"})
        self.assertTrue(any(u["activity"] == "skipped" for u in manifest.units))
        self.assertEqual(ledger.master_length, len(text))
        self.assertEqual((self.root / "main.tex").read_text(), r"\documentclass{article}" + source)

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

    def test_inactive_resource_provider_keeps_materialization_undetermined(self):
        self.put("plot.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
        _, manifest, _, _ = self.prepare(r"\includegraphics{plot.svg}\usepackage{graphicx}")
        requirement = next(r for r in manifest.requirements if r["reason"] == "package_not_loaded")
        self.assertEqual(requirement["stage"], "binding")
        self.assertEqual(requirement["dependency"], "possible")
        self.assertEqual(requirement["materialization"], "undetermined")
        self.assertEqual(manifest.materialization_status, "complete")
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
