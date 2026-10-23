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
             patch("src.reading.character_rules.re.compile",
                   side_effect=AssertionError("Unexpected regex compilation")):
            resolver = BindingResolver(self.catalog)
            resolver.load_package("fancyvrb")
            context = resolver.new_context()
            context.apply_profile(resolver.resolve_command("makeatletter"))
            self.assertEqual(context.catcodes["@"], 11)
            self.assertIsInstance(resolver.resolve_environment("Verbatim"), EffectiveReadingProfile)

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
