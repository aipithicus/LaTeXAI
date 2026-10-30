"""Offline assay boundaries and generated fixture consumption."""
import json
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


class MeaningAssayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = Candidates()

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
