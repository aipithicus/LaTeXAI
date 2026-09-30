"""
Unit tests for policy loader, declarative policy configurations, and capture projections.
"""

from pathlib import Path
import sys
import unittest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python" / "latex-extractor"))

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
            self.assertTrue(policy.target_pipeline)
            self.assertTrue(policy.description)

    def test_compact_alias_resolves_to_preflight(self):
        policy = load_policy("compact")
        self.assertEqual(policy.name, "preflight")

    def test_preflight_policy_rules(self):
        policy = load_policy("preflight")

        # Span actions
        comment_action = policy.get_span_action("editorial_comment_block")
        self.assertEqual(comment_action.action, "delete_span")
        self.assertTrue(comment_action.emit_tombstone)
        self.assertEqual(comment_action.tombstone_category, "PRUNED_SEMANTIC")

        verbatim_action = policy.get_span_action("opaque_literal")
        self.assertEqual(verbatim_action.action, "preserve_immutable")
        self.assertFalse(verbatim_action.strip_comments)
        self.assertFalse(verbatim_action.normalize_whitespace)

        # Lexical comments
        self.assertEqual(policy.lexical_comments.full_line_action, "drop_line")
        self.assertEqual(policy.lexical_comments.inline_action, "strip_payload_preserve_boundary")
        self.assertEqual(policy.lexical_comments.line_continuation_action, "preserve_continuation_marker")

        # Whitespace
        self.assertEqual(policy.whitespace.max_consecutive_blank_lines, 1)
        self.assertTrue(policy.whitespace.strip_trailing_spaces)
        self.assertTrue(policy.whitespace.swallow_first_verbatim_newline)

        # Macro pruning
        self.assertTrue(policy.should_drop_macro("todo"))
        self.assertTrue(policy.should_drop_macro(r"\todo"))
        self.assertTrue(policy.should_drop_macro("annotation"))
        self.assertFalse(policy.should_unwrap_macro("textbf"))

        # Conditionals & Provenance
        self.assertTrue(policy.conditionals.simplify_static_branches)
        self.assertTrue(policy.provenance.emit_ledger)
        self.assertTrue(policy.provenance.rle_compression)

    def test_lossless_policy_rules(self):
        policy = load_policy("lossless")

        # Span actions: sidecar routing instead of deletion
        comment_action = policy.get_span_action("editorial_comment_block")
        self.assertEqual(comment_action.action, "route_to_sidecar")
        self.assertEqual(comment_action.destination_sidecar, "editorial_notes.jsonl")
        self.assertTrue(comment_action.preserve_in_source)

        # Exact whitespace
        self.assertIsNone(policy.whitespace.max_consecutive_blank_lines)
        self.assertFalse(policy.whitespace.strip_trailing_spaces)

        # No pruning
        self.assertFalse(policy.should_drop_macro("todo"))
        self.assertFalse(policy.conditionals.simplify_static_branches)
        self.assertFalse(policy.provenance.track_tombstones)

    def test_prose_extraction_policy_unwrapping(self):
        policy = load_policy("prose_extraction")

        # Styling macros unwrapped to reveal prose
        self.assertTrue(policy.should_unwrap_macro("textbf"))
        self.assertTrue(policy.should_unwrap_macro(r"\textbf"))
        self.assertTrue(policy.should_unwrap_macro("textit"))
        self.assertTrue(policy.should_unwrap_macro("emph"))
        self.assertTrue(policy.should_unwrap_macro("blue"))
        self.assertFalse(policy.should_unwrap_macro("unknown_macro"))

        # Opaque literal markdown conversion
        self.assertEqual(policy.get_span_action("opaque_literal").action, "convert_to_markdown_fence")
        self.assertEqual(policy.get_span_action("opaque_inline_literal").action, "convert_to_inline_code")

    def test_unknown_category_fallback(self):
        policy = load_policy("preflight")
        fallback = policy.get_span_action("unregistered_custom_category")
        self.assertEqual(fallback.action, "preserve_immutable")

    def test_missing_policy_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            load_policy("nonexistent_preset_xyz")


class CaptureProjectionTests(unittest.TestCase):
    def setUp(self):
        self.capture_dir = REPO / "python" / "latex-extractor" / "capture"
        self.bindings_dir = REPO / "python" / "latex-extractor" / "bindings"

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


if __name__ == "__main__":
    unittest.main()
