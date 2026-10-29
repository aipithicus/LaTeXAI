"""Current kernel load-marker meanings control requests, including after writes."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper


class LoadMarkerTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        folder = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def put(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8", newline="\n")

    def prepare(self, source):
        self.put("main.tex", r"\documentclass{article}\makeatletter" + source)
        return preprocess_paper(str(self.root), root_tex="main.tex")

    def queries(self, manifest):
        return [d for d in manifest.conditional_decisions if d["predicate"] == "loaded"]

    def test_author_marker_suppresses_source_and_binding_activation(self):
        self.put("gmfake.sty", r"\catcode\bad=12 NEVER READ")
        text, manifest, _, ledger = self.prepare(
            r"\expandafter\def\csname ver@gmfake.sty\endcsname{}"
            r"\usepackage{gmfake}\@ifpackageloaded{gmfake}{YES}{NO}")
        self.assertFalse([o for o in manifest.input_occurrences if o["source"] == "gmfake.sty"])
        self.assertNotIn("gmfake", [p.name for p in manifest.packages_declared])
        self.assertFalse(any(r["reason"] == "package_binding" for r in manifest.requirements))
        self.assertEqual([d["truth"] for d in self.queries(manifest)], [True])
        self.assertTrue(self.queries(manifest)[0]["definition_unit_ids"])
        self.assertIn("YES", text)
        self.assertNotIn("NO", text)
        self.assertFalse([s for s in ledger.source_coverage if s["unaccounted"]])

    def test_explicit_relax_reopens_a_previously_read_package(self):
        self.put("local.sty", r"\def\packagevalue{read}")
        _, manifest, _, _ = self.prepare(
            r"\usepackage{local}\@ifpackageloaded{local}{YES}{NO}"
            r"\expandafter\let\csname ver@local.sty\endcsname\relax"
            r"\@ifpackageloaded{local}{NO}{YES}\usepackage{local}"
            r"\@ifpackageloaded{local}{YES}{NO}\usepackage{local}")
        self.assertEqual([d["truth"] for d in self.queries(manifest)], [True, False, True])
        self.assertEqual(len([o for o in manifest.input_occurrences if o["source"] == "local.sty"]), 2)
        self.assertEqual(manifest.source_reads.count("local.sty"), 1)

    def test_local_marker_restores_and_a_real_load_is_global(self):
        self.put("local.sty", r"\def\packagevalue{read}")
        _, manifest, _, _ = self.prepare(
            r"{\expandafter\def\csname ver@local.sty\endcsname{}\usepackage{local}}"
            r"\@ifpackageloaded{local}{NO}{YES}"
            r"{\usepackage{local}}\@ifpackageloaded{local}{YES}{NO}\usepackage{local}")
        self.assertEqual([d["truth"] for d in self.queries(manifest)], [False, True])
        self.assertEqual(len([o for o in manifest.input_occurrences if o["source"] == "local.sty"]), 1)

    def test_alias_to_undefined_is_absence_not_a_historical_loaded_flag(self):
        self.put("local.sty", r"\def\packagevalue{read}")
        _, manifest, _, _ = self.prepare(
            r"\usepackage{local}\let\unset\undefined"
            r"\expandafter\let\csname ver@local.sty\endcsname\unset"
            r"\@ifpackageloaded{local}{NO}{YES}\usepackage{local}")
        self.assertEqual([d["truth"] for d in self.queries(manifest)], [False])
        self.assertEqual(len([o for o in manifest.input_occurrences if o["source"] == "local.sty"]), 2)

    def test_marker_only_request_with_options_reports_a_located_clash(self):
        _, manifest, _, _ = self.prepare(
            r"\expandafter\def\csname ver@gmfake.sty\endcsname{}\usepackage[extra]{gmfake}")
        self.assertTrue(any(r["reason"] == "option_clash" for r in manifest.unresolved))
        self.assertFalse([u for u in manifest.units if u["location_status"] == "unmapped"])

    def test_unknown_marker_keeps_possible_source_without_executing_it(self):
        self.put("broken.sty", r"\catcode\unknown=12")
        self.put("local.sty", r"\def\notexecuted{READ}")
        text, manifest, output, _ = self.prepare(r"\usepackage{broken}\usepackage{local} TAIL")
        requirement, = [r for r in manifest.requirements if r["reason"] == "package_load_state"]
        self.assertTrue(requirement["cause_ids"])
        self.assertEqual(requirement["materialization"], "prepared")
        self.assertTrue((output / "local.sty").is_file())
        self.assertFalse([o for o in manifest.input_occurrences if o["source"] == "local.sty"])
        self.assertIn("TAIL", text)


if __name__ == "__main__":
    unittest.main()
