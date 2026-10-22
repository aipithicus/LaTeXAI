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

    def test_handler_registry_rejects_executable_and_unknown_fields(self):
        data = load_mapping(HANDLERS_PATH)
        data["handlers"]["assign_catcode"]["python_import"] = "example.run"
        path = self.root / "reading_handlers.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "invalid handler"):
            BindingCatalog(self.bindings, handlers_path=path)

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
