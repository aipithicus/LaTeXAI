"""Reader-backed lint, narrowly justified repairs, and ordered load evidence."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

from src.event_log import read_events
from src.prepare.lint import load_rules, RULE_PATH
from src.prepare.pipeline import preprocess_paper
from src.prepare.session import PreparationUnresolved
from src.prepare.policy import load_policy
from src.reading.contracts import ReadingBoundary
from src.reading.dispatcher import StructuralDispatcher
from src.bindings.resolver import BindingResolver
from src.reading.tex_reader import EventKind, InvalidCharacterError, TexReader
from tests.reader_support import new_reader


PROJECT = Path(__file__).resolve().parents[1]


class ExplicitRecoveryTests(unittest.TestCase):
    def test_reader_requires_exact_failure_and_preserves_state(self):
        reader = new_reader("a\x7fb", endline_char=-1)
        self.assertEqual(reader.next_token().value, "a")
        with self.assertRaises(InvalidCharacterError) as caught:
            reader.next_event()
        with self.assertRaises(ValueError):
            reader.discard_invalid_character(InvalidCharacterError("\x7f", caught.exception.span))
        recovered = reader.discard_invalid_character(caught.exception)
        self.assertEqual(recovered.kind, EventKind.RECOVERED_INVALID)
        self.assertEqual(recovered.state_before, recovered.state_after)
        self.assertEqual([t.value for t in reader], ["b"])
        with self.assertRaises(ValueError):
            reader.discard_invalid_character(caught.exception)

    def test_dispatcher_exposes_ordinary_failure_but_not_partial_scanner_failure(self):
        for source, resumable in (("a\x7fb", True), (r"\def\foo{a" + "\x7f" + "b}", False),
                                  (r"\iffalse a" + "\x7f" + r"b\fi", False)):
            with self.subTest(source=source):
                resolver = BindingResolver()
                context = resolver.new_context()
                context.endlinechar = -1
                reader = TexReader(source, catcodes=context.catcodes, endline_char=-1)
                dispatcher = StructuralDispatcher(reader, context, resolver)
                boundary = list(dispatcher)[-1]
                self.assertIsInstance(boundary, ReadingBoundary)
                self.assertEqual(dispatcher.lexical_failure(boundary) is not None, resumable)
                if resumable:
                    dispatcher.discard_invalid_character(boundary)
                    self.assertEqual(dispatcher.next_item().token.value, "b")
                else:
                    with self.assertRaises(ValueError):
                        dispatcher.discard_invalid_character(boundary)


class PreparationLintTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "prepared"

    def put(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def policy(self, mode="repair", repairs=None):
        path = self.root / "lint.yaml"
        path.write_text(yaml.safe_dump({"identity": {"name": "lint"}, "linting": {
            "mode": mode, "repairs": ["drop_invalid_character"] if repairs is None else repairs}}), encoding="utf-8")
        return str(path)

    def prepare(self, source, *, mode="report", repairs=None, **kwargs):
        self.put("main.tex", "\\documentclass{article}\n" + source)
        return preprocess_paper(str(self.source), str(self.output), root_tex="main.tex",
                                policy=self.policy(mode, repairs), **kwargs)

    def test_report_only_preserves_invalid_source_and_proposes_checked_edit(self):
        text, manifest, _, _ = self.prepare("alpha\x7fbeta")
        self.assertIn("alpha\x7fbeta", text)
        finding = manifest.lint["findings"][0]
        self.assertEqual(finding["code"], "source.invalid_character")
        self.assertEqual(finding["repair"]["status"], "proposed")
        self.assertTrue(finding["repair"]["checked"])
        loc = finding["locations"][0]
        self.assertEqual(text[loc["start"]:loc["end"]], "\x7f")
        self.assertEqual(manifest.preparation_status, "partial")

    def test_repair_resumes_discovery_and_maps_edit_without_original_mutation(self):
        self.put("part.tex", "INCLUDED")
        text, manifest, output, ledger = self.prepare("alpha\x7fbeta\\input{part}", mode="repair")
        self.assertIn("alphabeta", text)
        self.assertIn("INCLUDED", text)
        self.assertIn("\x7f", (self.source / "main.tex").read_text())
        self.assertEqual(manifest.preparation_status, "complete")
        finding = manifest.lint["findings"][0]
        self.assertEqual(finding["repair"]["status"], "applied")
        location = finding["locations"][0]
        self.assertEqual(location["start"], location["end"])
        self.assertEqual(text[location["start"] - 1:location["start"] + 1], "ab")
        self.assertTrue(any(t.src_start == finding["start"] and t.src_end == finding["end"]
                            and "lint" in t.reason for t in ledger.tombstones))
        event = next(e for e in read_events(output / "preparation.jsonl") if e["code"] == "lint.finding")
        self.assertEqual(event["data"]["id"], finding["id"])
        self.assertEqual(event["locations"][0]["basis"], "artifact")
        self.assertTrue(event["locations"][0]["sha256"])
        # Second preparation is idempotent; there is no remaining repair to apply.
        rerun, clean, _, _ = preprocess_paper(str(output), str(self.root / "again"), root_tex="master.tex",
                                             policy=self.policy())
        # Input-EOF whitespace serialization is not a byte-level fixed point;
        # the repaired token stream and the absence of further repairs are.
        self.assertEqual([(t.kind, t.value, t.catcode) for t in new_reader(text)],
                         [(t.kind, t.value, t.catcode) for t in new_reader(rerun)])
        self.assertEqual(clean.lint["findings"], [])

    def test_repair_needs_allowlist_and_works_without_provenance_sidecar(self):
        text, manifest, _, _ = self.prepare("a\x7fb", mode="repair", repairs=[])
        self.assertIn("\x7f", text)
        self.assertEqual(manifest.lint["findings"][0]["repair"]["status"], "proposed")
        text, manifest, _, ledger = self.prepare("a\x7fb", mode="repair", emit_provenance=False)
        self.assertNotIn("\x7f", text)
        self.assertIsNone(ledger)
        self.assertTrue(manifest.lint["findings"][0]["locations"])

    def test_reading_categories_determine_eligibility(self):
        text, manifest, _, _ = self.prepare(r"\catcode`\!=15 a!b", mode="repair")
        self.assertIn("ab", text)
        self.assertEqual(manifest.lint["findings"][0]["repair"]["before"], "!")
        text, manifest, _, _ = self.prepare(r"\catcode127=12 a" + "\x7f" + "b", mode="repair")
        self.assertIn("\x7f", text)
        self.assertEqual(manifest.lint["findings"], [])

    def test_unsafe_joins_synthetic_spelling_and_unknown_context_stay_unchanged(self):
        for source in ("^\x7f^41", r"a^^7fb", "\x7fb", "a\x7f", r"\foo a" + "\x7fb",
                       r"\usepackage{unbound}a" + "\x7fb", "a\x7f\nb", "a\x7f\x7fb",
                       r"\catcode13=15 a" + "\rb"):
            with self.subTest(source=source):
                _, manifest, _, _ = self.prepare(source, mode="repair")
                finding = next(f for f in manifest.lint["findings"] if f["reason"] == "invalid_character")
                self.assertEqual(finding["repair"]["status"], "ineligible")
                self.assertIsNotNone(finding["repair"]["rejection_reason"])

    def test_protected_regions_are_never_repaired_as_ordinary_source(self):
        for source in ("\\verb|a\x7fb|", "\\def\\foo{a\x7fb}", "\\iffalse a\x7fb\\fi",
                       "$a\x7fb$", "\\unknown{a\x7fb}"):
            with self.subTest(source=source):
                text, manifest, _, _ = self.prepare(source, mode="repair")
                self.assertIn("\x7f", text)
                self.assertFalse(any(f["repair"]["status"] == "applied" for f in manifest.lint["findings"]))
        text, manifest, _, _ = self.prepare("% a\x7fb\nBODY", mode="repair")
        self.assertNotIn("\x7f", text)  # ordinary comment policy, not a lint repair
        self.assertEqual(manifest.lint["findings"], [])

    def test_retained_local_code_is_reported_without_edit(self):
        self.put("local.sty", "a\x7fb")
        _, manifest, output, _ = self.prepare(r"\usepackage{local}AFTER", mode="repair")
        self.assertEqual((output / "local.sty").read_text(), "a\x7fb")
        finding = next(f for f in manifest.lint["findings"] if f["reason"] == "invalid_character")
        self.assertEqual(finding["repair"]["status"], "ineligible")
        self.assertEqual(finding["locations"][0]["artifact"], "local.sty")

    def test_repeated_inputs_have_distinct_lint_and_occurrence_ids(self):
        self.put("part.tex", "a\x7fb")
        text, manifest, _, _ = self.prepare(r"\input{part}\input{part}", mode="repair")
        findings = manifest.lint["findings"]
        self.assertEqual(len(findings), 2)
        self.assertEqual(len({f["id"] for f in findings}), 2)
        self.assertEqual(len({f["occurrence"] for f in findings}), 2)
        self.assertTrue(all(f["repair"]["status"] == "applied" for f in findings))
        self.assertEqual(text.count("ab"), 2)

    def test_repair_rolled_back_by_later_boundary_is_not_claimed_as_emitted(self):
        self.put("part.tex", "a\x7fb\\catcode\\computed=12")
        text, manifest, output, _ = self.prepare(r"\input{part}AFTER", mode="repair")
        finding = next(f for f in manifest.lint["findings"] if f["reason"] == "invalid_character")
        self.assertEqual(finding["repair"]["status"], "not_emitted")
        self.assertIn(r"\input{part.tex}", text)
        self.assertEqual((output / "part.tex").read_text(), "a\x7fb\\catcode\\computed=12")

    def test_later_failure_never_claims_a_published_repair(self):
        with self.assertRaises(PreparationUnresolved):
            self.prepare("a\x7fb\\input{missing}", mode="repair")
        manifest = json.loads((self.output / "manifest.json").read_text())
        finding = manifest["lint"]["findings"][0]
        self.assertEqual(finding["repair"]["status"], "not_published")
        self.assertEqual(finding["locations"], [])

    def test_publication_failure_clears_repair_cursors_and_related_load_locations(self):
        self.put("wrapper.sty", r"\RequirePackage[a]{xcolor}")
        rename = os.replace
        def fail(source, target):
            if Path(source).name == "payload":
                raise OSError("publication fault")
            return rename(source, target)
        with patch("src.prepare.publication.os.replace", fail), self.assertRaisesRegex(OSError, "publication fault"):
            self.prepare("alpha\x7fbeta" + r"\usepackage{wrapper}\usepackage[b]{xcolor}", mode="repair")
        manifest = json.loads((self.output / "manifest.json").read_text())
        findings = manifest["lint"]["findings"]
        repair = next(f for f in findings if f["reason"] == "invalid_character")
        clash = next(f for f in findings if f["reason"] == "option_clash")
        related, = clash["evidence"]["related"]
        self.assertEqual(repair["repair"]["status"], "not_published")
        self.assertTrue(repair["repair"]["postcondition_verified"])
        self.assertEqual(related["source"], "wrapper.sty")
        self.assertNotEqual(related["unit_id"], clash["unit_id"])
        for record in [repair, clash, related]:
            self.assertEqual((record["location_status"], record["locations"]), ("pending", []))
        self.assertEqual(manifest["prepared_artifacts"], [])
        self.assertFalse((self.output / "master.tex").exists())

    def test_final_postcondition_is_checked_before_publication(self):
        from src.prepare.lint import PreparationLint
        finalize = PreparationLint.finalize_repairs
        def changed(lint, pieces, master):
            return finalize(lint, pieces, master.replace("ab", "xy"))
        with patch.object(PreparationLint, "finalize_repairs", changed), self.assertRaisesRegex(ValueError, "postcondition"):
            self.prepare("a\x7fb", mode="repair")
        self.assertFalse((self.output / "master.tex").exists())

    def test_structural_findings_are_located_and_never_guess_repairs(self):
        for source, code in (("{body", "source.group_structure"),
                             (r"\iffalse hidden", "source.conditional_structure"),
                             (r"\verb|unterminated", "source.literal_structure"),
                             ("$unfinished", "source.math_structure"),
                             (r"\def\foo{body", "source.argument_structure")):
            with self.subTest(source=source):
                _, manifest, _, _ = self.prepare(source, mode="repair")
                finding = next(f for f in manifest.lint["findings"] if f["code"] == code)
                self.assertTrue(finding["locations"])
                self.assertIsNone(finding["repair"]["name"])

    def test_off_mode_keeps_existing_unresolved_reporting(self):
        _, manifest, _, _ = self.prepare("a\x7fb", mode="off")
        self.assertEqual(manifest.lint["findings"], [])
        self.assertTrue(manifest.unresolved)

    def test_option_clash_links_transitive_first_load_and_new_options(self):
        self.put("wrapper.sty", r"\RequirePackage[table]{xcolor}")
        source = r"\usepackage{wrapper}\usepackage[dvipsnames]{xcolor}BODY"
        text, manifest, output, _ = self.prepare(source, mode="repair")
        finding = next(f for f in manifest.lint["findings"] if f["code"] == "source.package_option_clash")
        self.assertEqual(finding["evidence"]["initial_options"], ["table"])
        self.assertEqual(finding["evidence"]["added_options"], ["dvipsnames"])
        self.assertFalse(finding["evidence"]["automatic_repair"])
        related = finding["evidence"]["related"][0]
        self.assertEqual(related["locations"][0]["artifact"], "wrapper.sty")
        self.assertEqual(finding["locations"][0]["artifact"], "master.tex")
        self.assertIn(r"\usepackage[dvipsnames]{xcolor}", text)
        self.assertEqual((output / "wrapper.sty").read_text(), r"\RequirePackage[table]{xcolor}")

    def test_option_subsets_and_forwarded_options_do_not_produce_false_clashes(self):
        for source in (r"\usepackage[a,b]{xcolor}\usepackage[a]{xcolor}",
                       r"\PassOptionsToPackage{b}{xcolor}\usepackage[a]{xcolor}\usepackage[b]{xcolor}",
                       r"\iffalse\usepackage[a]{xcolor}\fi\usepackage[b]{xcolor}",
                       r"\def\later{\usepackage[a]{xcolor}}\usepackage[b]{xcolor}"):
            with self.subTest(source=source):
                _, manifest, _, _ = self.prepare(source)
                self.assertFalse(any(f["reason"] == "option_clash" for f in manifest.lint["findings"]))

    def test_late_forwarding_is_review_only_with_load_anchor(self):
        _, manifest, _, _ = self.prepare(r"\usepackage{xcolor}\PassOptionsToPackage{table}{xcolor}")
        finding = next(f for f in manifest.lint["findings"] if f["reason"] == "option_lifecycle")
        self.assertEqual(finding["evidence"]["requested_options"], ["table"])
        self.assertTrue(finding["evidence"]["related"][0]["locations"])
        self.assertEqual(finding["repair"]["status"], "not_available")

    def test_multi_package_clashes_are_separate_findings(self):
        _, manifest, _, _ = self.prepare(r"\usepackage[a]{foo,bar}\usepackage[b]{foo,bar}")
        clashes = [f for f in manifest.lint["findings"] if f["reason"] == "option_clash"]
        self.assertEqual({f["evidence"]["target"] for f in clashes}, {"foo", "bar"})

    def test_policy_and_catalog_validation_reject_unknown_contracts(self):
        path = Path(self.policy())
        base = yaml.safe_load(path.read_text())
        for config in ({"mode": "guess"}, {"repairs": ["close_braces"]}, {"enabled": True},
                       {"repairs": ["drop_invalid_character", "drop_invalid_character"]}):
            with self.subTest(config=config):
                path.write_text(yaml.safe_dump({**base, "linting": config}), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "linting"):
                    load_policy(path)
        rules = yaml.safe_load(RULE_PATH.read_text())
        rules["rules"][1]["reasons"] = rules["rules"][0]["reasons"]
        bad = self.root / "preparation.yaml"
        bad.write_text(yaml.safe_dump(rules), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate lint reason"):
            load_rules(bad)


if __name__ == "__main__":
    unittest.main()
