"""Hook execution and residual file events share the existing reader engine."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import ReadingIssue
from src.bindings.resolver import BindingResolver
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader
from src.engine.programs import evaluate


class FileHookTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def prepare(self, body):
        self.put("main.tex", r"\documentclass{article}" + body)
        return preprocess_paper(str(self.root), engine_profile="pdftex")

    def test_macro_registers_both_hooks_and_emits_one_runtime_dispatch(self):
        self.put("sections/math.tex", "BODY\n")
        text, manifest, _, ledger = self.prepare(
            r"\newcommand{\logfile}[1]{\typeout{enter #1}}"
            r"\newcommand{\register}[1]{\AddToHook{file/#1.tex/before}{\logfile{#1}}"
            r"\AddToHook{file/#1.tex/after}{\typeout{leave #1}}}"
            r"\register{math}\begin{document}\input{sections/math}TAIL\end{document}")
        self.assertIn("BODY", text)
        self.assertNotIn(r"\input{sections/math}", text)
        self.assertIn(r"\register{math}", text)
        self.assertEqual(text.count(r"\UseHook{file/before}"), 1)
        event, = manifest.file_events
        self.assertEqual(event["status"], "inlined")
        self.assertEqual([e["diagnostics"] for e in event["events"]], [[], ["enter math"], ["leave math"], []])
        self.assertTrue(any(s.get("derivations") for s in ledger.segments))
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_hook_state_is_applied_before_body_and_after_before_suffix(self):
        self.put("body.tex", r"\ifx\x\expected YES\else WRONG\fi")
        text, manifest, _, _ = self.prepare(
            r"\def\expected{A}\AddToHook{file/body.tex/before}{\def\x{A}}"
            r"\AddToHook{file/body.tex/after}{\def\x{B}}"
            r"\begin{document}\input{body}\def\expected{B}\ifx\x\expected AFTER\else BAD\fi\end{document}")
        self.assertIn("YES", text)
        self.assertIn("AFTER", text)
        self.assertNotIn("WRONG", text)
        self.assertNotIn("BAD", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_alias_and_firing_time_redefinition(self):
        self.put("body.tex", "BODY")
        _, manifest, _, _ = self.prepare(
            r"\let\register\AddToHook\def\msg{old}"
            r"\register{file/body.tex/before}{\typeout{\msg}}\def\msg{new}"
            r"\begin{document}\input{body}\end{document}")
        self.assertEqual(manifest.file_events[0]["events"][1]["diagnostics"], ["new"])

    def test_nested_repeated_inputs_have_distinct_events_and_file_context(self):
        self.put("one/item.tex", r"A\input{two/item}\typeout{back=\CurrentFilePath}")
        self.put("two/item.tex", "B")
        text, manifest, _, _ = self.prepare(
            r"\AddToHook{file/item.tex/before}{\typeout{path=\CurrentFilePath}}"
            r"\begin{document}\input{one/item}\input{two/item}\end{document}")
        self.assertEqual(len(manifest.file_events), 3)
        self.assertEqual(len({e["occurrence"] for e in manifest.file_events}), 3)
        self.assertEqual([e["events"][1]["diagnostics"] for e in manifest.file_events],
                         [["path=two"], ["path=one"], ["path=two"]])
        self.assertEqual(text.count(r"\UseHook{file/before}"), 3)

    def test_hook_group_can_span_the_file_without_an_input_group(self):
        self.put("body.tex", r"\ifx\x\expected LOCAL\else BAD\fi")
        text, manifest, _, _ = self.prepare(
            r"\def\x{outer}\def\expected{inner}"
            r"\AddToHook{file/body.tex/before}{\begingroup\def\x{inner}}"
            r"\AddToHook{file/body.tex/after}{\endgroup}"
            r"\begin{document}\input{body}\def\expected{outer}\ifx\x\expected RESTORED\else BAD\fi\end{document}")
        self.assertIn("LOCAL", text)
        self.assertIn("RESTORED", text)
        self.assertNotIn("BAD", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_before_hook_can_register_the_after_hook(self):
        self.put("body.tex", "BODY")
        _, manifest, _, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{\AddToHook{file/body.tex/after}{\typeout{late}}}"
            r"\begin{document}\input{body}\end{document}")
        self.assertEqual(manifest.file_events[0]["events"][2]["diagnostics"], ["late"])

    def test_unsupported_ordering_retains_the_input(self):
        self.put("body.tex", "BODY")
        text, manifest, output, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}[a]{A}"
            r"\begin{document}\input{body}TAIL\end{document}")
        self.assertIn(r"\input{body}", text)
        self.assertNotIn(r"\UseHook{file/before}", text)
        self.assertTrue((output / "body.tex").is_file())
        self.assertEqual(manifest.file_events[0]["status"], "retained")
        self.assertTrue(any(r["reason"] == "hook_order" for r in manifest.unresolved))

    def test_unknown_body_rolls_back_earlier_registration_effect(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(
            r"\def\register{\AddToHook{file/body.tex/before}{\typeout{wrong}}\unknown}"
            r"\register\begin{document}\input{body}\end{document}")
        self.assertNotIn(r"\UseHook{file/before}", text)
        self.assertEqual(manifest.file_events[0]["status"], "retained")
        self.assertIn(r"\input{body}", text)

    def test_unbraced_input_is_the_kernel_primitive_route(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{WRONG}\begin{document}\input body TAIL\end{document}")
        self.assertEqual(manifest.file_events, [])
        self.assertNotIn(r"\UseHook{file/before}", text)

    def test_recursive_hook_is_bounded_and_retained(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{\UseHook{file/body.tex/before}}"
            r"\begin{document}\input{body}\end{document}")
        self.assertIn(r"\input{body}", text)
        self.assertTrue(any(r["reason"] == "program_budget" for r in manifest.unresolved))

    def test_shadowed_dispatch_is_retained(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{BEFORE}\def\UseHook#1{}"
            r"\begin{document}\input{body}\end{document}")
        self.assertIn(r"\input{body}", text)
        self.assertTrue(any(r["reason"] == "file_hook_dispatch" for r in manifest.unresolved))

    def test_inactive_registration_does_not_fire(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(
            r"\iffalse\AddToHook{file/body.tex/before}{WRONG}\fi"
            r"\begin{document}\input{body}\end{document}")
        self.assertNotIn("WRONG", text)
        self.assertFalse(manifest.file_events[0]["lowered"])

    def test_ordinary_input_stays_compact(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(r"\begin{document}\input{body}TAIL\end{document}")
        self.assertNotIn("UseHook", text)
        self.assertIn("BODY", text)

    def test_macro_arguments_continue_after_a_replacement_frame(self):
        self.put("body.tex", "BODY")
        _, manifest, _, _ = self.prepare(
            r"\def\print#1{\typeout{value=#1}}\def\forward{\print}"
            r"\AddToHook{file/body.tex/before}{\forward{RIGHT}}"
            r"\begin{document}\input{body}\end{document}")
        self.assertEqual(manifest.file_events[0]["events"][1]["diagnostics"], ["value=RIGHT"])

    def test_global_hook_definition_survives_outer_scope(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(
            r"\def\x{old}\AddToHook{file/body.tex/before}{\gdef\x{new}}"
            r"\begin{document}{\input{body}}\def\expected{new}"
            r"\ifx\x\expected GLOBAL\else WRONG\fi\end{document}")
        self.assertIn("GLOBAL", text)
        self.assertNotIn("WRONG", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_emission_failure_retains_input_and_does_not_use_stale_state(self):
        self.put("body.tex", "BODY")
        with patch("src.prepare.session.file_wrappers", side_effect=ReadingIssue("test_emission", "rejected")):
            text, manifest, output, _ = self.prepare(
                r"\def\x{old}\def\expected{old}\AddToHook{file/body.tex/before}{\def\x{new}}"
                r"\begin{document}\input{body}\ifx\x\expected OLD\else NEW\fi\end{document}")
        self.assertIn(r"\input{body.tex}", text)
        self.assertIn("OLD", text)
        self.assertIn("NEW", text)
        self.assertNotIn(r"\UseHook{file/before}", text)
        self.assertTrue((output / "body.tex").is_file())
        self.assertTrue(any(r["reason"] == "test_emission" for r in manifest.unresolved))

    def test_unknown_execution_invalidates_registered_hooks(self):
        self.put("body.tex", "BODY")
        text, manifest, output, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{BEFORE}\unknown"
            r"\begin{document}\input{body}\end{document}")
        self.assertIn(r"\input{body}", text)
        self.assertTrue((output / "body.tex").is_file())
        diagnostic = next(r for r in manifest.unresolved if r["reason"] == "hook_order")
        cause, = [c for c in manifest.uncertainty_causes if c["id"] in diagnostic["cause_ids"]]
        original = (self.root / "main.tex").read_text(encoding="utf-8")
        self.assertEqual(cause["source"], "main.tex")
        self.assertEqual(original[cause["start"]:cause["end"]], r"\unknown")
        self.assertEqual(cause["location_status"], "mapped")

    def test_failed_program_cause_keeps_authored_origin_after_rollback(self):
        self.put("body.tex", "BODY")
        text, manifest, output, _ = self.prepare(
            r"\def\badcopy{\let\hidden\unavailable}"
            r"\AddToHook{file/body.tex/before}{\badcopy\typeout{\hidden}}\input{body}")
        diagnostic = next(r for r in manifest.unresolved if r["reason"] == "uncertain_meaning")
        cause, = [c for c in manifest.uncertainty_causes if c["id"] in diagnostic["cause_ids"]]
        original = (self.root / "main.tex").read_text(encoding="utf-8")
        self.assertEqual(cause["source"], "main.tex")
        self.assertEqual(original[cause["start"]:cause["end"]], r"\let\hidden\unavailable")
        self.assertGreaterEqual(cause["occurrence"], 0)
        self.assertEqual(cause["location_status"], "mapped")
        self.assertIn(r"\input{body}", text)
        self.assertTrue((output / "body.tex").is_file())
        self.assertFalse(any(i.get("generated") for i in manifest.input_occurrences))

    def test_remove_top_level_hook(self):
        self.put("body.tex", "BODY")
        _, manifest, _, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{\typeout{WRONG}}"
            r"\RemoveFromHook{file/body.tex/before}"
            r"\begin{document}\input{body}\end{document}")
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertEqual(manifest.file_events[0]["events"][1]["diagnostics"], [])

    def test_next_use_hook_retains_input(self):
        self.put("body.tex", "BODY")
        text, manifest, _, _ = self.prepare(
            r"\AddToHookNext{file/body.tex/before}{ONCE}"
            r"\begin{document}\input{body}\end{document}")
        self.assertIn(r"\input{body}", text)
        self.assertTrue(any(r["reason"] == "hook_order" for r in manifest.unresolved))

    def test_context_read_without_hooks_requires_residual_context(self):
        self.put("body.tex", r"\typeout{file=\CurrentFile}BODY")
        text, manifest, _, _ = self.prepare(r"\begin{document}\input{body}\end{document}")
        self.assertTrue(manifest.file_events[0]["lowered"])
        self.assertIn("filehook@file@push", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_unknown_body_effects_leave_subsequent_assignment_scope_unresolved(self):
        self.put("body.tex", r"\showfile\def\CurrentFile{changed}")
        text, manifest, _, _ = self.prepare(
            r"\def\showfile{Context \CurrentFile}"
            r"\begin{document}\input{body}\end{document}")
        self.assertFalse(manifest.file_events[0]["lowered"])
        self.assertIn(r"\input{body.tex}", text)
        self.assertIn(r"\showfile", text)
        self.assertTrue(any(r["reason"] == "uncertain_integer" and "globaldefs" in r["detail"]
                            for r in manifest.unresolved), manifest.unresolved)

    def test_hooked_include_retains_its_own_protocol(self):
        self.put("body.tex", "BODY")
        text, manifest, output, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{BEFORE}"
            r"\begin{document}\include{body}\end{document}")
        self.assertIn(r"\include{body}", text)
        self.assertNotIn(r"\clearpage", text)
        self.assertTrue((output / "body.tex").is_file())
        self.assertTrue(any(r["reason"] == "file_hook_entrypoint" for r in manifest.unresolved))

    def test_active_helper_punctuation_retains_input(self):
        self.put("body.tex", "BODY")
        text, manifest, output, _ = self.prepare(
            r"\AddToHook{file/body.tex/before}{BEFORE}\catcode95=13 "
            r"\begin{document}\input{body}\end{document}")
        self.assertIn(r"\input{body}", text)
        self.assertTrue((output / "body.tex").is_file())
        self.assertTrue(any(r["reason"] == "file_hook_serialization" for r in manifest.unresolved))

    def test_nested_programs_share_one_work_budget_and_rollback(self):
        resolver = BindingResolver()
        context = resolver.new_context()
        reader = TexReader(r"\AddToHook{leaf}{abcdefghij}"
            r"\AddToHook{branch}{\UseHook{leaf}\UseHook{leaf}}"
            r"\UseHook{branch}\UseHook{branch}", catcodes=context.catcodes, endline_char=context.endlinechar)
        host = StructuralDispatcher(reader, context, resolver, preparation=True, source_commands=True)
        tokens = []
        while (token := reader.next_token()) is not None:
            tokens.append(token)
        with self.assertRaises(ReadingIssue) as caught:
            evaluate(host, tokens, reader.basis.whole, budget=30)
        self.assertEqual(caught.exception.reason, "program_budget")
        self.assertEqual(context.hooks.code, {})
        self.assertEqual(host.program_sources, [])


if __name__ == "__main__":
    unittest.main()
