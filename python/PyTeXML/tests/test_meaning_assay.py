"""Offline assay boundaries and generated fixture consumption."""
import json
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.reading.contracts import ReadingIssue
from src.validation.meaning_assay.model import (Candidates, check_fixtures, descriptor,
    active_references, exception_reason, kind, layer, references)
from src.validation.meaning_assay.native import cs, name_hex
from src.validation.meaning_assay.fixtures import freeze
from src.validation.meaning_assay.compare import compare_derived, load_reference
from src.validation.meaning_assay.triage import conclusion, differences, pattern, spacing_direction
from src.reading.contracts import UncertainMeaning


class MeaningAssayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = Candidates()
        cls.reference = load_reference(PROJECT / "tests/fixtures/engine/native-meanings/root-a-20261029")

    def test_typed_descriptor_preserves_flags_parameters_and_references(self):
        _, definition = self.candidates.parse(r"\protected\long macro:#1,#2;->\__foo:n {#2}##:#1", "l3", "test")
        value = descriptor(definition)
        self.assertEqual(value["parameter_count"], 2)
        self.assertTrue(definition.protected and definition.long)
        self.assertEqual(references(definition), {"__foo:n": 1})
        self.assertIn("control_sequence", json.dumps(value))

    def test_same_display_can_have_different_typed_reconstructions(self):
        _, l3 = self.candidates.parse("macro:->_", "l3", "one")
        _, latex = self.candidates.parse("macro:->_", "latex", "two")
        self.assertNotEqual(descriptor(l3)["semantic_sha256"], descriptor(latex)["semantic_sha256"])

    def test_active_references_are_not_control_sequence_names(self):
        _, definition = self.candidates.parse(r"macro:->~\~", "latex", "test")
        self.assertEqual(active_references(definition), {"~": 1})
        self.assertEqual(references(definition), {"~": 1})

    def test_exception_reports_furthest_gate(self):
        self.assertEqual(exception_reason({"l3": "unequal", "latex": "ReadingIssue: invalid"}), "native_unequal")
        self.assertEqual(exception_reason({"l3": "ValueError: non_ascii_or_control_input"}), "non_ascii_or_control_input")

    def test_display_triage_requires_same_candidate_native_comparison(self):
        edits = differences(r"macro:->\T1-cmd ", r"macro:->\T 1-cmd ")
        self.assertEqual(pattern(edits), "spaces_only")
        self.assertEqual(spacing_direction(edits), "spaces_added")
        self.assertEqual(conclusion([]), "incomplete_native_comparison")
        self.assertEqual(conclusion([{}]), "incomplete_native_comparison")
        self.assertEqual(conclusion([{"native_display": "x", "python_matches_native_candidate": True}]),
                         "candidate_displays_agree_reconstruction_loss")
        self.assertEqual(conclusion([{"native_display": "x", "python_matches_native_candidate": False}]),
                         "candidate_display_discrepancy")

    def test_census_comparison_preserves_basis_and_unknown_boundaries(self):
        manifest, rows = self.reference
        expected = rows["@firstofone"]
        _, definition = self.candidates.parse(expected["meaning"], expected["regime"], "derived")
        def compare(values, basis=manifest["basis"]["inventory_sha256"]):
            return compare_derived(values, self.reference, inventory_sha256=basis, state_boundary="test")
        result = compare({"@firstofone": definition, "new-generated-name": definition})
        self.assertEqual(result["counts"], {"match": 1, "no_qualified_reference": 1})
        self.assertEqual(result["matched_share_of_qualified_reference"], 1 / manifest["count"])
        self.assertEqual(compare({"@firstofone": replace(definition, long=not definition.long)})["counts"], {"mismatch": 1})
        self.assertEqual(compare({"@firstofone": UncertainMeaning(definition.span)})["counts"], {"uncertain": 1})
        self.assertEqual(compare({"@firstofone": None})["counts"], {"missing": 1})
        with self.assertRaisesRegex(ValueError, "bases differ"):
            compare({"@firstofone": definition}, basis="wrong-basis")

    def test_delimited_parameter_does_not_merge_with_candidate_name(self):
        _, definition = self.candidates.parse("macro:a#1b->#1", "l3", "test")
        self.assertEqual(definition.target.value, "AssayCandidate")
        self.assertEqual(definition.parameter_tokens[0].value, "a")

    def test_unbalanced_or_trailing_input_is_never_sent_to_native(self):
        for meaning in (r"macro:->}\input danger{", "macro:->{", "macro:->a\nb"):
            with self.subTest(meaning=meaning), self.assertRaises((ValueError, ReadingIssue)):
                self.candidates.parse(meaning, "l3", "test")

    def test_hex_names_cannot_change_generated_probe_syntax(self):
        name = "a%}\\input{b}\n"
        self.assertNotIn("input", cs(name))
        self.assertEqual(bytes.fromhex(name_hex(name)).decode("latin-1"), name)
        with self.assertRaises(UnicodeEncodeError):
            name_hex("λ")

    def test_kinds_and_naming_layers_are_separate(self):
        self.assertEqual(layer("tex_relax:D"), "tex_primitive_alias")
        self.assertEqual(layer("l__foo_tl"), "private_l3")
        self.assertEqual(layer("c_true_bool"), "public_l3")
        self.assertEqual(layer("@foo"), "kernel_at")
        self.assertEqual(kind(r"\count23"), "register")
        self.assertEqual(kind(r"\long macro:->x"), "macro")
        self.assertEqual(kind("undefined"), "undefined")

    def test_generated_fixture_replay_detects_token_drift(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            path = Path(folder) / "fixtures.jsonl"
            _, definition = self.candidates.parse(r"macro:#1->\foo {#1}", "l3", "fixture")
            row = {"schema": "pytexml-native-meaning-fixture/1", "name": "example:n",
                   "meaning": r"macro:#1->\foo {#1}", "regime": "l3", **descriptor(definition)}
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertEqual(check_fixtures(path), 1)
            row["regime"] = "latex"
            row["meaning"] = "macro:->_"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Typed meaning changed"):
                check_fixtures(path)

    def test_freeze_rejects_incomplete_or_changed_receipt(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            assay = Path(folder)
            receipt = assay / "summary.json"
            receipt.write_text(json.dumps({"schema": "pytexml-meaning-assay/1", "status": "failed"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "completed assay"):
                freeze(assay, assay / "frozen")
            (assay / "fixtures.jsonl").write_text("changed", encoding="utf-8")
            receipt.write_text(json.dumps({"schema": "pytexml-meaning-assay/1", "status": "complete",
                "artifacts": {"fixtures.jsonl": "wrong"}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum differs"):
                freeze(assay, assay / "frozen")
            self.assertFalse((assay / "frozen").exists())


if __name__ == "__main__":
    unittest.main()
