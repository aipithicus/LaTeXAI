"""
Unit tests for policy loader, declarative policy configurations, and capture projections.
"""

from pathlib import Path
import sys
import unittest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from policy_loader import (
    ExtractionPolicy,
    load_policy,
    POLICY_DIR,
)


class PolicyLoaderTests(unittest.TestCase):
    def test_all_preset_policies_exist_and_load(self):
        presets = ["preflight", "lossless", "prose_extraction"]
        for preset in presets:
            policy = load_policy(preset)
            self.assertIsInstance(policy, ExtractionPolicy)
            self.assertEqual(policy.name, preset)
            self.assertTrue(policy.target)
            self.assertTrue(policy.description)

    def test_compact_alias_resolves_to_preflight(self):
        policy = load_policy("compact")
        self.assertEqual(policy.name, "preflight")

    def test_preflight_role_actions(self):
        policy = load_policy("preflight")

        # Semantic roles
        self.assertTrue(policy.should_eliminate_role("author_notes"))
        self.assertTrue(policy.should_eliminate_role("editorial_annotation"))
        self.assertTrue(policy.should_eliminate_role("dead_conditional"))
        self.assertFalse(policy.should_eliminate_role("code_listing"))
        self.assertEqual(policy.get_role_action("code_listing"), "preserve")
        self.assertEqual(policy.get_role_action("code_inline"), "preserve")
        self.assertEqual(policy.get_role_action("transparent_container"), "unwrap")
        self.assertTrue(policy.should_unwrap_role("transparent_container"))

        # Lexical events
        self.assertTrue(policy.should_eliminate_comment_line())
        self.assertTrue(policy.should_strip_comment_inline())
        self.assertTrue(policy.should_preserve_line_continuation())
        self.assertEqual(policy.lexical_events.magic_directive, "extract_metadata")

        # Structural normalization
        self.assertTrue(policy.should_coalesce_paragraphs())
        self.assertTrue(policy.should_strip_trailing_whitespace())

        # Provenance
        self.assertTrue(policy.provenance.emit_ledger)
        self.assertTrue(policy.provenance.rle_compression)

    def test_lossless_policy_rules(self):
        policy = load_policy("lossless")

        # Roles
        self.assertEqual(policy.get_role_action("author_notes"), "route_to_sidecar")
        self.assertFalse(policy.should_eliminate_role("editorial_annotation"))
        self.assertFalse(policy.should_eliminate_role("dead_conditional"))

        # Lexical events
        self.assertFalse(policy.should_eliminate_comment_line())
        self.assertEqual(policy.lexical_events.comment_line, "preserve")
        self.assertEqual(policy.lexical_events.comment_inline, "preserve")

        # Normalization
        self.assertFalse(policy.should_coalesce_paragraphs())
        self.assertFalse(policy.should_strip_trailing_whitespace())

        # Provenance
        self.assertTrue(policy.provenance.emit_ledger)
        self.assertFalse(policy.provenance.rle_compression)

    def test_prose_extraction_policy_unwrapping(self):
        policy = load_policy("prose_extraction")

        # Styling containers unwrapped to reveal prose
        self.assertTrue(policy.should_unwrap_role("formatting_container"))
        self.assertTrue(policy.should_eliminate_role("author_notes"))
        self.assertTrue(policy.should_eliminate_role("editorial_annotation"))

        # Opaque literal markdown conversion
        self.assertEqual(policy.get_role_action("code_listing"), "convert_to_markdown")
        self.assertEqual(policy.get_role_action("code_inline"), "convert_to_markdown")

    def test_unknown_role_fallback(self):
        policy = load_policy("preflight")
        fallback = policy.get_role_action("unregistered_custom_role")
        self.assertEqual(fallback, "preserve")

    def test_missing_policy_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            load_policy("nonexistent_preset_xyz")


class CaptureProjectionTests(unittest.TestCase):
    def setUp(self):
        self.capture_dir = PROJECT_ROOT / "capture"
        self.bindings_dir = PROJECT_ROOT / "bindings"

    def test_capture_directory_structure(self):
        self.assertTrue(self.capture_dir.is_dir())
        self.assertTrue((self.capture_dir / "engine").is_dir())
        self.assertTrue((self.capture_dir / "packages").is_dir())

    def test_capture_files_correspond_to_bindings(self):
        expected_mirrors = [
            ("engine", "verbatim.yaml"),
            ("packages", "comment.yaml"),
            ("packages", "verbatim.yaml"),
            ("packages", "fancyvrb.yaml"),
            ("packages", "listings.yaml"),
            ("packages", "alltt.yaml"),
        ]
        for sub, name in expected_mirrors:
            cap_file = self.capture_dir / sub / name
            bind_file = self.bindings_dir / sub / name
            self.assertTrue(cap_file.is_file(), f"Missing capture mirror: {cap_file}")
            self.assertTrue(bind_file.is_file(), f"Missing binding file: {bind_file}")

            with open(cap_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertIn("identity", data)
            self.assertIn("projections", data)
            self.assertEqual(data["identity"]["corresponds_to_binding"], f"{sub}/{name.replace('.yaml', '')}")

    def test_bindings_are_purified_of_semantics(self):
        """Verifies that no binding file retains the downstream 'semantics' projection section."""
        for yml in self.bindings_dir.glob("**/*.yaml"):
            with open(yml, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertNotIn("semantics", data, f"Binding file {yml.name} still contains 'semantics' projection!")


class BindingConformanceTests(unittest.TestCase):
    def setUp(self):
        self.bindings_dir = PROJECT_ROOT / "bindings"

    def load_binding(self, rel_path: str) -> dict:
        path = self.bindings_dir / rel_path
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

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
        mouth_file = PROJECT_ROOT / "profiles" / "mouth" / "discard_block.yaml"
        with mouth_file.open(encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        self.assertNotIn("requires_column_zero", profile)


if __name__ == "__main__":
    unittest.main()
