"""Resource ownership and loader failures at the shared/preparation boundaries."""
from contextlib import chdir
from pathlib import Path
import sys
import tempfile
import unittest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.bindings.catalog import BindingCatalog, HANDLERS_PATH
from src.prepare.policy import load_policy
from src.reading.character_rules import ProfileError
from src.reading.mouth_profiles import MouthProfiles
from src.yaml_io import load_mapping, validate_resource_identity


class ResourceLoadingTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT_ROOT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bindings = self.root / "bindings"
        (self.bindings / "engine").mkdir(parents=True)
        (self.bindings / "packages").mkdir()
        self.core = {"identity": {"name": "core"}, "reading": {}}
        self.write("engine/core.yaml", self.core)

    def write(self, relative, data):
        path = self.bindings / relative
        path.write_text(yaml.safe_dump(data), encoding="utf-8", newline="\n")
        return path

    def test_defaults_are_independent_of_working_directory(self):
        (self.root / "prepare").write_text("unexpected: {}", encoding="utf-8")
        with chdir(self.root):
            catalog = BindingCatalog()
            policy = load_policy("prepare")
            with self.assertRaisesRegex(ValueError, "unknown policy sections"):
                load_policy(Path("prepare"))
        self.assertIn("verbatim", catalog.engine_bindings)
        self.assertEqual(catalog.engine_bindings["verbatim"]["identity"]["name"], "verbatim")
        self.assertEqual(catalog.package_bindings["verbatim"]["identity"]["requires_engine"], "engine/verbatim")
        self.assertEqual(policy.name, "prepare")

    def test_missing_binding_directory_is_an_explicit_error(self):
        with self.assertRaisesRegex(ProfileError, "Missing binding directory"):
            BindingCatalog(self.root / "absent")

    def test_engine_identity_must_match_filename(self):
        self.write("engine/second.yaml", self.core)
        with self.assertRaisesRegex(ProfileError, "identity.name.*must match filename stem"):
            BindingCatalog(self.bindings)

    def test_missing_engine_dependency_uses_qualified_identity(self):
        self.write("packages/example.yaml", {
            "identity": {"package": "example", "requires_engine": "engine/missing"}, "reading": {}})
        with self.assertRaisesRegex(ProfileError, "unknown required engine identity"):
            BindingCatalog(self.bindings)

    def test_package_identity_must_match_filename(self):
        self.write("packages/example.yaml", {"identity": {"package": "other"}, "reading": {}})
        with self.assertRaisesRegex(ProfileError, "identity.package.*must match filename stem"):
            BindingCatalog(self.bindings)

    def test_engine_dependencies_do_not_use_bare_or_wrong_namespace_aliases(self):
        package = {"identity": {"package": "core", "requires_engine": "engine/core"}, "reading": {}}
        self.write("packages/core.yaml", package)
        catalog = BindingCatalog(self.bindings)
        self.assertEqual(set(catalog.engine_bindings), {"core"})
        self.assertEqual(set(catalog.package_bindings), {"core"})
        for reference in ("core", "packages/core", "../engine/core", "engine/core.yaml"):
            with self.subTest(reference=reference):
                package["identity"]["requires_engine"] = reference
                self.write("packages/core.yaml", package)
                with self.assertRaisesRegex(ProfileError, "unknown required engine identity"):
                    BindingCatalog(self.bindings)

    def test_resource_identity_requires_an_explicit_exact_local_name(self):
        path = self.root / "example.yaml"
        for key in ("name", "package", "registry"):
            for name in (None, "", 42, False, "alias", "Example", "engine/example", "example.yaml"):
                with self.subTest(key=key, name=name):
                    with self.assertRaises(ValueError) as caught:
                        validate_resource_identity({"identity": {key: name}}, path, key=key)
                    self.assertIn(str(path), str(caught.exception))
            self.assertEqual(validate_resource_identity({"identity": {key: "example"}}, path, key=key), "example")
        for data in ({}, {"identity": []}, {"identity": {}}, {"identity": {"package": "example"}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_resource_identity(data, path)

    def test_missing_profile_reference_is_rejected_at_load(self):
        self.core["reading"] = {"commands": [{"name": r"\example", "profile": "missing"}]}
        self.write("engine/core.yaml", self.core)
        with self.assertRaisesRegex(ProfileError, "Unknown mouth profile"):
            BindingCatalog(self.bindings)

    def test_unknown_handler_reference_is_rejected_at_load(self):
        self.core["reading"] = {"grouping": [{"name": r"\example", "action": "unknown"}]}
        self.write("engine/core.yaml", self.core)
        with self.assertRaisesRegex(ProfileError, "unknown reading handler"):
            BindingCatalog(self.bindings)

    def test_duplicate_constructs_do_not_silently_shadow(self):
        self.core["reading"] = {"commands": [{"name": r"\example"}, {"name": r"\example"}]}
        self.write("engine/core.yaml", self.core)
        with self.assertRaisesRegex(ProfileError, "duplicate name in reading.commands"):
            BindingCatalog(self.bindings)

    def test_literal_grammar_handler_references_are_validated(self):
        for grammar, error in (([], "grammar must be a mapping"),
                               ({"handler": "missing"}, "unknown grammar handler"),
                               ({"handler": ["inline_character"]}, "unknown grammar handler")):
            with self.subTest(grammar=grammar):
                self.core["reading"] = {"commands": [{"name": r"\example", "grammar": grammar}]}
                self.write("engine/core.yaml", self.core)
                with self.assertRaisesRegex(ProfileError, error):
                    BindingCatalog(self.bindings)

    def test_grouping_requires_a_supported_declared_kind(self):
        for state in ({}, {"group_kind": "unknown"}, {"group_kind": ["simple"]}, []):
            with self.subTest(state=state):
                self.core["reading"] = {"grouping": [{"name": r"\start", "action": "push_lexical_scope",
                                                      "state_management": state}]}
                self.write("engine/core.yaml", self.core)
                with self.assertRaisesRegex(ProfileError, "requires a simple or semi_simple group_kind"):
                    BindingCatalog(self.bindings)

    def test_malformed_binding_sections_are_configuration_errors(self):
        for reading in ([], {"commands": {}}, {"commands": [42]}):
            with self.subTest(reading=reading):
                self.core["reading"] = reading
                self.write("engine/core.yaml", self.core)
                with self.assertRaises(ProfileError):
                    BindingCatalog(self.bindings)

    def test_definition_contract_requires_explicit_supported_fields(self):
        valid = {"name": r"\example", "family": "stored_definition", "scope": "local",
                 "grammar": {"handler": "primitive_definition", "expansion": "none"}}
        for changed in ({"scope": "unknown"}, {"scope": None},
                        {"grammar": {"handler": "primitive_definition"}},
                        {"grammar": {"handler": "primitive_definition", "expansion": False}},
                        {"grammar": {"handler": "primitive_definition", "expansion": "none", "extra": True}},
                        {"grammar": {"handler": "inline_character", "expansion": "none"}}):
            with self.subTest(changed=changed):
                self.core["reading"] = {"commands": [valid | changed]}
                self.write("engine/core.yaml", self.core)
                with self.assertRaisesRegex(ProfileError, "requires a primitive definition grammar"):
                    BindingCatalog(self.bindings)

    def test_definition_contract_is_resolved_from_yaml_without_losing_scope_or_expansion(self):
        from src.bindings.resolver import BindingResolver
        from src.reading.contracts import UnresolvedBindingResult

        resolver = BindingResolver()
        for name, scope, expansion in (("def", "local", "none"), ("gdef", "global", "none"),
                                        ("edef", "local", "full"), ("xdef", "global", "full")):
            with self.subTest(name=name):
                profile = resolver.resolve_command(name)
                self.assertEqual(profile.family, "stored_definition")
                self.assertEqual(profile.state_management.scope, scope)
                self.assertEqual(profile.grammar, {"handler": "primitive_definition", "expansion": expansion})
                self.assertIsInstance(resolver.resolve_command(name, {"unexpected": True}), UnresolvedBindingResult)
        resolver.resolve_command("def").grammar["expansion"] = "full"
        self.assertEqual(resolver.resolve_command("def").grammar["expansion"], "none")

    def test_handler_registry_rejects_executable_and_unknown_fields(self):
        data = load_mapping(HANDLERS_PATH)
        data["handlers"]["assign_catcode"]["python_import"] = "example.run"
        path = self.root / "reading_handlers.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "invalid handler"):
            BindingCatalog(self.bindings, handlers_path=path)

    def test_conditional_contract_rejects_ambiguous_or_unhandled_fields(self):
        for fields in ({}, {"role": "opener"}, {"role": "opener", "evaluation": True},
                       {"role": "opener", "evaluation": "unknown"},
                       {"role": ["opener"], "evaluation": "always_true"},
                       {"role": "terminator", "evaluation": "always_true"},
                       {"role": "alternative", "action": "conditional_alternative"},
                       {"role": "terminator", "grammar": {"handler": "inline_character"}},
                       {"role": "terminator", "python_import": "example.run"}):
            with self.subTest(fields=fields):
                self.core["reading"] = {"conditionals": [{"name": r"\choice"} | fields]}
                self.write("engine/core.yaml", self.core)
                with self.assertRaisesRegex(ProfileError, "conditional role and opener-only evaluation"):
                    BindingCatalog(self.bindings)

    def test_conditional_aliases_and_deferred_predicates_resolve_from_yaml(self):
        from src.bindings.resolver import BindingResolver
        from src.reading.contracts import ConditionalRule, UnresolvedBindingResult

        specs = [{"name": r"\yes", "role": "opener", "evaluation": "always_true"},
                 {"name": r"\no", "role": "opener", "evaluation": "always_false"},
                 {"name": r"\test", "role": "opener", "evaluation": "deferred"},
                 {"name": r"\otherwise", "role": "alternative"},
                 {"name": r"\case", "role": "case_alternative"},
                 {"name": r"\done", "role": "terminator"}]
        self.core["reading"] = {"conditionals": specs}
        self.write("engine/core.yaml", self.core)
        resolver = BindingResolver(BindingCatalog(self.bindings))
        for spec in specs:
            with self.subTest(spec=spec):
                rule = ConditionalRule(spec["role"], spec.get("evaluation"))
                self.assertEqual(resolver.resolve_conditional(spec["name"]), rule)
                profile = resolver.resolve_command(spec["name"])
                self.assertEqual(profile.family, "conditional")
                self.assertEqual(profile.conditional, rule)
                self.assertEqual(profile.binding_id, "engine/core")
                self.assertIsInstance(resolver.resolve_command(spec["name"], {"extra": True}), UnresolvedBindingResult)
        self.assertIsNone(resolver.resolve_conditional("if_not_declared"))

    def test_bounded_predicate_recipe_is_validated_and_resolved(self):
        from src.bindings.resolver import BindingResolver
        spec = {"name": r"\compare", "role": "opener", "evaluation": "deferred",
                "capture_operands": 2, "predicate": "character_equal"}
        self.core["reading"] = {"conditionals": [spec]}
        self.write("engine/core.yaml", self.core)
        self.assertEqual(BindingResolver(BindingCatalog(self.bindings)).resolve_conditional("compare").predicate,
                         "character_equal")
        for changes in ({"predicate": "python_eval"}, {"predicate": []}, {"capture_operands": 0},
                        {"evaluation": "always_true"}, {"role": "terminator"}):
            with self.subTest(changes=changes):
                self.core["reading"]["conditionals"] = [{**spec, **changes}]
                self.write("engine/core.yaml", self.core)
                with self.assertRaises(ProfileError):
                    BindingCatalog(self.bindings)

    def test_newif_is_a_factory_without_a_conditional_nesting_role(self):
        from src.bindings.resolver import BindingResolver
        from src.reading.contracts import EffectiveReadingProfile

        resolver = BindingResolver()
        self.assertIsNone(resolver.resolve_conditional("newif"))
        profile = resolver.resolve_command("newif")
        self.assertIsInstance(profile, EffectiveReadingProfile)
        self.assertEqual(profile.family, "conditional_factory")
        self.assertEqual(profile.grammar["handler"], "boolean_declaration")
        self.assertIsNone(profile.conditional)

    def test_registry_identity_must_match_filename(self):
        path = self.root / "renamed.yaml"
        path.write_text(HANDLERS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "identity.registry.*must match filename stem"):
            BindingCatalog(self.bindings, handlers_path=path)

    def test_mouth_loader_rejects_misplaced_registries(self):
        directory = self.root / "mouth"
        directory.mkdir()
        (directory / "wrong.yaml").write_text("identity: {registry: reading_handlers}", encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "registries do not belong"):
            MouthProfiles(directory)


if __name__ == "__main__":
    unittest.main()
