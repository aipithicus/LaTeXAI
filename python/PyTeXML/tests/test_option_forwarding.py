"""Frozen option tokens, bounded source requests, and atomic owner publication."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from reader_support import requested_options
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.prepare.session import PreparationSession
from src.prepare.pipeline import preprocess_paper
from src.reading.contracts import ReadingBoundary, SourceCommand, TokenListMeaning
from src.reading.coverage import ReadingCoverage
from src.reading.dispatcher import StructuralDispatcher
from src.reading.options import OptionScope, option_names
from src.reading.tex_reader import CatCode, TexReader


class OptionForwardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def read(self, text, *, local=("x",), globals_=(), complete=True, forward=True, preparation=False):
        knowledge = BindingResolver(self.catalog)
        context = knowledge.new_context()
        reader = TexReader(text, source_id="local.sty", occurrence_id=1,
                           catcodes=context.catcodes, endline_char=context.endlinechar)
        scope = OptionScope("local", requested_options(context, local),
                            requested_options(context, globals_, "global.tex"))
        self.requests = []
        host = StructuralDispatcher(reader, context, knowledge, source_commands=True, options=scope,
                                    option_forwarder=self.requests.extend if forward else None, preparation=preparation)
        items = list(host)
        self.assertEqual(isinstance(items[-1], ReadingBoundary), not complete, items[-1:])
        if complete:
            ReadingCoverage(reader.basis, items)
        self.host, self.items = host, items
        return context

    def replacement(self, context, name):
        return "".join(t.value for t in context.lookup_meaning(name).replacement_tokens)

    def forwarded(self):
        return [(c.value("name"), option_names(c.argument("options"))) for c in self.requests]

    def test_current_option_alias_keeps_frozen_value_and_original_origin(self):
        context = self.read(r"\DeclareOption*{\let\saved\CurrentOption"
                            r"\def\CurrentOption{changed}\PassOptionsToClass{\saved}{article}}\ProcessOptions",
                            local=("11pt",))
        self.assertEqual(self.forwarded(), [("article", ("11pt",))])
        self.assertEqual(self.replacement(context, "saved"), "11pt")
        self.assertEqual(self.replacement(context, "CurrentOption"), "")
        tokens = self.requests[0].argument("options").tokens
        self.assertEqual({t.span.basis.source_id for t in tokens}, {"request.tex"})
        self.assertEqual([t.span.start for t in tokens], [1, 2, 3, 4])

    def test_declaration_order_uses_declaration_tokens_star_uses_request_tokens(self):
        for star, values, source in (("", ("a", "b"), "local.sty"), ("*", ("b", "a"), "request.tex")):
            with self.subTest(star=star):
                self.read(r"\DeclareOption{a}{\PassOptionsToPackage{\CurrentOption}{target}}"
                          r"\DeclareOption{b}{\PassOptionsToPackage{\CurrentOption}{target}}\ProcessOptions" + star,
                          local=("b", "a"))
                self.assertEqual([v[1][0] for v in self.forwarded()], list(values))
                self.assertEqual({t.span.basis.source_id for c in self.requests for t in c.argument("options").tokens},
                                 {source})

    def test_recognized_globals_precede_locals_and_default_repeats(self):
        self.read(r"\DeclareOption{a}{\PassOptionsToPackage{\CurrentOption}{target}}"
                  r"\DeclareOption*{\PassOptionsToPackage{\CurrentOption}{target}}\ProcessOptions*",
                  local=("x", "a", "x"), globals_=("unrelated", "a"))
        self.assertEqual(self.forwarded(), [("target", ("a",)), ("target", ("x",)), ("target", ("x",))])

    def test_execute_options_restores_previous_contents_and_process_clears(self):
        context = self.read(r"\def\CurrentOption{previous}"
                            r"\DeclareOption{a}{\PassOptionsToPackage{\CurrentOption}{target}}"
                            r"\ExecuteOptions{a,absent}\edef\afterDefaults{\CurrentOption}"
                            r"\ProcessOptions\edef\afterProcess{\CurrentOption}", local=("a",))
        self.assertEqual(self.replacement(context, "afterDefaults"), "previous")
        self.assertEqual(self.replacement(context, "afterProcess"), "")
        self.assertEqual(self.forwarded(), [("target", ("a",)), ("target", ("a",))])

    def test_execute_options_restoration_expands_saved_tokens_in_resulting_state(self):
        context = self.read(r"\def\value{before}\def\CurrentOption{\value}"
                            r"\DeclareOption{x}{\def\value{after}}\ExecuteOptions{x}")
        self.assertEqual(self.replacement(context, "CurrentOption"), "after")

    def test_forwarding_arguments_use_current_macro_and_aliased_operation_meanings(self):
        self.read(r"\let\forward\PassOptionsToPackage\def\PassOptionsToPackage{shadow}"
                  r"\def\opts{a,b}\def\target{child}"
                  r"\DeclareOption{x}{\forward{\opts}{\target}}\ProcessOptions")
        self.assertEqual(self.forwarded(), [("child", ("a", "b"))])

    def test_shadowed_forwarding_operation_is_not_dispatched_by_spelling(self):
        self.read(r"\def\PassOptionsToPackage{shadow}\DeclareOption{x}{"
                  r"\PassOptionsToPackage{a}{target}}\ProcessOptions", complete=False)
        self.assertEqual(self.requests, [])
        self.assertIn("stored_macro", self.items[-1].detail)

    def test_current_option_categories_survive_later_catcode_changes(self):
        context = self.read(r"\DeclareOption*{\catcode65=12\relax"
                            r"\edef\captured{\CurrentOption}\PassOptionsToPackage{\CurrentOption}{target}}"
                            r"\ProcessOptions", local=("A",))
        self.assertEqual(context.catcodes["A"], CatCode.OTHER)
        self.assertEqual(context.lookup_definition("captured").replacement_tokens[0].catcode, CatCode.LETTER)
        self.assertEqual(self.requests[0].argument("options").tokens[0].catcode, CatCode.LETTER)

    def test_later_body_failure_rolls_back_all_meanings_and_requests(self):
        context = self.read(r"\def\CurrentOption{entry}\widowpenalty=17 "
                            r"\DeclareOption{a}{\gdef\leaked{bad}\widowpenalty=23 "
                            r"\PassOptionsToPackage{a}{target}}"
                            r"\DeclareOption{b}{\unknown}\ProcessOptions", local=("a", "b"), complete=False)
        self.assertEqual(self.requests, [])
        self.assertIsNone(context.lookup_meaning("leaked"))
        self.assertEqual(context.integer_parameters.read("widowpenalty"), 17)
        self.assertEqual(self.replacement(context, "CurrentOption"), "entry")
        self.assertFalse(self.host.options.processed)

    def test_invalid_expansion_publishes_no_partial_requests(self):
        for operand in (r"\missing", r"\loop", r"\noexpand\CurrentOption"):
            with self.subTest(operand=operand):
                self.read(r"\def\loop{\loop}\DeclareOption{x}{"
                          r"\PassOptionsToPackage{good}{target}\PassOptionsToPackage{" + operand +
                          r"}{target}}\ProcessOptions", complete=False)
                self.assertEqual(self.requests, [])

    def test_generated_spaces_remain_an_explicit_limit(self):
        self.read(r"\def\opts{a b}\DeclareOption{x}{\PassOptionsToPackage{\opts}{target}}\ProcessOptions",
                  complete=False)
        self.assertIn("option_expansion", self.items[-1].detail)
        self.assertEqual(self.requests, [])

    def test_literal_spaces_are_removed_before_expansion(self):
        self.read(r"\DeclareOption{x}{\PassOptionsToPackage{ a , b }{target}}\ProcessOptions")
        self.assertEqual(self.forwarded(), [("target", ("a", "b"))])

    def test_option_replay_admits_only_forwarding_with_an_owner(self):
        for body, forward in ((r"\PassOptionsToPackage{a}{target}", False),
                              (r"\input{absent}", True), (r"\RequirePackage{target}", True)):
            with self.subTest(body=body, forward=forward):
                self.read(r"\DeclareOption{x}{" + body + r"}\ProcessOptions", complete=False, forward=forward)
                self.assertIn("input owner", self.items[-1].detail)
                self.assertEqual(self.requests, [])

    def test_empty_format_meaning_is_mutable_and_scoped(self):
        context = self.read(r"\let\saved\CurrentOption{\def\CurrentOption{inner}}"
                            r"\edef\after{\CurrentOption}\DeclareOption{x}{}\ProcessOptions")
        self.assertIsInstance(context.lookup_meaning("saved"), TokenListMeaning)
        self.assertEqual(self.replacement(context, "after"), "")
        self.assertIsNotNone(context.lookup_meaning("saved").format_origin)

    def test_unknown_execution_invalidates_copied_token_lists_across_scope_exit(self):
        context = self.read(r"\let\saved\CurrentOption{\def\CurrentOption{inner}\unknown}"
                            r"\edef\out{\saved}", preparation=True, complete=False)
        self.assertEqual(self.items[-1].reason, "uncertain_meaning")
        self.assertTrue(self.items[-1].causes)
        self.assertIsNone(context.lookup_meaning("out"))
        self.assertIsNotNone(context.lookup_meaning("saved").uncertain)

    def test_execute_options_unavailable_restoration_is_an_atomic_boundary(self):
        context = self.read(r"\let\CurrentOption\relax"
                            r"\DeclareOption{x}{\gdef\leaked{bad}\PassOptionsToPackage{x}{target}}"
                            r"\ExecuteOptions{x}", complete=False)
        self.assertEqual(self.items[-1].reason, "option_current")
        self.assertIsNone(context.lookup_meaning("leaked"))
        self.assertEqual(self.requests, [])


class OptionForwardingPreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8", newline="\n")

    def run_session(self, source):
        self.put("main.tex", source)
        with patch("subprocess.run", side_effect=AssertionError("No compiler in preparation")):
            return PreparationSession(self.root).run()

    def test_gauntlet_default_forwarding_reaches_base_class(self):
        fixture = PROJECT / "tests/fixtures/specimens/gauntlet-master/gmvenue.cls"
        # Exercise the actual fixture through LoadClass; later predicates are
        # independently tracked gates, not part of this mechanism test.
        style = fixture.read_text()
        style = style[:style.index(r"\LoadClass{article}[2020/01/01]") + len(r"\LoadClass{article}[2020/01/01]")]
        self.put("local.cls", style)
        session = self.run_session(r"\documentclass[11pt]{local}")
        self.assertEqual(session.manifest.unresolved, [])
        article = next(p for p in session.manifest.packages_declared if p.name == "article")
        self.assertEqual(article.options, ["11pt"])
        process = next(c for c in session.commands if c.action == "process_options")
        request = process.metadata["forwarded_options"][0]
        self.assertEqual(request["options"], ["11pt"])
        self.assertTrue(request["unit_id"])
        self.assertEqual({t["source"] for t in request["tokens"]}, {"main.tex"})

    def test_owner_validation_failure_rolls_back_earlier_forwarding(self):
        self.put("local.sty", r"\DeclareOption{x}{\PassOptionsToPackage{a}{future}"
                 r"\PassOptionsToClass{11pt}{article}}\ProcessOptions")
        session = self.run_session(r"\documentclass{article}\usepackage[x]{local}")
        self.assertTrue(any(d["reason"] == "option_lifecycle" for d in session.manifest.unresolved))
        self.assertNotIn("package:future", session.forwarded_options)

    def test_later_selected_body_failure_never_reaches_owner(self):
        self.put("local.sty", r"\DeclareOption{a}{\PassOptionsToPackage{x}{future}}"
                 r"\DeclareOption{b}{\unknown}\ProcessOptions")
        session = self.run_session(r"\documentclass{article}\usepackage[a,b]{local}")
        self.assertTrue(any(d["reason"] == "option_body" for d in session.manifest.unresolved))
        self.assertEqual(session.forwarded_options, {})

    def test_direct_macro_forwarding_and_nested_load_options_keep_order(self):
        self.put("outer.sty", r"\DeclareOption*{\PassOptionsToPackage{\CurrentOption}{child}}"
                 r"\ProcessOptions*\RequirePackage[c]{child}")
        self.put("child.sty", r"\DeclareOption*{}\ProcessOptions*")
        session = self.run_session(r"\def\opts{a,b}\PassOptionsToPackage{\opts}{outer}"
                                   r"\documentclass{article}\usepackage{outer}")
        self.assertEqual(session.manifest.unresolved, [])
        self.assertEqual(next(p.options for p in session.manifest.packages_declared if p.name == "child"),
                         ["a", "b", "c"])
        processes = [c for c in session.commands if c.action == "process_options"]
        self.assertEqual([c.metadata["selected_options"] for c in processes], [["a", "b"], ["a", "b", "c"]])

    def test_preparation_retains_authored_source_without_replay_emission(self):
        style = r"\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}\ProcessOptions\LoadClass{article}"
        self.put("local.cls", style)
        source = r"\documentclass[11pt]{local}TAIL"
        self.put("main.tex", source)
        text, manifest, output, ledger = preprocess_paper(str(self.root))
        self.assertFalse(manifest.unresolved)
        self.assertEqual((output / "local.cls").read_text(), style)
        self.assertIn("TAIL", text)
        self.assertNotIn(r"\PassOptionsToClass", text)
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))

    def test_base_class_owns_its_options_without_replacing_document_globals(self):
        self.put("venue.cls", r"\PassOptionsToClass{base}{base}\LoadClass{base}")
        self.put("base.cls", r"\DeclareOption{base}{}\ProcessOptions")
        self.put("local.sty", r"\def\seen{}\DeclareOption{global}{\def\seen{global}}"
                 r"\DeclareOption{base}{\def\seen{base}}\ProcessOptions")
        session = self.run_session(r"\documentclass[global]{venue}\usepackage{local}")
        self.assertEqual(session.manifest.unresolved, [])
        self.assertEqual([o.name for o in session.class_options], ["global"])
        self.assertEqual("".join(t.value for t in session.context.lookup_definition("seen").replacement_tokens), "global")
        self.assertEqual(next(p.options for p in session.manifest.packages_declared if p.name == "base"), ["base"])

    def test_load_class_requires_class_context(self):
        session = self.run_session(r"\documentclass{article}\LoadClass{report}")
        self.assertTrue(any(d["reason"] == "class_context" for d in session.manifest.unresolved))
        self.assertNotIn("report", [p.name for p in session.manifest.packages_declared])

    def test_independent_latex_witness(self):
        fixture = PROJECT / "tests/fixtures/engine"
        expected = json.loads((fixture / "option-forwarding.expected.json").read_text())
        for name in ("of-venue.cls", "of-order.sty", "of-star.sty", "of-target.sty"):
            self.put(name, (fixture / name).read_text())
        source = (fixture / "option-forwarding.tex").read_text().split(r"\makeatletter")[0]
        session = self.run_session(source)
        self.assertEqual(session.manifest.unresolved, [])
        for key, name in (("declaration", "declarationTrace"), ("request", "requestTrace"),
                          ("defaults", "afterDefaults"), ("process", "afterProcess"), ("alias", "savedAlias")):
            self.assertEqual("".join(t.value for t in session.context.lookup_meaning(name).replacement_tokens),
                             expected[key], key)
        # Kernel option-list serialization carries a trailing empty item; it
        # never invokes an option body and is excluded from the resolved list.
        for key, name in (("article", "article"), ("forwarded", "of-target")):
            self.assertEqual(next(p.options for p in session.manifest.packages_declared if p.name == name),
                             [o for o in expected[key].split(",") if o])


if __name__ == "__main__":
    unittest.main()
