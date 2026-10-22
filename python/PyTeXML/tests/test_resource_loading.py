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
from src.yaml_io import load_mapping


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
        self.assertEqual(catalog.engine_bindings["verbatim"]["identity"]["name"], "verbatim_core")
        self.assertEqual(policy.name, "prepare")

    def test_missing_binding_directory_is_an_explicit_error(self):
        with self.assertRaisesRegex(ProfileError, "Missing binding directory"):
            BindingCatalog(self.root / "absent")

    def test_duplicate_engine_identities_are_rejected(self):
        self.write("engine/second.yaml", self.core)
        with self.assertRaisesRegex(ProfileError, "duplicate binding identity"):
            BindingCatalog(self.bindings)

    def test_missing_engine_dependency_uses_logical_identity(self):
        self.write("packages/example.yaml", {
            "identity": {"package": "example", "requires_engine": "missing"}, "reading": {}})
        with self.assertRaisesRegex(ProfileError, "unknown required engine identity"):
            BindingCatalog(self.bindings)

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
        path = self.root / "handlers.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "invalid handler"):
            BindingCatalog(self.bindings, handlers_path=path)

    def test_mouth_loader_rejects_misplaced_registries(self):
        directory = self.root / "mouth"
        directory.mkdir()
        (directory / "wrong.yaml").write_text("identity: {registry: reading_handlers}", encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "registries do not belong"):
            MouthProfiles(directory)


if __name__ == "__main__":
    unittest.main()
