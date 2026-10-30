"""Replay the generated corpus without requiring an installed native oracle."""
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.validation.meaning_assay.fixtures import check_frozen


class GeneratedNativeMeaningTests(unittest.TestCase):
    def test_pinned_format_meanings(self):
        directory = PROJECT / "tests/fixtures/engine/native-meanings/root-a-20261029"
        self.assertEqual(check_frozen(directory), 15552)


if __name__ == "__main__":
    unittest.main()
