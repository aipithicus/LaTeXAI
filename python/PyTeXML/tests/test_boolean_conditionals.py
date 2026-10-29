"""Bounded LaTeX newif: local meanings, source preservation, and preparation.

Semantics: latex2e base/ltdefns.dtx newif/@if (initial local let to iffalse,
local setter definitions whose invocation lets the target to iftrue/iffalse).
No compiler or general macro expansion is used by these tests.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from reader_support import reload_catalog
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.context import ExecutionMode
from src.reading.contracts import BooleanMeaning, ReadingBoundary, SourceCommand, SkippedRegion, ConditionalRegion
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.mouth_profiles import ProfileError
from src.reading.tex_reader import CatCode, ReadEvent, TexReader, TokenKind


class BooleanConditionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, text, *, preparation=False, complete=True, catalog=None):
        resolver = BindingResolver(catalog or self.catalog)
        self.context = resolver.new_context()
        self.reader = TexReader(text, source_id="paper.tex", occurrence_id=7,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, resolver,
                                               preparation=preparation, source_commands=True)
        items = list(self.dispatcher)
        spans = [i.remainder if isinstance(i, ReadingBoundary) else i.span for i in items]
        self.assertEqual("".join(text[s.start:s.end] for s in spans), text)
        self.assertEqual([s.start for s in spans[1:]], [s.end for s in spans[:-1]])
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)
        if complete:
            self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items), items[-1:])
        else:
            self.assertIsInstance(items[-1], ReadingBoundary)
        return items

    def chars(self, items):
        return "".join(i.token.value for i in items if isinstance(i, ReadEvent) and i.token
                       and i.token.kind == TokenKind.CHARACTER
                       and i.token.catcode not in {CatCode.SPACE, CatCode.BEGIN_GROUP, CatCode.END_GROUP})

    def test_false_initially_and_both_setters_route_branches(self):
        items = self.read(r"\newif\ifflag\ifflag X\else A\fi\flagtrue\ifflag B\else X\fi"
                          r"\flagfalse\ifflag X\else C\fi")
        self.assertEqual(self.chars(items), "ABC")
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)
        self.assertIsNone(self.context.lookup_definition("ifflag"))
        self.assertEqual(len([i for i in items if isinstance(i, SkippedRegion)]), 3)
        self.assertFalse(ReadingCoverage(self.reader.basis, items).unknown)

    def test_declaration_headers_keep_comments_caret_spelling_and_braces(self):
        for header in (r"\newif\ifflag", r"\newif{\ifflag}",
                       "\\newif% target\n\\iffl^^61g", "\\newif % target\n{\\ifflag}"):
            with self.subTest(header=header):
                items = self.read(header + r"\flagtrue\ifflag Y\fi")
                self.assertIsInstance(items[0], SourceCommand)
                self.assertEqual(self.reader.source_slice(items[0].span), header)
                self.assertEqual(self.chars(items), "Y")

    def test_setters_and_redeclarations_restore_through_nested_groups(self):
        items = self.read(r"\newif\ifflag{\flagtrue\ifflag A\fi"
                          r"\begingroup\newif\ifflag\ifflag X\else B\fi\endgroup"
                          r"\ifflag C\fi}\ifflag X\else D\fi")
        self.assertEqual(self.chars(items), "ABCD")
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)
        self.read(r"{\newif\iflocal\localtrue}")
        for name in ("iflocal", "localtrue", "localfalse"):
            self.assertIsNone(self.context.lookup_meaning(name))

    def test_author_definitions_and_booleans_share_one_scoped_meaning_slot(self):
        items = self.read(r"\def\ifflag{OLD}\def\flagtrue{OLD}"
                          r"{\newif\ifflag\flagtrue\ifflag A\fi}")
        self.assertEqual(self.chars(items), "A")
        self.assertIsNotNone(self.context.lookup_definition("ifflag"))
        self.assertIsNotNone(self.context.lookup_definition("flagtrue"))
        # A later setter overwrites a local macro definition of the test itself.
        items = self.read(r"\newif\ifflag\def\ifflag{BODY}\flagtrue\ifflag B\fi")
        self.assertEqual(self.chars(items), "B")
        self.assertIsNone(self.context.lookup_definition("ifflag"))

    def test_shadowed_setter_is_not_executed_and_restores_on_group_exit(self):
        items = self.read(r"\newif\ifflag{\def\flagtrue{}\iffalse\flagtrue\fi}"
                          r"\flagtrue\ifflag Y\fi")
        self.assertEqual(self.chars(items), "Y")
        items = self.read(r"\newif\ifflag\def\flagtrue{}\flagtrue", complete=False)
        self.assertEqual(items[-1].reason, "stored_macro")
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)

    def test_skipped_branches_use_meanings_without_executing_setters_or_factories(self):
        items = self.read(r"\newif\ifflag\iffalse\flagtrue\ifflag X\else X\fi"
                          r"\newif\ifnever\else A\fi\ifflag X\else B\fi")
        self.assertEqual(self.chars(items), "AB")
        self.assertIsNone(self.context.lookup_meaning("ifnever"))
        # newif is not executed, but an already-existing test token following it
        # still nests, exactly as it does in TeX's pass_text.
        items = self.read(r"\newif\ifflag\iffalse\newif\ifflag X\fi\else Y\fi")
        self.assertEqual(self.chars(items), "Y")

    def test_skipped_literals_and_definitions_do_not_hide_conditional_tokens(self):
        items = self.read(r"\newif\ifflag\iffalse\verb|\ifflag X\fi|\else Y\fi")
        self.assertEqual(self.chars(items), "Y")
        items = self.read(r"\newif\ifflag\iffalse\def\ifflag{X\fi}\else Y\fi")
        self.assertEqual(self.chars(items), "Y")

    def test_active_stored_bodies_and_literal_regions_do_not_execute_booleans(self):
        items = self.read(r"\newif\ifflag\def\set{\flagtrue\newif\ifhidden}"
                          r"\verb|\flagtrue|\ifflag X\else Y\fi")
        self.assertEqual(self.chars(items), "Y")
        self.assertIsNone(self.context.lookup_meaning("ifhidden"))

    def test_setters_copy_current_conditional_meanings_instead_of_hardcoded_truth(self):
        items = self.read(r"\newif\ifflag{\newif\iftrue\flagtrue\ifflag X\else Y\fi}"
                          r"\flagtrue\ifflag Z\fi")
        self.assertEqual(self.chars(items), "YZ")
        items = self.read(r"\newif\ifflag\def\iftrue{}\flagtrue", complete=False)
        self.assertEqual(items[-1].reason, "unsupported_boolean_meaning")
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)

    def test_factory_recipe_and_command_name_come_from_yaml(self):
        catalog = deepcopy(self.catalog)
        spec = next(s for s in catalog.engine_bindings["core_latex"]["reading"]["commands"]
                    if s["family"] == "conditional_factory")
        spec["name"] = r"\switch"
        spec["grammar"] = {"handler": "boolean_declaration", "target_prefix": "when",
                           "initial": r"\iftrue", "setters": {"off": r"\iffalse", "on": r"\iftrue"}}
        items = self.read(r"\switch\whenready\whenready A\fi\readyoff\whenready X\else B\fi", catalog=reload_catalog(self, catalog))
        self.assertEqual(self.chars(items), "AB")

    def test_invalid_or_computed_targets_publish_nothing(self):
        for suffix in ("", " a", "{}", r"\flag", r"\if", r"{\ifflag extra}", r"\csname ifflag\endcsname"):
            with self.subTest(suffix=suffix):
                items = self.read(r"\newif" + suffix, complete=False)
                self.assertEqual(items[-1].reason, "unsupported_boolean_target")
                self.assertIsNone(self.context.lookup_meaning("ifflag"))
        self.read(r"\def\iffalse{}\newif\ifflag", complete=False)
        for name in ("ifflag", "flagtrue", "flagfalse"):
            self.assertIsNone(self.context.lookup_meaning(name))

    def test_internal_names_follow_live_catcodes_and_global_prefix_stays_deferred(self):
        items = self.read(r"\makeatletter\newif\if@flag\@flagtrue\if@flag Y\fi\makeatother")
        self.assertEqual(self.chars(items), "Y")
        items = self.read(r"\newif\ifflag\global\flagtrue\ifflag X\else Y\fi",
                          preparation=True, complete=False)
        self.assertEqual(items[-1].reason, "assignment_prefix")
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)

    def test_unexecuted_commands_never_route_using_a_stale_boolean(self):
        for code in (r"\unknown", r"\def\enable{\flagtrue\unknown}\enable",
                     r"\begin{unknown}BODY\end{unknown}", r"$\flagtrue$"):
            with self.subTest(code=code):
                items = self.read(r"\newif\ifflag" + code + r"\ifflag YES\else NO\fi",
                                  preparation=True)
                self.assertTrue(any(isinstance(i, ConditionalRegion) for i in items))
                self.assertIsNotNone(self.context.lookup_meaning("ifflag").uncertain)
                self.assertNotIn("YES", self.chars(items))
                self.assertNotIn("NO", self.chars(items))
        # Unknown code could assign globally; restoring an outer group cannot
        # re-establish a known value. Known setters remain strictly local.
        items = self.read(r"\newif\ifflag{\flagtrue\unknown}\ifflag A\else B\fi",
                          preparation=True)
        self.assertTrue(any(isinstance(i, ConditionalRegion) for i in items))
        self.assertIsNotNone(self.context.lookup_meaning("ifflag").uncertain)

    def test_context_copy_and_restore_keep_independent_boolean_scope_journals(self):
        self.read(r"\newif\ifflag")
        ctx = self.context
        ctx.push_scope()
        ctx.record_meaning("ifflag", BooleanMeaning(self.reader.basis.span(0, 0), True))
        saved = ctx.copy()
        ctx.pop_scope()
        self.assertFalse(ctx.lookup_meaning("ifflag").truth)
        self.assertTrue(saved.lookup_meaning("ifflag").truth)
        ctx.restore_from(saved)
        ctx.pop_scope()
        self.assertFalse(ctx.lookup_meaning("ifflag").truth)

    def test_schema_rejects_incomplete_or_unsupported_boolean_recipes(self):
        for field, value in (("scope", "global"), ("target_prefix", ""), ("initial", "\\"),
                             ("setters", {True: r"\iftrue"}), ("setters", {}), ("handler", "source_arguments")):
            reading = deepcopy(self.catalog.engine_bindings["core_latex"]["reading"])
            spec = next(s for s in reading["commands"] if s["family"] == "conditional_factory")
            (spec if field == "scope" else spec["grammar"])[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ProfileError):
                self.catalog._validate_reading(reading, Path("core_latex.yaml"))

    def test_pure_math_does_not_invalidate_boolean_and_unknown_setter_does_not_renest(self):
        items = self.read(r"\newif\ifflag $1+2$\ifflag X\else Y\fi", preparation=True)
        self.assertEqual(self.chars(items), "Y")
        items = self.read(r"\newif\ifflag\unknown\iffalse\flagtrue\fi", preparation=True, complete=False)
        self.assertEqual(items[-1].reason, "uncertain_boolean")

    def test_runtime_boolean_declarations_do_not_change_shared_catalog_or_other_documents(self):
        original = deepcopy(self.catalog.engine_bindings)
        self.read(r"\newif\ifflag\flagtrue")
        resolver = BindingResolver(self.catalog)
        self.assertIsNone(resolver.new_context().lookup_meaning("ifflag"))
        self.assertEqual(self.catalog.engine_bindings, original)


class BooleanPreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def put(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def prepare(self, source):
        self.put("main.tex", source)
        with patch("subprocess.run", side_effect=AssertionError("No compiler in preparation")):
            return preprocess_paper(str(self.root))

    def test_boolean_state_crosses_inputs_and_routes_only_selected_dependencies(self):
        part = self.put("part.tex", r"\flagtrue\ifflag\input{yes}\else\input{missing}\fi")
        self.put("yes.tex", "CHOSEN")
        self.put("after.tex", "AFTER")
        source = (r"\documentclass{article}\newif\ifflag\begin{document}"
                  r"{\input{part}}\ifflag\input{missing}\else\input{after}\fi\end{document}")
        text, manifest, out, ledger = self.prepare(source)
        self.assertIn("CHOSEN", text)
        self.assertIn("AFTER", text)
        self.assertIn(r"\newif\ifflag", text)
        self.assertIn(r"\flagtrue", text)
        self.assertNotIn(r"\input", text)
        self.assertFalse(manifest.unresolved)
        self.assertEqual(len(manifest.source_reads), 4)
        self.assertEqual(len(set(manifest.source_reads)), 4)
        self.assertEqual(ledger.master_length, len(text))
        self.assertEqual((self.root / "main.tex").read_text(), source)
        self.assertEqual(part.read_text(), r"\flagtrue\ifflag\input{yes}\else\input{missing}\fi")

    def test_declaration_emission_cannot_join_target_to_following_text(self):
        text, _, _, _ = self.prepare("\\documentclass{article}\\newif\\ifflag\nTAIL")
        self.assertIn(r"\newif\ifflag TAIL", text)
        self.assertNotIn(r"\ifflagTAIL", text)

    def test_local_style_boolean_can_select_package_activation_without_inlining_style(self):
        style = r"\newif\ifloadbib\loadbibtrue\ifloadbib\RequirePackage{natbib}\fi"
        self.put("local.sty", style)
        self.put("refs.bib", "@misc{a,title={A}}")
        text, manifest, out, _ = self.prepare(r"\documentclass{article}\usepackage{local}"
            r"\begin{document}\citep{a}\bibliography{refs}\end{document}")
        self.assertEqual(manifest.bibliography.citation_keys, ["a"])
        self.assertFalse(manifest.unresolved)
        self.assertFalse(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))
        self.assertNotIn(r"\newif", text)
        self.assertEqual((self.root / "local.sty").read_text(), style)

    def test_unresolved_effect_retains_both_branches_and_publishes_master(self):
        suffix = r"\ifflag\input{yes}\else\input{no}\fi\end{document}"
        source = r"\documentclass{article}\newif\ifflag\begin{document}\unknown" + suffix
        text, manifest, out, _ = self.prepare(source)
        self.assertTrue((out / "master.tex").is_file())
        self.assertIn(suffix.replace(r"\fi\end", r"\fi \end"), text)
        self.assertFalse(manifest.unresolved)
        self.assertTrue(any(d["reason"] == "conditional_interpretation" for d in manifest.requirements))
        self.assertEqual({d["reason"] for d in manifest.candidate_dependencies}, {"missing_dependency"})
        self.assertEqual((self.root / "main.tex").read_text(), source)

    def test_input_can_open_an_evaluated_boolean_conditional_closed_by_caller(self):
        self.put("part.tex", r"\newif\ifflag\flagtrue\ifflag CHILD")
        text, manifest, _, _ = self.prepare(r"\documentclass{article}\input{part} PARENT\else UNUSED\fi")
        self.assertFalse(manifest.unresolved)
        self.assertIn("CHILD PARENT", " ".join(text.split()))
        self.assertNotIn("UNUSED", text)

    def test_unresolved_local_style_and_missing_package_invalidate_caller_booleans(self):
        self.put("local.sty", r"\catcode\unknown=11")
        for package in ("local", "missing"):
            with self.subTest(package=package):
                text, manifest, _, _ = self.prepare(r"\documentclass{article}\newif\ifflag\usepackage{" +
                    package + r"}\ifflag YES\else NO\fi")
                self.assertIn(r"\ifflag YES\else NO\fi", text)
                self.assertTrue(any(d["reason"] == "conditional_interpretation" for d in manifest.requirements))
                self.assertFalse(any(d["reason"] == "uncertain_boolean" for d in manifest.unresolved))


if __name__ == "__main__":
    unittest.main()
