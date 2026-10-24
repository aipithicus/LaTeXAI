"""Activity proofs, argument roles, and bounded source-visible load queries."""
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
from src.reading.contracts import ReadingBoundary, SourceCommand, SkippedRegion
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader
from src.reading.options import OptionScope
from src.reading.coverage import ReadingCoverage
from src.reading.loads import SourceLoadState
from src.reading.character_rules import ProfileError
from src.reading.units import UnitRegistry


class ActivityEvidenceTests(unittest.TestCase):
    def setUp(self):
        folder = PROJECT / "temp/tests"
        folder.mkdir(parents=True, exist_ok=True)
        scratch = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def put(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8", newline="")
        return path

    def prepare(self, source):
        self.put("main.tex", r"\documentclass{article}\makeatletter" + source)
        return preprocess_paper(str(self.root), root_tex="main.tex")

    def decisions(self, manifest):
        return [d for d in manifest.conditional_decisions if d["predicate"] == "loaded"]

    def assert_links(self, manifest):
        units = {u["id"]: u for u in manifest.units}
        for unit in units.values():
            for field in ("owner_unit_id", "decision_unit_id"):
                if identifier := unit["activity_evidence"].get(field):
                    self.assertIn(identifier, units)
            self.assertNotEqual(unit["location_status"], "unmapped", unit)
        for requirement in manifest.requirements:
            self.assertIn(requirement["unit_id"], units)
            self.assertIn("next_step", requirement)
        for decision in manifest.conditional_decisions:
            self.assertIn(decision["unit_id"], units)

    def test_class_query_selects_and_inlines_only_reached_input(self):
        self.put("yes.tex", "YES")
        source = r"\@ifclassloaded{article}{\input{yes}}{\input{absent}} TAIL"
        text, manifest, _, ledger = self.prepare(source)
        self.assertIn("YES", text)
        self.assertIn("TAIL", text)
        self.assertNotIn("absent", text)
        self.assertIn(r"\@ifclassloaded{article}{", text)
        self.assertEqual([d["truth"] for d in self.decisions(manifest)], [True])
        self.assertEqual([d["target"] for d in manifest.dependencies], ["yes.tex"])
        self.assertEqual(ledger.master_length, len(text))
        self.assert_links(manifest)
        self.assertEqual((self.root / "main.tex").read_text(), r"\documentclass{article}\makeatletter" + source)

    def test_package_queries_are_ordered_and_do_not_require_a_binding(self):
        text, manifest, _, _ = self.prepare(
            r"\@ifpackageloaded{unbound}{BAD}{BEFORE}\usepackage{unbound}"
            r"\@ifpackageloaded{unbound}{AFTER}{BAD}")
        self.assertEqual([d["truth"] for d in self.decisions(manifest)], [False, True])
        self.assertIn("BEFORE", text)
        self.assertIn("AFTER", text)
        self.assertNotIn("BAD", text)
        usage = next(p for p in manifest.packages_declared if p.name == "unbound")
        self.assertFalse(usage.binding_available)
        self.assertEqual(self.decisions(manifest)[1]["load_unit_ids"], [usage.unit_id])
        self.assert_links(manifest)

    def test_nested_branches_and_repeated_inputs_preserve_occurrences(self):
        self.put("child.tex", "CHILD")
        text, manifest, _, _ = self.prepare(
            r"\@ifclassloaded{article}{\@ifpackageloaded{missing}{BAD}{\input{child}}}{}"
            r"\@ifclassloaded{article}{\input{child}}{BAD}")
        self.assertEqual(text.count("CHILD"), 2)
        self.assertNotIn("BAD", text)
        self.assertEqual(len(manifest.source_reads), len(set(manifest.source_reads)))
        self.assertEqual(len([o for o in manifest.input_occurrences if o["source"] == "child.tex"]), 2)
        self.assert_links(manifest)

    def test_literal_and_boolean_conditional_units_link_to_their_decision(self):
        text, manifest, _, _ = self.prepare(
            r"\newif\ifflag\flagtrue\ifflag\def\x{0}\else BAD\fi"
            r"\if0\x YES\else BAD\fi")
        decisions = {d["unit_id"] for d in manifest.conditional_decisions}
        skipped = [u for u in manifest.units if u["activity"] == "skipped"]
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all(u["activity_evidence"]["decision_unit_id"] in decisions for u in skipped))
        definition = next(u for u in manifest.units if u["kind"] == "StoredDefinition")
        self.assertEqual(definition["activity_evidence"]["reason"], "selected_branch")
        self.assertNotIn("BAD", text)
        self.assert_links(manifest)

    def test_unread_style_makes_negative_query_unknown_but_preserves_positive_fact(self):
        self.put("broken.sty", r"\catcode\computed=12 \RequirePackage{hidden}")
        text, manifest, _, _ = self.prepare(r"\usepackage{broken}"
            r"\@ifpackageloaded{hidden}{LEFT}{RIGHT}\@ifclassloaded{article}{YES}{NO}")
        self.assertEqual([d["truth"] for d in self.decisions(manifest)], [None, True])
        self.assertTrue(self.decisions(manifest)[0]["uncertainty_unit_ids"])
        self.assertIn("LEFT", text)
        self.assertIn("RIGHT", text)
        self.assertNotIn("NO", text)
        self.assert_links(manifest)

    def test_possible_load_invalidates_absence_without_becoming_a_known_load(self):
        _, manifest, _, _ = self.prepare(r"\unknown{\RequirePackage{hidden}}"
            r"\@ifpackageloaded{hidden}{LEFT}{RIGHT}")
        self.assertEqual([d["truth"] for d in self.decisions(manifest)], [None])
        self.assertNotIn("hidden", [p.name for p in manifest.packages_declared])
        dependency, = [r for r in manifest.requirements if r["reason"] == "deferred_dependency"]
        self.assertEqual(dependency["dependency"], "possible")
        self.assertEqual(dependency["materialization"], "undetermined")
        self.assertEqual(dependency["next_step"], "argument_behavior")
        self.assertEqual(manifest.materialization_status, "complete")
        self.assertEqual(manifest.preparation_status, "partial")

    def test_diagnostic_arguments_do_not_create_dependency_obligations(self):
        source = r"\PackageError{test}{Message}{Remove \protect\usepackage{natbib} and \input{absent}} TAIL"
        text, manifest, _, _ = self.prepare(source)
        self.assertIn(source.removesuffix(" TAIL"), text)
        self.assertFalse(any(r["reason"] == "deferred_dependency" for r in manifest.requirements))
        self.assertFalse(manifest.dependencies)
        arguments = [u for u in manifest.units if u["activity_evidence"].get("argument_role") == "diagnostic"]
        self.assertEqual(len(arguments), 3)
        self.assertTrue(all(u["activity"] == "data" for u in arguments))
        self.assert_links(manifest)

    def test_diagnostic_roles_also_apply_inside_unknown_branches(self):
        self.put("broken.sty", r"\catcode\computed=12")
        _, manifest, _, _ = self.prepare(r"\usepackage{broken}\@ifclassloaded{unknown}"
            r"{\PackageError{test}{Message}{Remove \protect\usepackage{natbib}}}{\input{possible}}")
        dependencies = [r for r in manifest.requirements if r["reason"] == "deferred_dependency"]
        self.assertEqual(len(dependencies), 1)
        self.assertEqual(dependencies[0]["next_step"], "branch_selection")
        self.assertEqual(dependencies[0]["dependency"], "possible")
        self.assertEqual(dependencies[0]["materialization"], "undetermined")

    def test_diagnostic_roles_apply_to_observations_inside_native_unknown_conditionals(self):
        _, manifest, _, _ = self.prepare(r"\ifx\unknown\other"
            r"\PackageError{test}{Message}{Remove \protect\usepackage{natbib}}\fi TAIL")
        self.assertFalse(any(r["reason"] == "deferred_dependency" for r in manifest.requirements))

    def test_redefined_diagnostic_does_not_keep_the_old_argument_contract(self):
        _, manifest, _, _ = self.prepare(r"\def\PackageError#1#2#3{#3}"
            r"\PackageError{test}{Message}{\input{possible}}")
        self.assertTrue(any(r["reason"] == "deferred_dependency" for r in manifest.requirements))

    def test_stored_dependency_is_linked_and_waits_for_macro_invocation(self):
        _, manifest, _, _ = self.prepare(r"\def\later{\input{absent}\RequirePackage{future}}"
            r"\@ifpackageloaded{future}{BAD}{GOOD}")
        dependencies = [r for r in manifest.requirements if r["reason"] == "deferred_dependency"]
        self.assertEqual(len(dependencies), 2)
        self.assertTrue(all(r["activity"] == "stored" and r["stage"] == "interpretation" for r in dependencies))
        self.assertTrue(all(r["next_step"] == "macro_invocation" for r in dependencies))
        self.assertEqual(self.decisions(manifest)[0]["truth"], False)
        self.assertEqual(manifest.preparation_status, "complete")
        self.assert_links(manifest)

    def test_selected_argument_tokens_keep_capture_time_catcodes(self):
        _, manifest, _, _ = self.prepare(r"\@ifclassloaded{article}{\catcode`\@=12 \def\foo@bar{OK}}{} TAIL")
        self.assertFalse(manifest.unresolved)
        definitions = [u for u in manifest.units if u["kind"] == "StoredDefinition"]
        self.assertEqual(len(definitions), 1)
        self.assert_links(manifest)

    def test_option_ampersand_is_data_without_changing_the_mouth(self):
        self.put("local.sty", r"\newif\ifflag\DeclareOption{sort&compress}{\flagtrue}\ProcessOptions")
        text, manifest, output, _ = self.prepare(r"\usepackage[sort&compress]{local}\ifflag YES\else NO\fi")
        self.assertFalse(manifest.unresolved)
        self.assertIn("YES", text)
        self.assertNotIn("NO", text)
        self.assertIn("sort&compress", (output / "local.sty").read_text())

    def test_computed_query_retains_both_branches_and_later_input(self):
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare(r"\@ifclassloaded{\computed}{LEFT}{RIGHT}\input{tail}")
        self.assertEqual(self.decisions(manifest)[0]["truth"], None)
        self.assertIn("LEFT", text)
        self.assertIn("RIGHT", text)
        self.assertIn("TAIL", text)

    def test_recovery_inside_selected_branch_preserves_following_caller(self):
        self.put("broken.sty", r"\catcode\computed=12")
        self.put("tail.tex", "TAIL")
        text, manifest, _, _ = self.prepare(r"\@ifclassloaded{article}{\usepackage{broken}\input{tail}}{BAD} AFTER")
        self.assertIn("TAIL", text)
        self.assertIn("AFTER", text)
        self.assertNotIn("BAD", text)
        self.assertEqual(manifest.preparation_status, "partial")
        self.assert_links(manifest)

    def test_endinput_in_captured_tokens_is_a_located_boundary_not_a_crash(self):
        source = r"\@ifclassloaded{article}{\endinput}{} AFTER"
        text, manifest, _, _ = self.prepare(source)
        self.assertIn("AFTER", text)
        self.assertTrue(any(r["reason"] == "token_input_boundary" for r in manifest.unresolved))


