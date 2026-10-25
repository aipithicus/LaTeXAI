"""Witnessed diagnostics, lossless wrapping evidence, and derived assessment."""
from copy import deepcopy
from pathlib import Path
import re
import sys
import tempfile
import unittest

import yaml

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.validation.diagnostics import load_rules, normalize_log, parse_log, audit_diagnostics
from src.validation.assessment import summarize, baseline_comparison

FIXTURES = Path(__file__).parent / "fixtures/validation"


def witnessed(name):
    return (FIXTURES / name).read_bytes()


def run_evidence(log=b"", *, format="pdf", execution="failed", audit="not_requested", output="not_run"):
    diagnostics = parse_log(log)["diagnostics"]
    checks = {"execution": {"outcome": execution}, "output_inspection": {"outcome": output},
              "dependency_audit": {"outcome": audit}, "tex_compilation": {"outcome": "not_run"},
              "pdf_generation": {"outcome": "not_run"}}
    for diagnostic in diagnostics:
        if diagnostic["severity"] == "error" and diagnostic["phase"] in checks:
            checks[diagnostic["phase"]]["outcome"] = "failed"
    return {"format": format, "checks": checks, "diagnostics": diagnostics, "input_fingerprint": "fixture-payload"}


class DiagnosticTests(unittest.TestCase):
    def test_witnessed_repeats_coalesce_without_losing_occurrences(self):
        raw = witnessed("font-unavailable.txt")
        result = parse_log(raw)
        primary = next(d for d in result["diagnostics"] if d["code"] == "pdf.font_resource_unavailable")
        self.assertEqual(primary["details"], {"font": "bbm12"})
        self.assertEqual(len(primary["evidence"]), 2)
        self.assertTrue(next(d for d in result["diagnostics"] if d["code"] == "pdf.driver_failure")["related"])
        for diagnostic in result["diagnostics"]:
            for evidence in diagnostic["evidence"]:
                self.assertEqual(raw[evidence["byte_start"]:evidence["byte_end"]].decode(), evidence["raw"])

    def test_79_column_wraps_rejoin_tokens_and_track_original_bytes(self):
        filename = "nested/" + "very_long_filename_" * 9 + "master.tex"
        text = f"error: {filename}:27: LaTeX Error: Option clash for package xcolor."
        raw = ("\r\n".join(text[i:i+79] for i in range(0, len(text), 79)) + "\r\n").encode()
        result = parse_log(raw)
        diagnostic, = result["diagnostics"]
        evidence, = diagnostic["evidence"]
        self.assertEqual(diagnostic["code"], "tex.package_option_clash")
        self.assertEqual(evidence["message"], text)
        self.assertEqual(evidence["location"]["file"], filename)
        self.assertEqual(evidence["raw"].encode(), raw)
        self.assertGreater(len(evidence["inferred_joins"]), 1)

    def test_wraps_inside_resource_name_are_not_replaced_with_spaces(self):
        font = "a" * 80
        text = f'warning: Could not locate a virtual/physical font for TFM "{font}".'
        raw = ("\n".join(text[i:i+79] for i in range(0, len(text), 79)) + "\n").encode()
        self.assertEqual(parse_log(raw)["diagnostics"][0]["details"]["font"], font)
        chatter = "(./" + "x" * 110 + ".tex)"
        raw = (chatter[:79] + "\n" + chatter[79:] + "\n").encode()
        self.assertEqual(normalize_log(raw)[0]["text"], chatter)
        self.assertEqual(parse_log(raw)["diagnostics"], [])

    def test_wrapper_prefix_does_not_hide_an_underlying_tex_wrap(self):
        message = 'LaTeX Error: Option clash for package ' + 'long' * 30 + '.'
        prefix = 'error: C:/paper/master.tex:25: '
        raw = (prefix + '\n'.join(message[i:i+79] for i in range(0, len(message), 79)) + '\n').encode()
        diagnostic, = parse_log(raw)["diagnostics"]
        self.assertEqual(diagnostic["details"]["package"], 'long' * 30)
        self.assertEqual(diagnostic["evidence"][0]["location"]["file"], 'C:/paper/master.tex')

    def test_real_boundaries_at_79_and_short_lines_are_not_glued(self):
        first = "! " + "x" * 77
        raw = (first + "\nerror: a separate diagnostic\nl.8 a source excerpt\n\n" +
               "warning: short\ncontinuation without wrapping evidence\n").encode()
        records = normalize_log(raw)
        self.assertEqual(len(records), 6)
        self.assertTrue(all(not record["inferred_joins"] for record in records))
        self.assertEqual(len(parse_log(raw)["diagnostics"]), 3)

    def test_context_text_does_not_become_a_diagnostic_and_bad_bytes_survive(self):
        raw = b'l.9 \\message{LaTeX Error: Option clash for package fake.}\nerror: unknown \xff\n'
        result = parse_log(raw)
        self.assertEqual(result["undecodable_bytes"], 1)
        diagnostic, = result["diagnostics"]
        self.assertEqual(diagnostic["code"], "log.unclassified")
        evidence, = diagnostic["evidence"]
        self.assertEqual(evidence["raw"].encode("utf-8", "surrogateescape"), raw[evidence["byte_start"]:])

    def test_resource_identity_duplicate_codes_regex_and_witnesses_are_validated(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            for mutate in (lambda d: d["identity"].update(name="wrong"),
                           lambda d: d["rules"].append(d["rules"][0]),
                           lambda d: d["rules"][0].update(patterns=["["]),
                           lambda d: d["rules"][0].update(severity="guess"),
                           lambda d: d.update(unknown="field"),
                           lambda d: d["rules"][0].update(witnesses=[])):
                data = deepcopy(load_rules())
                mutate(data)
                (root / "tectonic.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
                with self.assertRaises((ValueError, re.error)):
                    load_rules(root=root)


class AssessmentTests(unittest.TestCase):
    def test_summary_is_pure_and_ignores_cached_or_tampered_verdicts(self):
        run = run_evidence(execution="passed", audit="passed", output="passed")
        report = {"render": run, "status": "failed", "summary": {"classification": "WRONG"}}
        before = deepcopy(report)
        self.assertEqual(summarize(report)["classification"], "QUALIFIED")
        self.assertEqual(report, before)
        run["checks"]["dependency_audit"]["outcome"] = "inconclusive"
        self.assertEqual(summarize(report)["classification"], "INDETERMINATE")

    def test_font_failure_and_xdv_evidence_do_not_qualify_pdf(self):
        run = run_evidence(witnessed("font-unavailable.txt"))
        report = {"render": run, "xdv_check": run_evidence(format="xdv", execution="passed", audit="passed", output="passed")}
        summary = summarize(report)
        self.assertEqual(summary["classification"], "ENVIRONMENT_LIMITATION")
        self.assertEqual(summary["compilation_isolation"], "qualified")
        self.assertFalse(summary["pdf_qualified"])
        report["xdv_check"]["input_fingerprint"] = "a-different-payload"
        self.assertEqual(summarize(report)["compilation_isolation"], "not_established")
        # A warning alone is not proof of a failed environment capability.
        report = run_evidence(b'warning: Could not locate a virtual/physical font for TFM "bbm12".\n',
                              execution="passed", audit="passed", output="passed")
        self.assertEqual(summarize(report)["classification"], "QUALIFIED")

    def test_baseline_requires_comparability_and_a_specific_matching_failure(self):
        prepared = run_evidence(witnessed("option-clash.txt"))
        original = run_evidence(witnessed("option-clash.txt").replace(b"master.tex:8", b"author.tex:27"))
        self.assertEqual(baseline_comparison(original, prepared)["outcome"], "incomparable")
        match = baseline_comparison(original, prepared, comparable=True)
        self.assertEqual(match["outcome"], "same_failure")
        self.assertEqual(summarize({"render": prepared, "original": original, "paired_configuration": True})["classification"], "BASELINE_REPRODUCED")
        other = run_evidence(witnessed("option-clash.txt").replace(b"xcolor", b"other"))
        self.assertEqual(baseline_comparison(other, prepared, comparable=True)["outcome"], "different_failure")
        generic = run_evidence(b"error: the XeTeX engine had an unrecoverable error\n")
        self.assertEqual(baseline_comparison(generic, generic, comparable=True)["outcome"], "insufficient_evidence")

    def test_baseline_pass_and_multiple_findings_do_not_assign_preparation_blame(self):
        prepared = run_evidence(witnessed("font-unavailable.txt"))
        original = run_evidence(execution="passed", output="passed")
        match = baseline_comparison(original, prepared, comparable=True)
        summary = summarize({"render": prepared, "original": original, "paired_configuration": True})
        self.assertEqual({f["category"] for f in summary["findings"]}, {"ENVIRONMENT_LIMITATION", "PREPARED_ONLY_FAILURE"})

    def test_absent_receipt_is_not_a_leak_but_observed_external_paths_are(self):
        run = run_evidence(execution="passed", output="passed", audit="inconclusive")
        run["diagnostics"] = audit_diagnostics({"status": "missing_receipt", "outside": [], "missing": []})
        self.assertEqual(summarize(run)["classification"], "INDETERMINATE")
        run["checks"]["dependency_audit"]["outcome"] = "failed"
        run["diagnostics"] = audit_diagnostics({"status": "external_dependencies", "outside": ["raw/figure.pdf"], "missing": []})
        self.assertEqual(summarize(run)["classification"], "PAYLOAD_DEPENDENCY_FAILURE")


if __name__ == "__main__":
    unittest.main()
