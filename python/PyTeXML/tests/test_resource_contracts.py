"""Conformance checks for declarative bindings and experimental projections."""
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from src.yaml_io import load_mapping, validate_resource_identity


class ResourceIdentityTests(unittest.TestCase):
    def test_all_yaml_resources_follow_the_filename_identity_rule(self):
        resources = PROJECT_ROOT / "resources"
        paths = sorted(resources.rglob("*.yaml"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(resource=path.relative_to(resources)):
                data = load_mapping(path)
                key = ("registry" if path.parent.name == "registries" else
                       "package" if path.parent.name == "packages" else "name")
                self.assertEqual(validate_resource_identity(data, path, key=key), path.stem)


class ExperimentalProjectionTests(unittest.TestCase):
    def setUp(self):
        self.capture_dir = PROJECT_ROOT / "resources" / "experimental" / "projections" / "latexml"
        self.bindings_dir = PROJECT_ROOT / "resources" / "bindings"

    def test_capture_directory_structure(self):
        self.assertTrue(self.capture_dir.is_dir())
        self.assertTrue((self.capture_dir / "engine").is_dir())
        self.assertTrue((self.capture_dir / "packages").is_dir())

    def test_capture_files_correspond_to_bindings(self):
        projections = sorted(self.capture_dir.rglob("*.yaml"))
        self.assertTrue(projections)
        for cap_file in projections:
            with self.subTest(projection=cap_file):
                relative = cap_file.relative_to(self.capture_dir)
                bind_file = self.bindings_dir / relative
                self.assertTrue(bind_file.is_file(), f"Missing binding file: {bind_file}")
                key = "package" if relative.parts[0] == "packages" else "name"
                data = load_mapping(cap_file)
                self.assertEqual(validate_resource_identity(data, cap_file, key=key),
                                 validate_resource_identity(load_mapping(bind_file), bind_file, key=key))
                self.assertIn("projections", data)
                self.assertEqual(data["identity"]["corresponds_to_binding"], relative.with_suffix("").as_posix())

    def test_bindings_are_purified_of_semantics(self):
        """Verifies that no binding file retains the downstream 'semantics' projection section."""
        for yml in self.bindings_dir.glob("**/*.yaml"):
            data = load_mapping(yml)
            self.assertNotIn("semantics", data, f"Binding file {yml.name} still contains 'semantics' projection!")


class BindingConformanceTests(unittest.TestCase):
    def setUp(self):
        self.bindings_dir = PROJECT_ROOT / "resources" / "bindings"

    def load_binding(self, rel_path: str) -> dict:
        path = self.bindings_dir / rel_path
        return load_mapping(path)

    def test_kernel_verbatim_strictness(self):
        data = self.load_binding("engine/verbatim.yaml")
        envs = {e["name"]: e for e in data["reading"]["environments"]}
        v = envs["verbatim"]
        self.assertEqual(v["terminator"]["regex_pattern"], r"\\end\{verbatim\}")
        self.assertEqual(v["terminator"]["trailing_line_behavior"], "preserve_trailing_content")

    def test_package_verbatim_ordered_overrides(self):
        data = self.load_binding("packages/verbatim.yaml")
        self.assertIn("environment_overrides", data["reading"])
        overrides = {e["name"]: e for e in data["reading"]["environment_overrides"]}
        self.assertIn("verbatim", overrides)
        v = overrides["verbatim"]
        self.assertEqual(v["terminator"]["matching_domain"], "physical_line")
        self.assertEqual(v["terminator"]["regex_pattern"], r"\\end[ \t]*\{verbatim\}")
        self.assertEqual(v["terminator"]["trailing_line_behavior"], "discard_with_warning")

        # Package comment environment
        envs = {e["name"]: e for e in data["reading"]["environments"]}
        self.assertIn("comment", envs)

    def test_comment_package_strict_whole_line(self):
        data = self.load_binding("packages/comment.yaml")
        c = data["reading"]["environments"][0]
        self.assertTrue(c["terminator"]["requires_column_zero"])
        self.assertFalse(c["terminator"]["trailing_content_allowed"])
        self.assertEqual(c["terminator"]["matching_domain"], "physical_line")
        self.assertEqual(c["terminator"]["regex_pattern"], r"^\\end\{comment\}$")

    def test_alltt_preserves_trailing_line_content(self):
        data = self.load_binding("packages/alltt.yaml")
        a = data["reading"]["environments"][0]
        self.assertEqual(a["terminator"]["trailing_line_behavior"], "preserve_trailing_content")
        self.assertEqual(a["terminator"]["regex_pattern"], r"\\end[ \t]*\{alltt\}")

    def test_expl3_catcodes_and_parameters(self):
        data = self.load_binding("engine/core_latex.yaml")
        mutators = {m["name"]: m for m in data["reading"]["catcode_mutators"]}
        expl = mutators[r"\ExplSyntaxOn"]
        # @ is intentionally NOT modified by \ExplSyntaxOn
        self.assertNotIn("@", expl["overrides"])
        self.assertEqual(expl["overrides"]["_"], 11)   # LETTER
        self.assertEqual(expl["overrides"][":"], 11)   # LETTER
        self.assertEqual(expl["overrides"]['"'], 12)   # OTHER
        self.assertEqual(expl["overrides"]["|"], 12)   # OTHER
        self.assertEqual(expl["overrides"]["^"], 7)    # SUPERSCRIPT
        self.assertEqual(expl["overrides"][" "], 9)    # IGNORED
        self.assertEqual(expl["overrides"]["\t"], 9)   # IGNORED
        self.assertEqual(expl["overrides"]["~"], 10)   # SPACE
        self.assertEqual(expl["reader_parameters"]["endlinechar"], 32)

    def test_configurable_literals_declare_option_resolution(self):
        fancy = self.load_binding("packages/fancyvrb.yaml")
        self.assertEqual(fancy["identity"]["version"], "4.7")
        self.assertTrue((REPO / fancy["identity"]["source_reference"]).is_file())
        self.assertIn("commandchars", fancy["reading"]["option_resolution"]["reading_affecting_keys"])

        listings = self.load_binding("packages/listings.yaml")
        self.assertEqual(listings["identity"]["version"], "1.11b")
        self.assertTrue((REPO / listings["identity"]["source_reference"]).is_file())
        self.assertIn("escapeinside", listings["reading"]["option_resolution"]["reading_affecting_keys"])

    def test_generic_discard_block_profile_does_not_force_column_zero(self):
        mouth_file = PROJECT_ROOT / "resources" / "profiles" / "mouth" / "discard_block.yaml"
        profile = load_mapping(mouth_file)
        self.assertNotIn("requires_column_zero", profile)


if __name__ == "__main__":
    unittest.main()
