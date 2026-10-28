"""Bounded LaTeX declarations, from latex2e base/ltdefns.dtx.

https://github.com/latex3/latex2e/blob/main/base/ltdefns.dtx
Tests assert authored tokens and reading effects, not macro expansion.
"""
from copy import deepcopy
import json
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
from src.reading.character_rules import ProfileError
from src.reading.context import ExecutionMode
from src.reading.contracts import CommandDefinition, DeferredRegion, ReadingBoundary, StoredDefinition
from src.reading.coverage import ReadingCoverage
from src.reading.definition_scanner import DefinitionScanner
from src.reading.dispatcher import StructuralDispatcher
from src.reading.options import OptionScope
from src.reading.tex_reader import CatCode, TexReader, TokenKind
from src.reading.token_cursor import TokenCursor
from src.reading.contracts import ScannedArgument


class CommandDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def setup_reader(self, source, *, preparation=False, catalog=None):
        self.resolver = BindingResolver(catalog or self.catalog)
        self.context = self.resolver.new_context()
        self.reader = TexReader(source, source_id="paper.tex", occurrence_id=7,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, self.resolver,
                                               preparation=preparation, source_commands=preparation)

    def complete(self):
        items = list(self.dispatcher)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in items), items[-1:])
        ReadingCoverage(self.reader.basis, items)
        return items

    def test_signature_and_exact_spans_without_synthetic_parameters(self):
        source = r"\newcommand * {\pair}[2][{a]b}]{#1:{#2}} tail"
        self.setup_reader(source)
        item = self.dispatcher.next_item()
        self.assertIsInstance(item, CommandDefinition)
        self.assertIsInstance(item, StoredDefinition)
        self.assertEqual(item.declaration, r"\newcommand")
        self.assertTrue(item.starred)
        self.assertEqual(item.parameter_count, 2)
        self.assertEqual(item.parameter_tokens, ())
        self.assertIsNone(item.hash_brace)
        self.assertEqual(self.reader.source_slice(item.target_argument.span), r"\pair")
        self.assertEqual(self.reader.source_slice(item.argument_count.span), "2")
        self.assertEqual(self.reader.source_slice(item.optional_default.span), "{a]b}")
        self.assertEqual(self.reader.source_slice(item.parameter_text), "[2][{a]b}]")
        self.assertEqual(self.reader.source_slice(item.body), "#1:{#2}")
        self.assertEqual(item.opening.end, item.body.start)
        self.assertEqual(item.body.end, item.closing.start)
        self.assertEqual(self.reader.position, source.index(" tail"))
        self.assertIs(self.context.lookup_definition("pair"), item)
        self.assertIsNotNone(item.unit_id)

    def test_unbraced_target_zero_count_and_empty_default(self):
        for header, count, default in ((r"\newcommand\x", 0, None),
                                       (r"\newcommand{\x}[0]", 0, None),
                                       (r"\newcommand\x[ 9 ][]", 9, "")):
            with self.subTest(header=header):
                self.setup_reader(header + "{}")
                item = self.complete()[0]
                self.assertFalse(item.starred)
                self.assertEqual(item.parameter_count, count)
                self.assertEqual(None if item.optional_default is None else item.optional_default.literal(), default)

    def test_captured_bodies_and_long_flags_match_recorded_kernel_oracle(self):
        expected = json.loads((PROJECT / "tests/fixtures/engine/command-bodies.expected.json").read_text(encoding="utf-8"))
        for name, source in (("word", r"\newcommand\x\varepsilon"),
                             ("letter", r"\newcommand\x A"),
                             ("star_par", r"\newcommand*\x\par"),
                             ("active", r"\newcommand\x~"),
                             ("group", r"\newcommand\x{{A}B}")):
            with self.subTest(name=name):
                self.setup_reader(source)
                item = self.complete()[0]
                # Only the captured body and long flag are compared here; this
                # does not pretend to implement meaning rendering or expansion.
                observed = ("" if item.starred else "\\long ") + "macro:->" + self.reader.source_slice(item.body)
                self.assertEqual(observed, expected[name])

    def test_unbraced_body_consumes_exactly_one_raw_token_with_exact_spans(self):
        for body, suffix in ((r"\varepsilon", " tail"), ("A", "BC"), ("~", "tail"),
                             (r"\makeatletter", " @"), (r"\unknown", "{next}")):
            with self.subTest(body=body):
                source = r"\newcommand\x " + body + suffix
                self.setup_reader(source)
                item = self.dispatcher.next_item()
                self.assertIsInstance(item, CommandDefinition)
                self.assertFalse(item.body_braced)
                self.assertEqual(len(item.body_tokens), 1)
                self.assertEqual(self.reader.source_slice(item.body), body)
                self.assertEqual(item.closing.start, item.closing.end)
                self.assertEqual(item.opening.end, item.body.start)
                self.assertEqual(item.body.end, item.span.end)
                self.assertEqual(self.reader.position, len(source) - len(suffix))
                self.assertEqual(self.reader.source_slice(self.reader.source_span(item.span.end, len(source))), suffix)
                self.assertIs(self.context.lookup_definition("x"), item)
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
                self.assertEqual(self.context.scope_depth, 0)
                ReadingCoverage(self.reader.basis, [item])

    def test_unbraced_body_preserves_stars_defaults_paragraphs_and_renewal_scope(self):
        self.setup_reader(r"\newcommand*\x[2][default]\par{\renewcommand\x\other}")
        items = self.complete()
        declarations = [i for i in items if isinstance(i, CommandDefinition)]
        self.assertEqual([d.body_tokens[0].value for d in declarations], ["par", "other"])
        self.assertTrue(declarations[0].starred)
        self.assertEqual(declarations[0].parameter_count, 2)
        self.assertEqual(declarations[0].optional_default.literal(), "default")
        self.assertIs(self.context.lookup_definition("x"), declarations[0])

    def test_unbraced_parameter_marker_does_not_consume_a_following_digit(self):
        self.setup_reader(r"\newcommand\x[1]#1TAIL")
        item = self.dispatcher.next_item()
        self.assertEqual(item.reason, "invalid_definition_parameter")
        self.assertIsNone(self.context.lookup_definition("x"))
        self.assertEqual(self.reader.next_token().value, "1")

    def test_unbraced_body_token_keeps_capture_time_category_in_replay(self):
        source = r"\newcommand\x@"
        self.setup_reader(source)
        tokens = tuple(self.reader)
        self.context.catcodes["@"] = CatCode.LETTER
        cursor = TokenCursor(ScannedArgument("body", self.reader.source_span(0, len(source)), tokens, "stored"), source, self.context)
        opener = cursor.next_token()
        item = DefinitionScanner(cursor, self.context).read(opener.span.start, self.resolver.resolve_command(opener.value))
        self.assertEqual(item.body_tokens[0].catcode, CatCode.OTHER)
        self.assertFalse(item.body_braced)
        self.assertIsNone(self.context.lookup_definition("x"))

    def test_unbraced_command_body_is_protected_during_deferred_observation(self):
        self.setup_reader(r"\begin{unknown}\newcommand\x\fi TEXT\end{unknown}", preparation=True)
        items = self.complete()
        self.assertIsInstance(items[0], DeferredRegion)
        self.assertEqual(self.reader.source_slice(items[0].span), self.reader.text)
        self.assertIsNone(self.context.lookup_definition("x"))

    def test_unbraced_implicit_paragraph_and_custom_group_categories(self):
        self.setup_reader("\\newcommand\\x\n\nTAIL")
        item = self.dispatcher.next_item()
        self.assertEqual(item.body_tokens[0].value, "par")
        self.assertFalse(item.body_braced)
        self.setup_reader(r"\newcommand\x(A(B)C)tail")
        self.context.catcodes["("] = CatCode.BEGIN_GROUP
        self.context.catcodes[")"] = CatCode.END_GROUP
        item = self.complete()[0]
        self.assertTrue(item.body_braced)
        self.assertEqual(self.reader.source_slice(item.body), "A(B)C")

    def test_scanner_only_captures_dispatcher_owns_registration(self):
        self.setup_reader(r"\newcommand{\x}{\newif\ifhidden\makeatletter}")
        token = self.reader.next_token()
        item = DefinitionScanner(self.reader, self.context).read(token.span.start, self.resolver.resolve_command(token.value))
        self.assertEqual(item.target_check, "unchecked")
        self.assertIsNone(self.context.lookup_definition("x"))
        self.assertIsNone(self.context.lookup_meaning("ifhidden"))
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)

    def test_bodies_and_defaults_neither_execute_nor_invalidate_booleans(self):
        source = (r"\newif\ifflag\flagtrue"
                  r"\newcommand{\x}[1][\flagfalse\input{missing}]{\unknown\makeatletter\def\inner##1{##1}}"
                  r"\ifflag YES\else NO\fi")
        self.setup_reader(source)
        items = self.complete()
        self.assertTrue(self.context.lookup_meaning("ifflag").truth)
        self.assertIsNone(self.context.lookup_meaning("ifflag").uncertain)
        self.assertIsNone(self.context.lookup_definition("inner"))
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        item = next(i for i in items if isinstance(i, CommandDefinition))
        self.assertIn("input", [t.value for t in item.optional_default.tokens])
        self.assertEqual(sum(t.catcode == CatCode.PARAMETER for t in item.body_tokens), 4)

    def test_scoped_renewal_restores_outer_definition_and_boolean_meaning(self):
        self.setup_reader(r"\newcommand\x{outer}{\renewcommand*\x[1]{#1}}"
                          r"\newif\ifflag{\renewcommand\ifflag{opaque}}\ifflag NO\else YES\fi")
        items = self.complete()
        declarations = [i for i in items if isinstance(i, CommandDefinition)]
        self.assertIs(self.context.lookup_definition("x"), declarations[0])
        self.assertEqual(declarations[1].target_check, "known_present")
        self.assertEqual(declarations[2].target_check, "known_present")
        self.assertFalse(self.context.lookup_meaning("ifflag").truth)
        self.assertEqual(self.context.scope_depth, 0)

    def test_renewal_shadows_bound_reading_handler_until_scope_ends(self):
        self.setup_reader(r"{\renewcommand\makeatletter{body}}\makeatletter")
        self.complete()
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)
        self.setup_reader(r"\renewcommand\makeatletter{body}\makeatletter")
        items = list(self.dispatcher)
        self.assertEqual(items[-1].reason, "stored_macro")
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_unbound_target_is_not_proof_of_undefinedness(self):
        for name, requirement in (("newcommand", "absent"), ("renewcommand", "present")):
            self.setup_reader("\\" + name + r"{\rmdefault}{ptm}")
            item = self.complete()[0]
            self.assertEqual(item.target_requirement, requirement)
            self.assertEqual(item.target_check, "unverified")
            self.assertIs(self.context.lookup_definition("rmdefault"), item)

    def test_known_newcommand_conflict_does_not_replace_existing_meaning(self):
        for prefix, target in ((r"\def\x{original}", "x"), ("", "makeatletter"), (r"\newif\ifflag", "ifflag")):
            with self.subTest(target=target):
                self.setup_reader(prefix + "\\newcommand{\\" + target + "}{replacement}")
                items = list(self.dispatcher)
                self.assertEqual(items[-1].reason, "definition_conflict")
                self.assertFalse(isinstance(self.context.lookup_definition(target), CommandDefinition))

    def test_invocation_is_deferred_without_expansion_or_definition_body_effects(self):
        self.setup_reader(r"\newcommand\x[1]{\makeatletter#1}\x{hello}TAIL", preparation=True)
        items = self.complete()
        self.assertTrue(any(isinstance(i, DeferredRegion) and i.reason == "stored_macro" for i in items))
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_definition_time_categories_comments_and_parameter_markers(self):
        self.setup_reader("\\makeatletter\\newcommand\\x@y[1]{@!1% comment }\n!!\\z@y}\\makeatother")
        self.context.catcodes["!"] = CatCode.PARAMETER
        self.context.catcodes["#"] = CatCode.OTHER
        items = self.complete()
        item = next(i for i in items if isinstance(i, CommandDefinition))
        self.assertEqual([t.value for t in item.body_tokens], ["@", "!", "1", "!", "!", "z@y"])
        self.assertEqual(item.body_tokens[0].catcode, CatCode.LETTER)
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_default_doubled_markers_preserved_and_par_in_body_allowed(self):
        self.setup_reader(r"\newcommand*\x[1][##]{\par#1}")
        item = self.complete()[0]
        self.assertEqual([t.value for t in item.optional_default.tokens], ["#", "#"])
        self.assertEqual([t.value for t in item.body_tokens], ["par", "#", "1"])

    def test_stored_literal_and_skipped_contexts_do_not_register_declarations(self):
        self.setup_reader(r"\def\outer{\newcommand\stored{body}}"
                          r"\verb|\newcommand\literal{body}|"
                          r"\iffalse\newcommand\skipped{body}\fi")
        self.complete()
        for name in ("stored", "literal", "skipped"):
            self.assertIsNone(self.context.lookup_definition(name))

    def test_deferred_environment_protects_definition_body_without_installing(self):
        self.setup_reader(r"\begin{unknown}\newcommand\x{\end{unknown}}tail\end{unknown}", preparation=True)
        items = self.complete()
        self.assertIsInstance(items[0], DeferredRegion)
        self.assertEqual(self.reader.source_slice(items[0].span), self.reader.text)
        self.assertIsNone(self.context.lookup_definition("x"))

    def test_stored_invocations_inside_deferred_environments_protect_their_envelopes(self):
        for declaration in (r"\def\x#1{#1}", r"\newcommand\x[1]{#1}"):
            source = declaration + r"\begin{unknown}\x{\end{unknown}}tail\end{unknown}AFTER"
            with self.subTest(declaration=declaration):
                self.setup_reader(source, preparation=True)
                items = self.complete()
                region = next(i for i in items if isinstance(i, DeferredRegion))
                self.assertEqual(self.reader.source_slice(region.span),
                                 r"\begin{unknown}\x{\end{unknown}}tail\end{unknown}")

    def test_stored_end_does_not_fall_back_to_environment_delimiter_binding(self):
        self.setup_reader(r"\renewcommand\end[1]{#1}\begin{unknown}body\end{unknown}", preparation=True)
        items = list(self.dispatcher)
        self.assertEqual(items[-1].reason, "unclosed_environment")

    def test_definition_body_verb_does_not_change_brace_scanning(self):
        self.setup_reader(r"\newcommand\x{\verb|}|tail")
        item = self.dispatcher.next_item()
        self.assertEqual(self.reader.source_slice(item.body), r"\verb|")
        self.assertEqual(self.dispatcher.next_item().token.value, "|")

    def test_bounded_rejections_are_located_without_installation(self):
        cases = (
            (r"\newcommand{\x\y}{}", "invalid_definition_target"),
            (r"\newcommand{\csname x\endcsname}{}", "invalid_definition_target"),
            (r"\newcommand~{}", "invalid_definition_target"),
            (r"\newcommand\endfoo{}", "invalid_definition_target"),
            (r"\newcommand\relax{}", "invalid_definition_target"),
            (r"\newcommand\x[\count]{}", "unsupported_definition_count"),
            (r"\newcommand\x[10]{}", "unsupported_definition_count"),
            (r"\newcommand\x[0][default]{}", "invalid_definition_default"),
            (r"\newcommand\x[1][#1]{}", "invalid_definition_parameter"),
            (r"\newcommand\x[1]{#2}", "invalid_definition_parameter"),
            (r"\newcommand\x{#}", "invalid_definition_parameter"),
            (r"\newcommand\x{", "unclosed_definition"),
            (r"\newcommand\x[1", "unclosed_argument"),
            (r"\newcommand\x", "argument_required"),
            (r"\newcommand\x}", "argument_required"),
        )
        for source, reason in cases:
            with self.subTest(source=source):
                self.setup_reader(source)
                item = self.dispatcher.next_item()
                self.assertIsInstance(item, ReadingBoundary)
                self.assertEqual(item.reason, reason)
                self.assertEqual(item.span.start, 0)
                self.assertIsNone(self.context.lookup_definition("x"))
                self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)

    def test_argument_count_requires_other_category(self):
        self.setup_reader(r"\newcommand\x[1]{}")
        self.context.catcodes["1"] = CatCode.LETTER
        self.assertEqual(self.dispatcher.next_item().reason, "unsupported_definition_count")

    def test_handler_is_selected_by_yaml_not_command_spelling(self):
        catalog = deepcopy(self.catalog)
        spec = next(c for c in catalog.engine_bindings["core_latex"]["reading"]["commands"] if c["name"] == r"\newcommand")
        spec["name"] = r"\declarelocal"
        self.setup_reader(r"\declarelocal\x{body}", catalog=reload_catalog(self, catalog))
        self.assertEqual(self.complete()[0].declaration, r"\declarelocal")

    def test_selected_option_captures_frozen_tokens_and_reports_pending_check(self):
        self.setup_reader(r"\DeclareOption{x}{\catcode`\!=11\relax\newcommand\kept{!}}"
                          r"\ProcessOptions", preparation=True)
        from reader_support import requested_options
        self.dispatcher.options = OptionScope("local", requested_options(self.context, ("x",)))
        items = self.complete()
        item = self.context.lookup_definition("kept")
        self.assertEqual(item.body_tokens[0].catcode, CatCode.OTHER)
        checks = next(i.metadata["definition_checks"] for i in items if getattr(i, "action", None) == "process_options")
        self.assertEqual(checks[0]["unit_id"], item.unit_id)
        self.assertEqual(checks[0]["requirement"], "absent")

    def test_schema_rejects_invalid_command_definition_recipes(self):
        for key, value in (("target_requirement", "any"), ("forbidden_names", "relax"),
                           ("forbidden_prefixes", [None]), ("expansion", "full")):
            reading = deepcopy(self.catalog.engine_bindings["core_latex"]["reading"])
            spec = next(c for c in reading["commands"] if c["name"] == r"\newcommand")
            spec["grammar"][key] = value
            with self.subTest(key=key), self.assertRaises(ProfileError):
                self.catalog._validate_reading(reading, Path("core_latex.yaml"))


