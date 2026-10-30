"""Reject drift and unsupported qualification in a research atlas."""
import copy
import unittest

from src.validation.behavioral_atlas import load, verify, excerpt


class AtlasCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load()

    def test_source_drift_is_not_a_qualified_observation(self):
        data = copy.deepcopy(self.catalog)
        data["sources"]["trailing"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Source drift"):
            verify(data)

    def test_invalid_and_shifted_fragments_rejected(self):
        for end in (-1, self.catalog["fragments"]["trailing_body"]["byte_end"] - 1):
            with self.subTest(end=end):
                data = copy.deepcopy(self.catalog)
                data["fragments"]["trailing_body"]["byte_end"] = end
                with self.assertRaisesRegex(ValueError, "Invalid byte range|Fragment drift"):
                    verify(data)

    def test_duplicate_and_unlocated_cases_rejected(self):
        data = copy.deepcopy(self.catalog)
        data["cases"].append(data["cases"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate case"):
            verify(data)
        data = copy.deepcopy(self.catalog)
        data["cases"][0]["fragments"] = []
        with self.assertRaisesRegex(ValueError, "Unlocated case"):
            verify(data)

    def test_golden_cannot_promote_itself_to_native_qualification(self):
        data = copy.deepcopy(self.catalog)
        data["cases"][0]["qualification"]["native"] = "passed"
        with self.assertRaisesRegex(ValueError, "Qualification needs"):
            verify(data)

    def test_stale_check_reference_is_rejected(self):
        data = copy.deepcopy(self.catalog)
        data["checks"]["physical_spaces"]["test"] = "AtlasWitnessTests.test_missing"
        with self.assertRaisesRegex(ValueError, "Missing Python check"):
            verify(data)

    def test_mixed_line_endings_are_retained_as_bytes(self):
        self.assertIn(b"\r\r\n", excerpt(self.catalog, "newlines_document"))
        self.assertTrue(excerpt(self.catalog, "newlines_helper").endswith(b"\r\r"))


if __name__ == "__main__":
    unittest.main()
