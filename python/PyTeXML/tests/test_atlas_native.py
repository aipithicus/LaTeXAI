"""Pinned program observations and strict comparison admission, without native TeX."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.validation.atlas_native import compare, load_reference, python_case
from src.validation.behavioral_atlas import PROJECT


class AtlasNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = load_reference()

    def native(self, case="M02"):
        return copy.deepcopy(self.reference["cases"][case])

    def matching(self, native):
        return {"identity": native["identity"], "status": "completed",
                "trace": dict(native["trace"]), "target": copy.deepcopy(native["target"])}

    def test_reconstruction_protocol_matches_native(self):
        native = self.native()
        actual = python_case("M02")
        comparison = compare(native, actual)
        self.assertEqual(comparison["status"], "match", actual)
        self.assertEqual(len(comparison["observations"]), 8)
        self.assertEqual(actual["trace"]["F"], "0")  # Generated-name display loses token identity.

    def test_native_generator_observes_helper_state_not_only_definition(self):
        trace = self.native("P03")["trace"]
        self.assertEqual(trace["A"], trace["H"])
        self.assertEqual([trace[k] for k in "BCDEFGI"],
                         ["SKIP", "F", "F", "SKIP", "SKIP", "F", "RESTORED"])
        insertion = self.native("P03-insertion")["trace"]
        self.assertEqual(insertion, {"A": "macro:->##1", "B": "macro:->##1", "C": "1"})

    def test_source_generator_derives_the_native_definition(self):
        native = self.native("P03")
        actual = python_case("P03")
        self.assertIsNotNone(actual["target"], actual)
        self.assertEqual(actual["target"]["semantic_key"], native["target"]["semantic_key"])
        self.assertEqual(compare(native, actual)["status"], "match", actual)

    def test_insertion_and_individual_expansion_barriers_match_native(self):
        cases = [*(f"P02-{n}" for n in range(1, 10)),
                 "P02-insertion", "P03-insertion", "P03-tail"]
        for case in cases:
            with self.subTest(case=case):
                actual = python_case(case)
                self.assertEqual(compare(self.native(case), actual)["status"], "match", actual)

    def test_missing_observation_or_target_is_not_a_pass(self):
        native = self.native()
        for omission in ("trace", "target"):
            with self.subTest(omission=omission):
                actual = self.matching(native)
                if omission == "trace":
                    actual["trace"].pop("F")
                else:
                    actual["target"] = None
                self.assertEqual(compare(native, actual)["status"], "not_qualified")

    def test_incomplete_execution_or_changed_typed_meaning_is_not_a_pass(self):
        native = self.native()
        for change in ("status", "semantic_key", "trace"):
            with self.subTest(change=change):
                actual = self.matching(native)
                if change == "status":
                    actual["status"] = "blocked"
                elif change == "trace":
                    actual["trace"]["F"] = "1"
                else:
                    actual["target"]["semantic_key"] = ["different"]
                self.assertEqual(compare(native, actual)["status"], "not_qualified")

    def test_identity_and_unqualified_native_reference_rejected(self):
        native = self.native()
        actual = self.matching(native)
        actual["identity"] = {}
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            compare(native, actual)
        actual = self.matching(native)
        native["status"] = "trace_only"
        self.assertEqual(compare(native, actual)["status"], "native_not_qualified")

    def test_native_ifx_failure_cannot_be_promoted_by_matching_display(self):
        data = copy.deepcopy(self.reference)
        data["cases"]["M02"]["runs"][1]["trace"]["IFX"] = "0"
        temporary_root = PROJECT / "temp/behavioral-atlas"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as folder:
            path = Path(folder) / "reference.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unqualified native replay"):
                load_reference(path)


if __name__ == "__main__":
    unittest.main()