class CommandPreparationTests(unittest.TestCase):
    def setUp(self):
        root = PROJECT / "temp" / "tests"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, text):
        (self.root / name).write_text(text, encoding="utf-8", newline="\n")

    def test_unbraced_definition_separates_control_word_after_removed_comment(self):
        self.put("main.tex", "\\documentclass{article}\n\\begin{document}\n"
                 "\\newcommand\\x\\varepsilon% comment\nTAIL\n\\end{document}\n")
        text, manifest, _, ledger = preprocess_paper(str(self.root))
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertIn(r"\newcommand\x\varepsilon TAIL", text)
        self.assertNotIn(r"\varepsilonTAIL", text)
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))

    def test_unbraced_body_and_following_group_remain_separate_in_preparation(self):
        self.put("main.tex", r"\documentclass{article}\input{child}")
        self.put("child.tex", r"\newcommand\x\varepsilon{\makeatletter}\input{tail}")
        self.put("tail.tex", "TAIL")
        text, manifest, _, ledger = preprocess_paper(str(self.root))
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertIn(r"\newcommand\x\varepsilon {\makeatletter }", text)
        self.assertIn("TAIL", text)
        self.assertNotIn(r"\input", text)
        self.assertTrue(ledger.resolve_source_line("child.tex", 1)["occurrences"])

    def test_unproven_separator_retains_child_without_manufacturing_a_letter(self):
        self.put("main.tex", r"\documentclass{article}\input{child}")
        child = r"\catcode32=11\relax\newcommand\x\varepsilon{}"
        self.put("child.tex", child)
        text, manifest, out, _ = preprocess_paper(str(self.root))
        self.assertEqual(manifest.preparation_status, "partial")
        self.assertEqual(manifest.unresolved[0]["reason"], "definition_separator")
        self.assertIn(r"\input{child.tex}", text)
        self.assertEqual((out / "child.tex").read_text(), child)

    def test_unchanged_style_copy_does_not_require_an_output_separator(self):
        self.put("main.tex", r"\documentclass{article}\usepackage{local}")
        style = r"\catcode32=11\relax\newcommand\x\varepsilon{}\catcode32=10\relax"
        self.put("local.sty", style)
        _, manifest, out, _ = preprocess_paper(str(self.root))
        self.assertEqual(manifest.preparation_status, "complete")
        self.assertEqual(manifest.unresolved, [])
        self.assertEqual((out / "local.sty").read_text(), style)

    def test_local_style_declarations_preserve_boolean_routing_and_final_locations(self):
        style = (r"\newif\ifload\loadtrue\renewcommand{\rmdefault}{ptm}"
                 r"\newcommand{\hidden}{\input{missing}\loadfalse}"
                 r"\ifload\RequirePackage{natbib}\fi")
        source = r"\documentclass{article}\usepackage{local}\input{child}\citep{a}\bibliography{refs}"
        child = r"\newcommand*\authored[1][{a]b}]{#1}\authored{X}"
        self.put("local.sty", style)
        self.put("main.tex", source)
        self.put("child.tex", child)
        self.put("refs.bib", "@misc{a,title={A}}")
        with patch("subprocess.run", side_effect=AssertionError("No compiler in preparation")):
            text, manifest, out, ledger = preprocess_paper(str(self.root))
        self.assertFalse(manifest.unresolved)
        self.assertIn("natbib", [p.name for p in manifest.packages_declared])
        self.assertIn(child, text)
        self.assertIn(r"\bibitem", text)
        self.assertEqual((out / "local.sty").read_text(), style)
        self.assertEqual((self.root / "main.tex").read_text(), source)
        self.assertEqual((self.root / "child.tex").read_text(), child)
        self.assertEqual(len(set(manifest.source_reads)), len(manifest.source_reads))
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))
        checks = [r for r in manifest.requirements if r["reason"] == "definition_precondition"]
        self.assertEqual(len(checks), 3)
        for check in checks:
            self.assertEqual(check["stage"], "interpretation")
            self.assertIsNotNone(check["unit_id"])
            self.assertTrue(check["locations"])
        self.assertFalse(any(r["reason"] == "package_not_loaded" for r in manifest.requirements))

    def test_option_replay_check_locates_the_retained_declaration(self):
        style = r"\DeclareOption{x}{\newcommand\kept{BODY}}\ProcessOptions"
        self.put("local.sty", style)
        self.put("main.tex", r"\documentclass{article}\usepackage[x]{local}TAIL")
        _, manifest, out, ledger = preprocess_paper(str(self.root))
        self.assertFalse(manifest.unresolved)
        check, = [r for r in manifest.requirements if r["reason"] == "definition_precondition"]
        location, = check["locations"]
        self.assertEqual(location["artifact"], "local.sty")
        self.assertEqual((out / location["artifact"]).read_text()[location["start"]:location["end"]],
                         r"\newcommand\kept{BODY}")
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))

    def test_default_dependencies_remain_visible_without_being_executed(self):
        self.put("main.tex", r"\documentclass{article}\newcommand\x[1][\input{default}]{\input{body}}TAIL")
        self.put("default.tex", "DEFAULT")
        self.put("body.tex", "BODY")
        text, manifest, _, _ = preprocess_paper(str(self.root))
        report = next(r for r in manifest.source_survey if r["source"] == "main.tex")
        inputs = [c for c in report["commands"] if c["name"] == "input"]
        self.assertEqual([c["context"] for c in inputs], ["stored_definition_default", "stored_definition"])
        self.assertNotIn("DEFAULT", text)
        self.assertNotIn("BODY", text)
        self.assertEqual({o["source"] for o in manifest.input_occurrences}, {"main.tex"})

    def test_repeated_scoped_inputs_keep_distinct_units_without_repeat_reads(self):
        child = r"\newcommand\x[1]{#1}"
        self.put("main.tex", r"\documentclass{article}{\input{child}}{\input{child}}TAIL")
        self.put("child.tex", child)
        text, manifest, _, ledger = preprocess_paper(str(self.root))
        self.assertFalse(manifest.unresolved)
        self.assertEqual(text.count(child), 2)
        declarations = [u for u in manifest.units if u["kind"] == "CommandDefinition"]
        self.assertEqual(len(declarations), 2)
        self.assertEqual(len({u["origin"]["occurrence"] for u in declarations}), 2)
        self.assertEqual(len({u["id"] for u in declarations}), 2)
        self.assertEqual(len(set(manifest.source_reads)), len(manifest.source_reads))
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))

    def test_unbound_environment_with_author_macro_does_not_hide_later_sources(self):
        self.put("main.tex", r"\documentclass{article}\newcommand\x[1]{#1}"
                 r"\begin{unknown}\x{CONTENT}\end{unknown}\input{later}\cite{a}\bibliography{refs}")
        self.put("later.tex", "LATER")
        self.put("refs.bib", "@misc{a,title={A}}")
        text, manifest, out, ledger = preprocess_paper(str(self.root))
        self.assertFalse(manifest.unresolved)
        self.assertIn("LATER", text)
        self.assertIn(r"\bibitem", text)
        self.assertTrue((out / "bibliography.bib").is_file())
        self.assertFalse(any(c["unaccounted"] for c in ledger.source_coverage))


if __name__ == "__main__":
    unittest.main()
