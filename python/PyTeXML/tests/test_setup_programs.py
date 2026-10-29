"""Setup requests execute complete token programs and preserve runtime source."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.resolver import BindingResolver
from src.engine.programs import evaluate, SETUP
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import ReadingIssue
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader


class SetupProgramTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def prepare(self, source, **files):
        for name, text in {"main.tex": source, **files}.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        return preprocess_paper(str(self.root), root_tex="main.tex")

    def test_optional_empty_invocation_does_not_invalidate_file_hooks(self):
        source = (r"\documentclass{article}\renewcommand{\documentclass}[2][]{}"
                  r"\AddToHook{file/math.tex/before}{\typeout{RIGHT}}"
                  r"\input{body/paper}")
        text, manifest, _, _ = self.prepare(source, **{
            "body/paper.tex": r"\documentclass[11pt]{unused}\input{sections/math}",
            "sections/math.tex": "MATH"})
        self.assertIn(r"\documentclass[11pt]{unused}", text)
        self.assertIn("MATH", text)
        self.assertNotIn(r"\input{body/paper}", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        event = next(e for e in manifest.file_events if e["resolved"] == "sections/math.tex")
        self.assertEqual(event["events"][1]["diagnostics"], ["RIGHT"])

    def test_braced_input_eof_defaults_and_publishes_a_return_barrier(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\newcommand{\opt}[1][default]{\gdef\Observed{#1}}"
            r"\input{child}[caller]\def\Expected{default}\ifx\Observed\Expected YES\else NO\fi",
            **{"child.tex": r"\opt%"})
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertNotIn(r"\input{child}", text)
        self.assertIn("\\opt%\n\\relax", text)
        self.assertIn("YES", text)
        self.assertNotIn("NO", text)

    def test_definition_factory_parameters_and_aliases_reach_the_reader(self):
        invocation = r"\install[chosen]{\value}"
        source = (r"\documentclass{article}\newcommand{\factory}[2][default]{\def#2{#1}}"
                  r"\let\install\factory" + invocation +
                  r"\def\expected{chosen}\ifx\value\expected RIGHT\else WRONG\fi")
        text, manifest, _, _ = self.prepare(source)
        self.assertIn(invocation, text)
        self.assertEqual(text.count(invocation), 1)
        self.assertIn("RIGHT", text)
        self.assertNotIn("WRONG", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        generated = [r for r in manifest.input_occurrences if r.get("generated")]
        self.assertTrue(any(r["derivation"]["invocation"]["source"] == "main.tex" for r in generated))

    def test_eof_optional_body_cannot_change_its_published_barrier(self):
        text, manifest, output, _ = self.prepare(
            r"\documentclass{article}\newcommand{\opt}[1][default]{\def\relax{SIDE}}"
            r"\input{child}[caller]", **{"child.tex": r"\opt"})
        self.assertIn(r"\input{child.tex}", text)
        self.assertNotIn(r"\opt\relax", text)
        self.assertTrue((output / 'child.tex').is_file())
        self.assertTrue(any(r['reason'] == 'input_return_barrier' for r in manifest.unresolved))

    def test_factory_constructs_names_with_existing_expansion_operations(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\def\factory#1#2{\expandafter\def\csname #1\endcsname{#2}}"
            r"\factory{value}{A}\def\expected{A}\ifx\value\expected YES\else BAD\fi")
        self.assertIn("YES", text)
        self.assertNotIn("BAD", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_optional_default_empty_and_brace_protected_delimiter(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\newcommand{\work}[2][default]{\def#2{#1}}"
            r"\work{\a}\work[]{\b}\work[{]}]{\c}"
            r"\def\da{default}\def\db{}\def\dc{]}"
            r"\ifx\a\da DEFAULT\else BAD\fi"
            r"\ifx\b\db EMPTY\else BAD\fi"
            r"\ifx\c\dc BRACED\else BAD\fi")
        for witness in ("DEFAULT", "EMPTY", "BRACED"):
            self.assertIn(witness, text)
        self.assertNotIn("BAD", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_optional_wrapper_is_not_promoted_to_pure_expansion(self):
        _, manifest, _, _ = self.prepare(
            r"\documentclass{article}\newcommand{\optional}[1][default]{#1}"
            r"\edef\value{\optional[x]}")
        self.assertTrue(any(r["reason"] == "macro_parameters" for r in manifest.unresolved))

    def test_optional_lookahead_cannot_assume_default_at_child_eof(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\def\chosen{old}"
            r"\newcommand{\picksetup}[1][default]{\gdef\chosen{#1}}"
            r"\input child [caller]\def\expected{caller}"
            r"\ifx\chosen\expected CORRECT\else WRONG\fi", **{"child.tex": r"\picksetup"})
        self.assertIn("CORRECT", text)
        self.assertIn("WRONG", text)
        self.assertTrue(any(r["reason"] == "argument_lookahead" for r in manifest.unresolved))
        self.assertIn(r"\input child [caller]", text)

    def test_unverified_declaration_inside_setup_is_not_silently_installed(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\def\install#1{\newcommand{#1}{A}}"
            r"\install{\unseen}\ifdefined\unseen YES\else NO\fi")
        self.assertIn("YES", text)
        self.assertIn("NO", text)
        self.assertTrue(any(r["reason"] == "stored_macro" for r in manifest.requirements))

    def test_published_uncertain_assignment_has_a_stable_causal_invocation(self):
        invocation = r"\install{\hidden}"
        source = (r"\documentclass{article}\def\install#1{\let#1\unavailable}"
                  + invocation + r"\typeout{\hidden}")
        _, manifest, _, _ = self.prepare(source)
        diagnostic = next(r for r in manifest.unresolved if r["reason"] == "uncertain_meaning")
        cause, = [c for c in manifest.uncertainty_causes if c["id"] in diagnostic["cause_ids"]]
        self.assertEqual(source[cause["start"]:cause["end"]], invocation)
        self.assertEqual(cause["reason"], "assignment_donor")
        self.assertEqual(cause["location_status"], "mapped")
        self.assertGreaterEqual(cause["occurrence"], 0)

    def test_scopes_global_writes_and_definitions_after_writes(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\def\x{old}\def\z{old}\def\work#1{\begingroup\def\x{local}"
            r"\gdef\y{#1}\endgroup\let\z\y}"
            r"{\work{new}}\def\old{old}\def\new{new}"
            r"\ifx\x\old LOCALRESTORED\else BAD\fi"
            r"\ifx\y\new GLOBALKEPT\else BAD\fi"
            r"\ifx\z\old ALIASRESTORED\else BAD\fi")
        for expected in ("LOCALRESTORED", "GLOBALKEPT", "ALIASRESTORED"):
            self.assertIn(expected, text)
        self.assertNotIn("BAD", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)

    def test_control_word_operand_keeps_separator_and_rereads(self):
        source = (r"\documentclass{article}\def\discard#1{}\discard\anything ABC "
                  r"\def\empty{}\empty DEF")
        text, manifest, output, _ = self.prepare(source)
        self.assertIn(r"\discard\anything ABC", text)
        self.assertIn(r"\empty DEF", text)
        reread, again, _, _ = preprocess_paper(str(output), output_dir=str(self.root / "again"), root_tex="master.tex")
        self.assertEqual(text, reread)
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertFalse(again.unresolved, again.unresolved)

    def test_failed_setup_has_no_partial_writes_sources_or_scope(self):
        for body in (r"\def\newname{A}TEXT", r"\def\newname{A}\unknown",
                     r"\begingroup\def\newname{A}", r"\def\newname{A}\iftrue"):
            with self.subTest(body=body):
                resolver = BindingResolver()
                context = resolver.new_context()
                reader = TexReader(body, catcodes=context.catcodes, endline_char=context.endlinechar)
                host = StructuralDispatcher(reader, context, resolver, preparation=True, source_commands=True)
                tokens = []
                while (token := reader.next_token()) is not None:
                    tokens.append(token)
                with self.assertRaises(ReadingIssue):
                    evaluate(host, tokens, reader.basis.whole, policy=SETUP)
                self.assertIsNone(context.lookup_meaning("newname"))
                self.assertEqual(context.scope_depth, 0)
                self.assertEqual(host.program_sources, [])
                self.assertEqual(host._groups, [])

    def test_setup_policy_is_inherited_by_nested_hook_execution(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\AddToHook{example}{TEXT}"
            r"\def\work{\def\x{A}\UseHook{example}}\work")
        self.assertIn(r"\work", text)
        self.assertTrue(any(r["reason"] == "stored_macro" for r in manifest.requirements))
        self.assertFalse(any(r.get("generated") for r in manifest.input_occurrences))

    def test_frozen_categories_and_boolean_effects(self):
        text, manifest, _, _ = self.prepare(
            r"\documentclass{article}\newif\ifflag\makeatletter"
            r"\def\work#1{\def\private@value{#1}\flagtrue}\makeatother\work{A}"
            r"\makeatletter\def\expected{A}\ifx\private@value\expected YES\else BAD\fi"
            r"\ifflag TRUE\else BAD\fi")
        self.assertIn("YES", text)
        self.assertIn("TRUE", text)
        self.assertNotIn("BAD", text)
        self.assertFalse(manifest.unresolved, manifest.unresolved)


if __name__ == "__main__":
    unittest.main()