class DeclarativeActivityTests(unittest.TestCase):
    def test_alias_selects_existing_branch_handler_without_python_spelling(self):
        catalog = BindingCatalog()
        spec = next(s for s in catalog.engine_bindings["core_latex"]["reading"]["commands"] if s["name"] == r"\@ifclassloaded")
        catalog.engine_bindings["core_latex"]["reading"]["commands"].append({**deepcopy(spec), "name": r"\isclass"})
        resolver = BindingResolver(catalog)
        context = resolver.new_context()
        reader = TexReader(r"\isclass{article}{YES}{NO}", catcodes=context.catcodes, endline_char=context.endlinechar)
        loads = SourceLoadState()
        units = UnitRegistry()
        fact = units.add(reader.basis.span(0, 0), "test_load", activity="reached")
        loads.record("class", "article", fact)
        dispatcher = StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True, loads=loads, units=units)
        items = list(dispatcher)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items))
        self.assertEqual(dispatcher.decisions[0]["truth"], True)
        ReadingCoverage(reader.basis, items)
        self.assertTrue(any(isinstance(i, SkippedRegion) for i in items))

    def test_argument_roles_and_literal_sets_reject_unhandled_recipes(self):
        catalog = BindingCatalog()
        base = {"commands": [{"name": r"\sample", "family": "source_command", "action": "opaque",
            "grammar": {"handler": "source_arguments", "arguments": [{"name": "body", "kind": "braced"}]}}]}
        for fields in ({"role": "execute_python"}, {"role": []}, {"literal_categories": [13]},
                       {"literal_categories": [4, 4]}, {"literal_categories": [True]},
                       {"literal_categories": "letters"}, {"literal_categories": []}, {"unused": 1}):
            reading = deepcopy(base)
            reading["commands"][0]["grammar"]["arguments"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ProfileError):
                catalog._validate_reading(reading, Path("example.yaml"))

    def test_load_query_rejects_missing_roles_and_unknown_predicates(self):
        catalog = BindingCatalog()
        spec = next(s for s in catalog.engine_bindings["core_latex"]["reading"]["commands"] if s["name"] == r"\@ifclassloaded")
        for mutation in ("role", "predicate", "kind"):
            invalid = deepcopy(spec)
            if mutation == "role":
                invalid["grammar"]["arguments"][1]["role"] = "unknown"
            else:
                invalid["metadata"][mutation] = "unknown"
            with self.subTest(mutation=mutation), self.assertRaises(ProfileError):
                catalog._validate_reading({"commands": [invalid]}, Path("example.yaml"))


if __name__ == "__main__":
    unittest.main()
