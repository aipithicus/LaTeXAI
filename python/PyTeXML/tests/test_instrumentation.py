import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.validation.checkpoint_state import basis_for, compare, observations, observer_source, python_observations
from src.validation.primitive_census import profile, lexical_candidates
from src.validation.probe_runner import run_probe, recorder
from src.validation.tex_trace import list_tree, parse

NONCE = "0123456789abcdef"
PLAN = {"fields": [{"id": "count", "kind": "count", "index": 20},
                   {"id": "width", "kind": "dimen", "index": 20},
                   {"id": "code", "kind": "catcode", "index": 64},
                   {"id": "meaning", "kind": "meaning", "target": "thing"},
                   {"id": "tokens", "kind": "toks", "index": 20}],
        "checkpoints": ["before", "inside", "after"]}
SOURCE = r"""\catcode123=1 \catcode125=2 \catcode35=6 \catcode94=7 \newlinechar=10
\input pytexml-observe.tex
\count20=7 \dimen20=123sp \catcode64=12 \def\thing{old}\toks20={\thing}
\PyTeXMLCheckpoint{before}
{\count20=9 \dimen20=-11sp \catcode64=11 \def\thing{new}\toks20={new}
\PyTeXMLCheckpoint{inside}}
\PyTeXMLCheckpoint{after}
\end
"""


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.basis = basis_for({"main.tex": SOURCE.encode()}, "main.tex", initial_state="initex-selected-state-v1")

    def test_same_observer_captures_state_inside_groups(self):
        result = python_observations({"main.tex": SOURCE}, "main.tex", PLAN, NONCE, self.basis)
        self.assertEqual(result["status"], "complete", result)
        fields = [s["fields"] for s in result["snapshots"]]
        self.assertEqual([f["count"]["value"] for f in fields], [7, 9, 7])
        self.assertEqual([f["width"]["value"] for f in fields], [123, -11, 123])
        self.assertEqual([f["code"]["value"] for f in fields], [12, 11, 12])
        self.assertEqual([f["meaning"]["value"] for f in fields], ["macro:->old", "macro:->new", "macro:->old"])
        self.assertEqual(fields[0]["tokens"]["comparison"], "printed_diagnostic")
        self.assertEqual(compare(result, copy.deepcopy(result))["status"], "matched")
        changed = copy.deepcopy(result)
        changed["snapshots"][1]["fields"]["count"]["value"] = 10
        self.assertEqual(compare(result, changed)["status"], "mismatch")
        for key, value in (("basis", {}), ("selection", {}), ("status", "incomplete"), ("snapshots", [])):
            changed = copy.deepcopy(result)
            changed[key] = value
            self.assertEqual(compare(result, changed)["status"], "not_comparable")
        changed = copy.deepcopy(result)
        changed["snapshots"][0]["occurrence"] = 2
        self.assertEqual(compare(result, changed)["status"], "not_comparable")
        for malformed in ({}, {"count": {"kind": "count", "comparison": "exact_integer", "value": "7"}}):
            changed = copy.deepcopy(result)
            changed["snapshots"][0]["fields"] = malformed
            self.assertEqual(compare(changed, changed)["status"], "not_comparable")

    def test_missing_duplicate_and_wrapped_observations_are_incomplete(self):
        plan = {"fields": [PLAN["fields"][0]], "checkpoints": ["one"]}
        prefix = "PX" + NONCE + ":"
        valid = [prefix + "BEGIN:one", prefix + "FIELD:count:7", prefix + "END:one"]
        for lines in ([], valid[:-1], valid[:2] + valid[1:], valid[:2] + ["continuation"] + valid[2:],
                      [s.replace(":7", ":7X") for s in valid]):
            result = observations(lines, plan, NONCE, self.basis, producer={})
            self.assertEqual(result["status"], "incomplete", lines)
        self.assertEqual(observations(valid, plan, NONCE, self.basis, producer={}, wrap_column=20)["status"], "incomplete")

    def test_undefined_meaning_does_not_create_a_binding(self):
        plan = {"fields": [{"id": "missing", "kind": "meaning", "target": "missing"}], "checkpoints": ["one"]}
        source = r"\catcode123=1 \catcode125=2 \catcode35=6 \catcode94=7 \newlinechar=10 \input pytexml-observe.tex \PyTeXMLCheckpoint{one}\ifcsname missing\endcsname\undefined\fi\end"
        basis = basis_for({"main.tex": source.encode()}, "main.tex", initial_state="initex-selected-state-v1")
        result = python_observations({"main.tex": source}, "main.tex", plan, NONCE, basis)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["snapshots"][0]["fields"]["missing"]["value"], "undefined")

    def test_structured_selectors_reject_tex_injection(self):
        for update in ({"id": "x:y"}, {"kind": "unknown"}, {"index": -1}):
            plan = copy.deepcopy(PLAN)
            plan["fields"][0].update(update)
            with self.assertRaises(ValueError):
                observer_source(plan, NONCE)


