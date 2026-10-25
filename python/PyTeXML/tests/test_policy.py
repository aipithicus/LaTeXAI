"""
Unit tests for preparation policy loading and experimental policy examples.
"""

from pathlib import Path
import sys
import unittest
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.prepare.policy import (
    ExtractionPolicy,
    load_policy,
    POLICY_DIR,
)


class PolicyLoaderTests(unittest.TestCase):
    def test_invalid_configuration_is_rejected_with_its_source(self):
        cases = (
            ("provenance: {emit_ledger: true, emit_ledger: false}", "Duplicate YAML key"),
            ("provenance: {emit_ledger: 'false'}", "provenance.emit_ledger"),
            ("role_actions: {code_listing: discard}", "unknown action"),
            ("role_actions: []", "role_actions must be a mapping"),
            ("lexical_events: {comment_inline: eliminate}", "lexical_events.comment_inline"),
            ("lexical_events: {comment_inlne: preserve}", "lexical_events.comment_inlne"),
            ("structural_normalization: {paragraph_breaks: false}", "paragraph_breaks"),
            ("identity: {name: 123}", "identity.name"),
            ("unexpected: {}", "unknown policy sections"),
            ("[]", "expected a YAML mapping"),
        )
        scratch = PROJECT_ROOT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / "policy.yaml"
            for source, error in cases:
                with self.subTest(source=source):
                    path.write_text(source, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error) as caught:
                        load_policy(path)
                    self.assertIn(str(path), str(caught.exception))

    def test_omitted_sections_keep_defaults_and_unknown_roles_preserve(self):
        scratch = PROJECT_ROOT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / "minimal.yaml"
            path.write_text("identity: {name: minimal}", encoding="utf-8")
            policy = load_policy(path)
        self.assertEqual(policy.name, "minimal")
        self.assertEqual(policy.get_role_action("new_role"), "preserve")
        self.assertTrue(policy.should_preserve_line_continuation())
        self.assertTrue(policy.provenance.emit_ledger)

    def test_custom_policy_requires_a_matching_declared_identity(self):
        scratch = PROJECT_ROOT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / "custom.yaml"
            for source, error in (("{}", "identity must be a mapping"),
                                  ("identity: {}", "identity.name must be a nonempty string"),
                                  ("identity: {name: alias}", "must match filename stem")):
                with self.subTest(source=source):
                    path.write_text(source, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        load_policy(path)

    def test_partial_sections_override_defaults_without_mutating_raw_config(self):
        scratch = PROJECT_ROOT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            path = Path(directory) / "partial.yaml"
            path.write_text("identity: {name: partial}\n"
                            "lexical_events: {comment_inline: preserve}\n"
                            "structural_normalization: {paragraph_breaks: coalesce}\n"
                            "provenance: {emit_ledger: false}\n"
                            "linting: {repairs: [drop_invalid_character]}\n", encoding="utf-8")
            policy = load_policy(path)
        self.assertEqual(policy.lexical_events.comment_inline, "preserve")
        self.assertEqual(policy.lexical_events.comment_line, "eliminate")
        self.assertEqual(policy.lexical_events.line_continuation, "preserve")
        self.assertEqual(policy.lexical_events.magic_directive, "extract_metadata")
        self.assertEqual(policy.normalization.paragraph_breaks, "coalesce")
        self.assertEqual(policy.normalization.trailing_whitespace, "strip")
        self.assertFalse(policy.provenance.emit_ledger)
        self.assertTrue(policy.provenance.rle_compression)
        self.assertEqual(policy.linting.mode, "report")
        self.assertEqual(policy.linting.repairs, ("drop_invalid_character",))
        self.assertEqual(policy.raw_config["linting"], {"repairs": ["drop_invalid_character"]})

    def test_all_preset_policies_exist_and_load(self):
        presets = ["prepare"]
        for preset in presets:
            policy = load_policy(preset)
            self.assertIsInstance(policy, ExtractionPolicy)
            self.assertEqual(policy.name, preset)
            self.assertTrue(policy.target)
            self.assertTrue(policy.description)

    def test_removed_names_and_experiments_are_not_named_presets(self):
        for name in ("preflight", "compact", "lossless", "prose_extraction"):
            with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                load_policy(name)

    def test_prepare_role_actions(self):
        policy = load_policy("prepare")

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
        self.assertFalse(policy.should_coalesce_paragraphs())
        self.assertTrue(policy.should_strip_trailing_whitespace())

        # Provenance
        self.assertTrue(policy.provenance.emit_ledger)
        self.assertTrue(policy.provenance.rle_compression)

    def test_lossless_policy_rules(self):
        policy = load_policy(PROJECT_ROOT / "resources/experimental/policies/lossless.yaml")

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
        policy = load_policy(PROJECT_ROOT / "resources/experimental/policies/prose_extraction.yaml")

        # Styling containers unwrapped to reveal prose
        self.assertTrue(policy.should_unwrap_role("formatting_container"))
        self.assertTrue(policy.should_eliminate_role("author_notes"))
        self.assertTrue(policy.should_eliminate_role("editorial_annotation"))

        # Opaque literal markdown conversion
        self.assertEqual(policy.get_role_action("code_listing"), "convert_to_markdown")
        self.assertEqual(policy.get_role_action("code_inline"), "convert_to_markdown")

    def test_unknown_role_fallback(self):
        policy = load_policy("prepare")
        fallback = policy.get_role_action("unregistered_custom_role")
        self.assertEqual(fallback, "preserve")

    def test_missing_policy_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            load_policy("nonexistent_preset_xyz")


if __name__ == "__main__":
    unittest.main()
