"""Catalog reuse must not share document activation or mutable reading state."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.contracts import EffectiveReadingProfile, UnresolvedBindingResult, UnresolvedReason
from src.reading.character_rules import ProfileError
from reader_support import reload_catalog


class CatalogSharingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = BindingCatalog()

    def test_package_activation_belongs_to_each_document(self):
        first = BindingResolver(self.catalog)
        second = BindingResolver(self.catalog)
        first.load_package("fancyvrb")
        self.assertIsInstance(first.resolve_environment("Verbatim"), EffectiveReadingProfile)
        unresolved = second.resolve_environment("Verbatim")
        self.assertIsInstance(unresolved, UnresolvedBindingResult)
        self.assertEqual(unresolved.reason, UnresolvedReason.PACKAGE_NOT_LOADED)
        second.load_package("listings")
        self.assertEqual(first.active_packages, ["fancyvrb"])
        self.assertEqual(second.active_packages, ["listings"])

    def test_new_document_reuses_loaded_and_compiled_knowledge(self):
        with patch.object(Path, "open", side_effect=AssertionError("Unexpected I/O")), \
             patch.object(self.catalog, "_compile_literal", side_effect=AssertionError("Repeated literal compilation")), \
             patch("src.reading.character_rules.re.compile",
                   side_effect=AssertionError("Unexpected regex compilation")):
            resolver = BindingResolver(self.catalog)
            resolver.load_package("fancyvrb")
            context = resolver.new_context()
            context.apply_profile(resolver.resolve_command("makeatletter"))
            self.assertEqual(context.catcodes["@"], 11)
            with patch.object(self.catalog.mouth, "profile", side_effect=AssertionError("Repeated profile composition")):
                self.assertIsInstance(resolver.resolve_environment("Verbatim"), EffectiveReadingProfile)
                self.assertIsInstance(resolver.resolve_environment("Verbatim", {"commandchars": "![]"}), EffectiveReadingProfile)

    def test_context_and_resolved_metadata_do_not_mutate_shared_knowledge(self):
        declarations = deepcopy(self.catalog.engine_bindings)
        first = BindingResolver(self.catalog)
        second = BindingResolver(self.catalog)
        left, right = first.new_context(), second.new_context()
        left.apply_profile(first.resolve_command("makeatletter"))
        self.assertEqual(left.catcodes["@"], 11)
        self.assertEqual(right.catcodes["@"], 12)

        expected = second.resolve_environment("verbatim")
        changed = first.resolve_environment("verbatim")
        changed.grammar["allow_nesting"] = "changed by this document"
        changed.reader_parameters["endlinechar"] = -1
        observed = second.resolve_environment("verbatim")
        self.assertEqual(observed.grammar, expected.grammar)
        self.assertEqual(observed.reader_parameters, expected.reader_parameters)
        self.assertEqual(self.catalog.engine_bindings, declarations)

    def test_index_is_a_snapshot_and_returned_nested_options_are_private(self):
        first, second = BindingResolver(self.catalog), BindingResolver(self.catalog)
        first.load_package("listings")
        second.load_package("listings")
        expected = second.resolve_command("lstset")
        changed = first.resolve_command("lstset")
        changed.configuration["exclusive_keys"][0].append("mutated")
        self.catalog.package_bindings["listings"]["reading"]["commands"].clear()
        self.assertEqual(second.resolve_command("lstset"), expected)
        self.assertIsInstance(second.resolve_command("lstinline"), EffectiveReadingProfile)

    def test_default_profile_and_explicit_construct_profile_have_distinct_consumers(self):
        self.catalog.package_bindings["fancyvrb"]["reading"]["option_resolution"]["default_profile"] = "semi_verbatim_block"
        resolver = BindingResolver(reload_catalog(self, self.catalog))
        resolver.load_package("fancyvrb")
        block, inline = resolver.resolve_environment("Verbatim"), resolver.resolve_command("Verb")
        self.assertEqual(block.family, "semi_verbatim_block")
        self.assertEqual(inline.family, "inline_delimited")
        context = resolver.new_context()
        context.apply_profile(block)
        self.assertEqual(context.catcodes["\\"], 0)
        self.assertEqual(context.catcodes["%"], 12)

    def test_option_profile_layers_are_applied_without_resetting_base_demotions(self):
        reading = self.catalog.package_bindings["fancyvrb"]["reading"]
        reading["environments"][0]["lexical_mode"] = {"catcode_overrides": {"%": 14}}
        resolver = BindingResolver(reload_catalog(self, self.catalog))
        resolver.load_package("fancyvrb")
        for value, expected_percent in (("none", 14), ("![]", 12)):
            with self.subTest(value=value):
                profile = resolver.resolve_environment("Verbatim", {"commandchars": value})
                context = resolver.new_context()
                context.apply_profile(profile)
                self.assertEqual(context.catcodes["%"], expected_percent)
                self.assertEqual(context.catcodes["\\"], 12)
                self.assertEqual(context.catcodes["{"], 12)
                if value != "none":
                    self.assertEqual([context.catcodes[c] for c in "![]"], [0, 1, 2])
                    self.assertEqual(profile.family, "semi_verbatim_block")
        # A later occurrence must not inherit the earlier override.
        self.assertEqual(resolver.resolve_environment("Verbatim").family, "raw_block")

    def test_profile_selection_is_declared_and_disabled_effects_do_not_select(self):
        options = self.catalog.package_bindings["listings"]["reading"]["option_resolution"]
        options["reading_affecting_keys"]["mathescape"]["profile_override"] = "raw_block"
        resolver = BindingResolver(reload_catalog(self, self.catalog))
        resolver.load_package("listings")
        enabled = resolver.resolve_environment("lstlisting", {"mathescape": True})
        self.assertEqual(enabled.family, "raw_block")
        self.assertEqual(enabled.interpolations[0].mode, "math")
        for options in ({"mathescape": False}, {"escapechar": ""}, {"escapeinside": ""}):
            profile = resolver.resolve_environment("lstlisting", options)
            self.assertEqual(profile.family, "raw_block")
            self.assertEqual(profile.interpolations, ())

    def test_index_preserves_activation_section_precedence_and_nonconditional_shadowing(self):
        conditional = {"name": r"\iftrue", "role": "opener", "evaluation": "always_false"}
        self.catalog.package_bindings["first"] = {"reading": {"conditionals": [conditional]}}
        self.catalog.package_bindings["second"] = {"reading": {
            "command_overrides": [{"name": r"\iftrue", "family": "opaque"}],
            "conditionals": [{**conditional, "evaluation": "always_true"}]}}
        resolver = BindingResolver(reload_catalog(self, self.catalog))
        self.assertEqual(resolver.resolve_conditional("iftrue").evaluation, "always_true")
        resolver.load_package("first")
        self.assertEqual(resolver.resolve_conditional("iftrue").evaluation, "always_false")
        resolver.load_package("second")
        resolver.load_package("first")
        self.assertIsNone(resolver.resolve_conditional("iftrue"))
        # Context copies can restore activation directly; no stale resolver cache.
        resolver.active_packages = ["second", "first"]
        self.assertEqual(resolver.resolve_conditional("iftrue").evaluation, "always_false")

    def test_environment_override_and_group_category_indexes_keep_provider_precedence(self):
        env = deepcopy(self.catalog.engine_bindings["verbatim"]["reading"]["environments"][0])
        env["lexical_mode"] = {"catcode_overrides": {"@": 11}}
        group = next(deepcopy(s) for s in self.catalog.engine_bindings["core_latex"]["reading"]["grouping"]
                     if s.get("catcode") == 1)
        group["state_management"]["group_kind"] = "semi_simple"
        self.catalog.package_bindings["custom"] = {"reading": {
            "environment_overrides": [env],
            "environments": [{**env, "lexical_mode": {"catcode_overrides": {"@": 12}}}],
            "grouping": [group]}}
        resolver = BindingResolver(reload_catalog(self, self.catalog))
        self.assertEqual(resolver.resolve_group(1).state_management.group_kind, "simple")
        resolver.load_package("custom")
        self.assertEqual(resolver.resolve_group(1).state_management.group_kind, "semi_simple")
        context = resolver.new_context()
        context.apply_profile(resolver.resolve_environment(env["name"]))
        self.assertEqual(context.catcodes["@"], 11)

    def test_source_syntax_preserves_provider_and_same_provider_ambiguity(self):
        source = {"name": r"\dependency", "family": "source_command", "action": "opaque",
                  "grammar": {"handler": "source_arguments", "arguments": [{"name": "value", "kind": "braced"}]}}
        self.catalog.package_bindings["first"] = {"reading": {"commands": [source]}}
        resolver = BindingResolver(reload_catalog(self, self.catalog))
        self.assertEqual(resolver.source_command_syntax("dependency").binding_id, "packages/first")
        self.assertEqual(resolver.active_packages, [])
        self.assertEqual(resolver.resolve_command("dependency").reason, UnresolvedReason.PACKAGE_NOT_LOADED)
        for location in ("same_provider", "other_provider"):
            with self.subTest(location=location):
                catalog = deepcopy(self.catalog)
                if location == "same_provider":
                    catalog.package_bindings["first"]["reading"]["command_overrides"] = [source]
                else:
                    catalog.package_bindings["second"] = {"reading": {"commands": [source]}}
                ambiguous = BindingResolver(reload_catalog(self, catalog))
                self.assertIsNone(ambiguous.source_command_syntax("dependency"))
                ambiguous.load_package("first")
                self.assertIsNone(ambiguous.source_command_syntax("dependency"))
                self.assertIsInstance(ambiguous.resolve_command("dependency"), EffectiveReadingProfile)

    def test_malformed_literal_option_contracts_fail_at_catalog_load(self):
        mutations = (
            {"default_profile": "missing"}, {"default_profile": "latex_ascii"},
            {"unsupported_options_behavior": "ignore"}, {"unknown_control": True},
            {"reading_affecting_keys": {"x": {"effect": "misspelled"}}},
            {"reading_affecting_keys": {"x": {"effect": "dynamic_catcode_mutations"}}},
            {"reading_affecting_keys": {"x": {"effect": "enable_verbatim_comment", "profile_override": "missing"}}},
            {"reading_affecting_keys": {"x": {"effect": "enable_verbatim_comment", "profile_overide": "raw_block"}}},
            {"non_reading_options": ["commentchar"]},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                catalog = deepcopy(self.catalog)
                catalog.package_bindings["fancyvrb"]["reading"]["option_resolution"].update(mutation)
                with self.assertRaises(ProfileError):
                    reload_catalog(self, catalog)

    def test_factory_recipes_reject_unbound_arguments_and_invalid_name_templates(self):
        original = self.catalog.package_bindings["comment"]["reading"]
        for mutation in ("name_argument", "regex_pattern", "unknown_field"):
            reading = deepcopy(original)
            recipe = reading["factories"][0]["metadata"]
            if mutation == "name_argument":
                recipe[mutation] = "absent"
            elif mutation == "regex_pattern":
                recipe["terminator"][mutation] = r"{name}["
            else:
                recipe[mutation] = True
            with self.subTest(mutation=mutation), self.assertRaises(ProfileError):
                self.catalog._validate_reading(reading, Path("comment.yaml"))

    def test_citation_contract_requires_key_argument_and_boolean_wildcard_policy(self):
        for mutation in ("missing_keys", "wildcard_string"):
            reading = deepcopy(self.catalog.package_bindings["natbib"]["reading"])
            command = reading["commands"][0]
            if mutation == "missing_keys":
                command["grammar"]["arguments"] = []
            else:
                command["metadata"] = {"allow_wildcard": "false"}
            with self.subTest(mutation=mutation), self.assertRaises(ProfileError):
                self.catalog._validate_reading(reading, Path("natbib.yaml"))


if __name__ == "__main__":
    unittest.main()