class ParserTests(unittest.TestCase):
    def test_void_boxes_and_unterminated_lists(self):
        result = parse("> \\box3=void\n\n! OK.\n", expected_ok=1, marked=False)
        self.assertTrue(result["boxes"][0]["void"])
        with self.assertRaises(ValueError):
            parse("### math mode entered at line 1\n\\mathord\n", marked=False)

    def test_native_math_branches_and_empty_fields(self):
        lines = [r"\mathchoice", r"D\mathord", r"D.\fam0 x", r"T\mathord", "T.{}",
                 r"S\mathord", r"S.\fam0 x", r"s\mathord", r"s.\fam0 x",
                 r"\fraction, thickness = default", r"\\fam0 1", r"/\fam0 2",
                 r"\discretionary", r".\f a", r"|\f b"]
        roots = list_tree(enumerate(lines, 1))
        self.assertEqual([c["path"] for c in roots[0]["children"]], list("DTSs"))
        self.assertEqual(roots[0]["children"][1]["children"][0]["text"], "{}")
        self.assertEqual([c["path"] for c in roots[1]["children"]], ["\\", "/"])
        self.assertEqual([c["path"] for c in roots[2]["children"]], [".", "|"])

    def test_unrecognized_or_abbreviated_nodes_are_never_silently_joined(self):
        for bad in (r"\hbox(0.0+0.0)x0.0 []", ".etc.", "wrapped continuation", r"..\fam0 x"):
            with self.assertRaises(ValueError):
                list_tree([(1, r"\mathord"), (2, bad)])
            issues = []
            roots = list_tree([(1, r"\mathord"), (2, bad)], issues=issues)
            self.assertTrue(issues)
            self.assertEqual(roots[0]["text"], r"\mathord")

    def test_macro_arguments_and_raw_unknown_lines_retained(self):
        log = "\n".join([r"\wrap #1->#1", "#1<-value", "unknown", r"{begin-group character {}"])
        result = parse(log, marked=False)
        self.assertEqual(result["macro_calls"][0]["arguments"][0]["text"], "value")
        self.assertEqual(result["raw_lines"][2]["raw"], "unknown")
        self.assertEqual(result["commands"][0]["command"], "begin-group character {")


class ProfileTests(unittest.TestCase):
    def test_streamed_issue_count_has_bounded_samples(self):
        result = profile(iter(["{broken"] * 100), nonce=NONCE, checkpoints=[])
        self.assertEqual(result["issue_count"], 100)
        self.assertEqual(len(result["issues"]), 30)

    def test_phase_markers_alias_reports_and_blind_spots(self):
        prefix = "PX" + NONCE + ":"
        lines = [r"{vertical mode: \count20}", r"\fake ->" + prefix + "BEGIN:fake",
                 prefix + "BEGIN:body", r"{\number}", prefix + "END:body",
                 r"{\count21}", r"{\number}", "{true}", r"{begin-group character {}"]
        result = profile(iter(lines), nonce=NONCE, checkpoints=["body"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["counts"], {"startup": {"count": 1}, "body": {"count": 1, "number": 1}})
        self.assertEqual(result["excluded_observer_reports"], 1)
        self.assertFalse(result["catalog"].get("fake", {}).get("registered", False))
        self.assertTrue(result["blind_spots"])
        self.assertEqual(profile(lines, nonce=NONCE, checkpoints=["body", "end"])["status"], "incomplete")

    def test_lexical_candidates_are_separate_and_keep_unreadable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.tex"
            path.write_text(r"% \the\the" + "\n" + r"\def\unused{\the}")
            result = lexical_candidates([path, path, Path(tmp) / "missing"], ["the"])
            self.assertEqual(result["counts"], {"the": 3})
            self.assertEqual(len(result["unavailable"]), 1)


class RunnerTests(unittest.TestCase):
    def test_timeout_and_missing_log_remain_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.tex").write_text("manuscript")
            with patch("src.validation.probe_runner.subprocess.run", side_effect=subprocess.TimeoutExpired("tex", .01)):
                receipt = run_probe(source, "main.tex", Path(sys.executable), root / "run", PLAN, initial_state="test")
            self.assertEqual(receipt["status"], "incomplete")
            self.assertEqual(receipt["arms"]["baseline"]["passes"][0]["error"], "timeout")
            self.assertNotEqual(receipt.get("noninterference", {}).get("status"), "observed_equal")

    def test_recorder_preserves_order_duplicates_and_missing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            project, build = root / "project", root / "build"
            project.mkdir()
            build.mkdir()
            (project / "a.tex").write_text("A")
            path = root / "x.fls"
            path.write_text(f"PWD {project}\nINPUT a.tex\nINPUT a.tex\nINPUT missing.tex\nOUTPUT ../build/x.aux\n")
            result = recorder(path, cwd=project, project=project, build=build)
            self.assertEqual(result["status"], "incomplete")
            self.assertEqual([r["path"] for r in result["records"]][1:3], ["project/a.tex"] * 2)

    def test_failed_execution_keeps_a_receipt_and_preserves_source_and_graphics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.tex").write_text("manuscript")
            (source / "figure.pdf").write_bytes(b"graphic")
            with patch("src.validation.probe_runner.subprocess.run", side_effect=OSError("cannot launch")):
                receipt = run_probe(source, "main.tex", Path(sys.executable), root / "run", PLAN, initial_state="test")
            self.assertEqual(receipt["status"], "incomplete")
            self.assertIn("cannot launch", receipt["error"])
            self.assertEqual((source / "main.tex").read_text(), "manuscript")
            self.assertEqual((root / "run/baseline/project/figure.pdf").read_bytes(), b"graphic")
            self.assertEqual(json.loads((root / "run/manifest.json").read_text())["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
