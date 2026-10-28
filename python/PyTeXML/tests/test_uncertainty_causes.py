"""Uncertainty links survive scope/input changes and point into the final payload."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper


class UncertaintyCauseTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8")

    def prepare(self, text):
        self.put("main.tex", r"\documentclass{article}" + text)
        return preprocess_paper(str(self.root), root_tex="main.tex")

    def test_repeated_source_occurrences_link_distinct_causes_and_master_locations(self):
        self.put("part.tex", r"\newif\ifflag{\unknown}\ifflag YES\else NO\fi")
        text, manifest, _, _ = self.prepare(r"\input{part}\input{part}")
        requirements = [r for r in manifest.requirements if r["reason"] == "conditional_interpretation"]
        self.assertEqual(len(requirements), 2)
        causes = {c["id"]: c for c in manifest.uncertainty_causes}
        linked = [causes[r["cause_ids"][0]] for r in requirements]
        self.assertNotEqual(linked[0]["occurrence"], linked[1]["occurrence"])
        self.assertNotEqual(linked[0]["id"], linked[1]["id"])
        self.assertNotEqual(linked[0]["locations"], linked[1]["locations"])
        for cause in linked:
            self.assertEqual(cause["reason"], "unknown_construct")
            for address in cause["locations"]:
                self.assertEqual(address["artifact"], "master.tex")
                self.assertIn(r"\unknown", text[address["start"]:address["end"]])
        manifest.mark_failed()
        self.assertTrue(all(c["locations"] == [] and c["location_status"] == "pending" for c in manifest.uncertainty_causes))

    def test_retained_package_options_link_to_unknown_operation_in_code_artifact(self):
        self.put("local.sty", r"\unknown\DeclareOption{x}{}\ProcessOptions\relax")
        text, manifest, output, _ = self.prepare(r"\usepackage{local}BODY")
        requirement = next(r for r in manifest.requirements if r["reason"] == "retained_code_reading")
        cause = next(c for c in manifest.uncertainty_causes if c["id"] in requirement["cause_ids"])
        self.assertEqual(cause["reason"], "unknown_construct")
        self.assertTrue(cause["locations"])
        address = cause["locations"][0]
        self.assertIn(r"\unknown", (output / address["artifact"]).read_text()[address["start"]:address["end"]])
        diagnostic = next(r for r in manifest.unresolved if r["reason"] == "uncertain_options")
        self.assertEqual(diagnostic["cause_ids"], requirement["cause_ids"])

    def test_package_cause_and_first_cause_survive_later_unknowns(self):
        _, manifest, _, _ = self.prepare(r"\newif\ifflag\usepackage{notbound}\unknown\ifflag A\else B\fi")
        requirement = next(r for r in manifest.requirements if r["reason"] == "conditional_interpretation")
        cause = next(c for c in manifest.uncertainty_causes if c["id"] in requirement["cause_ids"])
        self.assertEqual(cause["reason"], "package_binding")
        self.assertIn("notbound", cause["detail"])

    def test_no_cause_table_growth_after_format_meanings_become_uncertain(self):
        text, manifest, _, _ = self.prepare(r"\unknown $\expression$ \another")
        # The first unknown invalidates the format's initial active meaning.
        # Subsequent unknowns must not allocate redundant causes.
        self.assertEqual(len(manifest.uncertainty_causes), 1)
        cause = manifest.uncertainty_causes[0]
        self.assertEqual(cause["reason"], "unknown_construct")
        location = cause["locations"][0]
        self.assertEqual(text[location["start"]:location["end"]], r"\unknown")

    def test_option_replay_preserves_the_cause_from_an_unknown_copied_meaning(self):
        self.put("local.sty", r"\let\copy\missing\DeclareOption{x}{\copy}\ProcessOptions")
        _, manifest, _, _ = self.prepare(r"\usepackage[x]{local}BODY")
        requirement = next(r for r in manifest.requirements if r["reason"] == "retained_code_reading")
        cause = next(c for c in manifest.uncertainty_causes if c["id"] in requirement["cause_ids"])
        self.assertEqual(cause["reason"], "assignment_donor")
        self.assertTrue(cause["locations"])


if __name__ == "__main__":
    unittest.main()
