"""Bounded option effects, checked against latex2e base/ltclass.dtx's contracts.

https://github.com/latex3/latex2e/blob/main/base/ltclass.dtx
Preparation remains compiler-free; selected forwarding uses bounded expansion.
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
from reader_support import reload_catalog, requested_options
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import ReadingBoundary, SourceCommand
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.options import OptionScope
from src.reading.character_rules import ProfileError
from src.reading.tex_reader import CatCode, TexReader


class OptionProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, text, *, local=(), globals_=(), is_class=False, complete=True, catalog=None):
        resolver = BindingResolver(catalog or self.catalog)
        self.context = resolver.new_context()
        self.reader = TexReader(text, source_id="local.sty", occurrence_id=1,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.scope = OptionScope("local", requested_options(self.context, local),
                                requested_options(self.context, globals_, "global.tex"), is_class)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, resolver,
                                               source_commands=True, preparation=True, options=self.scope)
        items = list(self.dispatcher)
        self.assertEqual(isinstance(items[-1], ReadingBoundary), not complete, items[-1:])
        if complete:
            # Effect replay never duplicates or reorders physical-source coverage.
            ReadingCoverage(self.reader.basis, items)
        return items

    def truth(self, name="ifflag"):
        return self.context.lookup_meaning(name).truth

    def test_declarations_capture_without_executing_or_invalidating(self):
        self.read(r"\newif\ifflag\DeclareOption{on}{\flagtrue\unknown\input{absent}}")
        self.assertFalse(self.truth())
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertEqual(self.scope.declarations["on"].argument.tokens[0].value, "flagtrue")

    def test_only_selected_body_runs_and_source_remains_whole(self):
        source = (r"\newif\ifflag\DeclareOption{on}{\flagtrue}"
                  r"\DeclareOption{unused}{\unknown}\ProcessOptions\relax")
        items = self.read(source, local=("on",))
        self.assertTrue(self.truth())
        selected = next(i for i in items if isinstance(i, SourceCommand) and i.action == "process_options")
        self.assertEqual(selected.metadata["selected_options"], ["on"])
        self.assertEqual("".join(source[i.span.start:i.span.end] for i in items), source)

    def test_declaration_order_differs_from_starred_request_order(self):
        source = r"\newif\ifflag\DeclareOption{on}{\flagtrue}\DeclareOption{off}{\flagfalse}"
        self.read(source + r"\ProcessOptions", local=("off", "on"))
        self.assertFalse(self.truth())
        self.read(source + r"\ProcessOptions*", local=("off", "on"))
        self.assertTrue(self.truth())

    def test_global_options_precede_local_requests_and_are_not_repeated(self):
        source = r"\newif\ifflag\DeclareOption{on}{\flagtrue}\DeclareOption{off}{\flagfalse}"
        items = self.read(source + r"\ProcessOptions*", globals_=("on", "unrelated"), local=("off", "on"))
        self.assertFalse(self.truth())
        process = next(i for i in items if isinstance(i, SourceCommand) and i.action == "process_options")
        self.assertEqual(process.metadata["selected_options"], ["on", "off"])

    def test_default_action_handles_local_unknowns_at_their_starred_positions(self):
        source = r"\newif\ifflag\DeclareOption{on}{\flagtrue}\DeclareOption*{\flagfalse}"
        self.read(source + r"\ProcessOptions*", local=("mystery", "on"), globals_=("unused",))
        self.assertTrue(self.truth())
        self.read(source + r"\ProcessOptions", local=("mystery", "on"))
        self.assertFalse(self.truth())

    def test_execute_defaults_then_explicit_options(self):
        source = (r"\newif\ifflag\DeclareOption{on}{\flagtrue}\DeclareOption{off}{\flagfalse}"
                  r"\DeclareOption*{\unknown}\ExecuteOptions{on,absent}\ProcessOptions")
        self.read(source, local=("off",))
        self.assertFalse(self.truth())
        self.read(source)
        self.assertTrue(self.truth())

    def test_class_does_not_reconsume_globals_or_fail_for_unused_options(self):
        self.read(r"\newif\ifflag\DeclareOption{on}{\flagtrue}\ProcessOptions*",
                  local=("for-later-package",), globals_=("on",), is_class=True)
        self.assertFalse(self.truth())

    def test_unknown_package_option_is_an_explicit_boundary(self):
        items = self.read(r"\ProcessOptions", local=("unknown",), complete=False)
        self.assertEqual(items[-1].reason, "unknown_option")

    def test_option_body_uses_capture_time_control_sequence_tokens(self):
        source = (r"\makeatletter\newif\if@flag\DeclareOption{on}{\@flagtrue}"
                  r"\makeatother\ProcessOptions")
        self.read(source, local=("on",))
        self.assertTrue(self.truth("if@flag"))
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_selected_effect_changes_later_mouth_but_not_captured_braces(self):
        source = (r"\DeclareOption{lex}{\catcode`\!=11\relax\def\kept{!}}"
                  r"\ProcessOptions\def\bang!{later}")
        self.read(source, local=("lex",))
        self.assertEqual(self.context.lookup_definition("kept").body_tokens[0].catcode, CatCode.OTHER)
        self.assertIsNotNone(self.context.lookup_definition("bang!"))

    def test_bounded_conditionals_and_groups_use_existing_dispatcher(self):
        source = (r"\newif\ifflag\DeclareOption{on}{"
                  r"{\flagtrue}\iffalse\verb|\fi|\flagtrue}\ProcessOptions")
        # A skipped \verb does not run: \fi ends skipping and the stray | is
        # ordinary executable text, outside the bounded effect contract.
        self.read(source, local=("on",), complete=False)
        self.assertFalse(self.truth())
        self.read(r"\newif\ifflag\DeclareOption{on}{{\flagtrue}\ifflag\unknown\else\flagtrue\fi}"
                  r"\ProcessOptions", local=("on",))
        self.assertTrue(self.truth())

    def test_unselected_definitions_and_skipped_declarations_do_not_install(self):
        self.read(r"\iffalse\DeclareOption{x}{\unknown}\fi"
                  r"\def\stored{\DeclareOption{y}{\unknown}}\ProcessOptions")
        self.assertEqual(self.scope.declarations, {})

    def test_unsupported_selected_bodies_restore_state_and_are_not_expanded(self):
        for body in (r"\flagtrue\unknown", r"\flagtrue\input{absent}",
                     r"\flagtrue\verb|text|", r"\flagtrue\begingroup", r"\flagtrue\iftrue",
                     r"\flagtrue\def\macro##1{##1}", r"\flagtrue\CurrentOption"):
            with self.subTest(body=body):
                items = self.read(r"\newif\ifflag\DeclareOption{x}{" + body + r"}\ProcessOptions",
                                  local=("x",), complete=False)
                self.assertEqual(items[-1].reason, "option_body")
                self.assertFalse(self.truth())
                self.assertEqual(self.context.scope_depth, 0)
                self.assertFalse(self.scope.processed)

    def test_unknown_execution_invalidates_option_selection(self):
        items = self.read(r"\DeclareOption{x}{}\unknown\ProcessOptions", local=("x",), complete=False)
        self.assertEqual(items[-1].reason, "uncertain_options")

    def test_option_effects_restore_when_the_package_load_group_ends(self):
        resolver = BindingResolver(self.catalog)
        context = resolver.new_context()
        context.push_scope()
        text = r"\DeclareOption{lex}{\catcode`\!=11\relax}\ProcessOptions"
        reader = TexReader(text, catcodes=context.catcodes, endline_char=context.endlinechar)
        dispatcher = StructuralDispatcher(reader, context, resolver, source_commands=True,
            options=OptionScope("local", requested_options(context, ("lex",)), depth=1))
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in dispatcher))
        self.assertEqual(context.catcodes["!"], CatCode.LETTER)
        context.pop_scope()
        self.assertEqual(context.catcodes["!"], CatCode.OTHER)

    def test_stored_macro_invocation_is_not_expanded_by_option_replay(self):
        items = self.read(r"\def\setter{}\DeclareOption{x}{\setter}\ProcessOptions",
                          local=("x",), complete=False)
        self.assertIn("stored_macro", items[-1].detail)

    def test_source_capture_reports_unclosed_body(self):
        items = self.read(r"\DeclareOption{x}{", complete=False)
        self.assertEqual(items[-1].reason, "unclosed_argument")

    def test_option_commands_require_load_context_and_outer_scope(self):
        resolver = BindingResolver(self.catalog)
        context = resolver.new_context()
        reader = TexReader(r"\DeclareOption{x}{}", catcodes=context.catcodes, endline_char=context.endlinechar)
        items = list(StructuralDispatcher(reader, context, resolver, preparation=True, source_commands=True))
        self.assertEqual(items[-1].reason, "option_context")
        self.read(r"{\DeclareOption{x}{}}", complete=False)

    def test_order_is_selected_by_yaml_and_malformed_recipes_fail_loading(self):
        catalog = deepcopy(self.catalog)
        commands = catalog.engine_bindings["core_latex"]["reading"]["commands"]
        process = next(c for c in commands if c.get("action") == "process_options")
        process["metadata"]["order"] = "request"
        self.read(r"\newif\ifflag\DeclareOption{on}{\flagtrue}\DeclareOption{off}{\flagfalse}\ProcessOptions",
                  local=("off", "on"), catalog=reload_catalog(self, catalog))
        self.assertTrue(self.truth())
        for mutation in ("order", "starred_arguments", "action"):
            reading = deepcopy(self.catalog.engine_bindings["core_latex"]["reading"])
            process = next(c for c in reading["commands"] if c.get("action") == "process_options")
            if mutation == "order":
                process["metadata"]["order"] = "alphabetical"
            elif mutation == "starred_arguments":
                process["grammar"][mutation] = "anything"
            else:
                process[mutation] = "opaque"
            with self.subTest(mutation=mutation), self.assertRaises(ProfileError):
                self.catalog._validate_reading(reading, Path("core_latex.yaml"))


class OptionPreparationTests(unittest.TestCase):
    def setUp(self):
        root = PROJECT / "temp" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def prepare(self, text):
        self.put("main.tex", text)
        with patch("subprocess.run", side_effect=AssertionError("No compiler in preparation")):
            return preprocess_paper(str(self.root))

    def test_option_selects_natbib_and_bibliography_through_real_entrypoint(self):
        style = (r"\newif\ifload\DeclareOption{bib}{\loadtrue}\DeclareOption{unused}{\unknown}"
                 r"\ProcessOptions\relax\ifload\RequirePackage{natbib}\fi")
        self.put("local.sty", style)
        self.put("refs.bib", "@misc{a,title={A}}")
        source = (r"\documentclass{article}\usepackage[bib]{local}\begin{document}"
                  r"\citep{a}\bibliography{refs}\end{document}")
        text, manifest, out, ledger = self.prepare(source)
        self.assertFalse(manifest.unresolved)
        self.assertFalse(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))
        self.assertEqual(manifest.bibliography.citation_keys, ["a"])
        self.assertIn(r"\bibitem", text)
        self.assertNotIn(r"\DeclareOption", text)
        self.assertEqual((out / "local.sty").read_text(), style)
        self.assertEqual((self.root / "main.tex").read_text(), source)
        self.assertTrue((out / "bibliography.bib").is_file())
        self.assertEqual(len(set(manifest.source_reads)), len(manifest.source_reads))
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))

    def test_class_globals_and_nested_package_ownership(self):
        self.put("child.sty", r"\DeclareOption{shared}{\def\child{C}}\ProcessOptions")
        self.put("outer.sty", r"\newif\ifouter\DeclareOption{shared}{\outertrue}"
                 r"\RequirePackage{child}\ProcessOptions\ifouter\RequirePackage{natbib}\fi")
        _, manifest, _, _ = self.prepare(r"\documentclass[shared]{article}\usepackage{outer}")
        self.assertFalse(manifest.unresolved)
        self.assertIn("natbib", [p.name for p in manifest.packages_declared])

    def test_option_declarations_can_be_in_cached_input_file(self):
        self.put("opts.tex", r"\DeclareOption{on}{\flagtrue}")
        self.put("local.sty", r"\newif\ifflag\input{opts}\ProcessOptions\ifflag\RequirePackage{natbib}\fi")
        _, manifest, _, _ = self.prepare(r"\documentclass{article}\usepackage[on]{local}")
        self.assertFalse(manifest.unresolved)
        self.assertIn("natbib", [p.name for p in manifest.packages_declared])

    def test_local_class_owns_only_its_options_and_source_is_retained(self):
        self.put("local.cls", r"\newif\ifflag\DeclareOption{on}{\flagtrue}\ProcessOptions"
                 r"\ifflag\RequirePackage{natbib}\fi")
        _, manifest, out, _ = self.prepare(r"\documentclass[on]{local}")
        self.assertFalse(manifest.unresolved)
        self.assertTrue((out / "local.cls").is_file())
        self.assertIn("natbib", [p.name for p in manifest.packages_declared])

    def test_unknown_option_body_keeps_master_and_separately_retained_style(self):
        self.put("local.sty", r"\DeclareOption{x}{\unknown}\ProcessOptions")
        self.put("later.tex", "LATER")
        text, manifest, out, _ = self.prepare(r"\documentclass{article}\usepackage[x]{local}\input{later}")
        self.assertIn("LATER", text)
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertTrue(any(d["reason"] == "option_body" for d in manifest.unresolved))
        self.assertTrue((out / "local.sty").is_file())

    def test_repeated_package_with_different_options_is_diagnosed(self):
        self.put("local.sty", r"\DeclareOption{a}{}\DeclareOption{b}{}\ProcessOptions")
        text, manifest, _, _ = self.prepare(r"\documentclass{article}\usepackage[a]{local}\usepackage[b]{local}TAIL")
        self.assertIn("TAIL", text)
        self.assertTrue(any(d["reason"] == "option_clash" for d in manifest.unresolved))
        self.assertEqual(sum(o["source"] == "local.sty" for o in manifest.input_occurrences), 1)

    def test_literal_option_forwarding_is_ordered_and_preserved(self):
        self.put("local.sty", r"\newif\ifflag\DeclareOption{on}{\flagtrue}\DeclareOption{off}{\flagfalse}"
                 r"\ProcessOptions*\ifflag\RequirePackage{natbib}\fi")
        source = r"\PassOptionsToPackage{off}{local}\documentclass{article}\usepackage[on]{local}"
        text, manifest, _, _ = self.prepare(source)
        self.assertFalse(manifest.unresolved)
        self.assertIn(r"\PassOptionsToPackage{off}{local}", text)
        self.assertIn("natbib", [p.name for p in manifest.packages_declared])

    def test_forwarded_class_options_do_not_become_global_package_options(self):
        self.put("local.cls", r"\newif\ifclassflag\DeclareOption{on}{\classflagtrue}\ProcessOptions"
                 r"\ifclassflag\RequirePackage{natbib}\fi")
        self.put("local.sty", r"\newif\ifflag\DeclareOption{on}{\flagtrue}\ProcessOptions"
                 r"\ifflag\RequirePackage{listings}\fi")
        _, manifest, _, _ = self.prepare(r"\PassOptionsToClass{on}{local}\documentclass{local}\usepackage{local}")
        self.assertFalse(manifest.unresolved)
        self.assertIn("natbib", [p.name for p in manifest.packages_declared])
        self.assertNotIn("listings", [p.name for p in manifest.packages_declared])

    def test_unsupported_child_invalidates_parent_options_and_later_sources_continue(self):
        self.put("child.sty", r"\unknown")
        self.put("local.sty", r"\DeclareOption{x}{}\RequirePackage{child}\ProcessOptions")
        text, manifest, _, _ = self.prepare(r"\documentclass{article}\usepackage[x]{local}TAIL")
        self.assertIn("TAIL", text)
        self.assertTrue(any(d["reason"] == "uncertain_options" for d in manifest.unresolved))


if __name__ == "__main__":
    unittest.main()
