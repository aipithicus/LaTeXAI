"""Bounded conditional execution, non-expanding skipping and source coverage."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.bindings.catalog import BindingCatalog
from reader_support import reload_catalog
from src.bindings.resolver import BindingResolver
from src.reading.context import ExecutionMode
from src.reading.contracts import LiteralRegion, ReadingBoundary, ReadingIssue, SkippedRegion, StoredDefinition
from src.reading.coverage import ReadingCoverage
from src.reading.definition_scanner import DefinitionScanner
from src.reading.dispatcher import StructuralDispatcher
from src.reading.skipped_scanner import SkippedBranchScanner
from src.reading.tex_reader import CatCode, ReadEvent, TexReader, TokenKind


class ConditionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def setup_reader(self, source, *, catalog=None, packages=(), catcodes=None):
        self.resolver = BindingResolver(reload_catalog(self, catalog) if catalog is not None else self.catalog)
        for name in packages:
            self.assertTrue(self.resolver.load_package(name))
        self.context = self.resolver.new_context()
        for char, category in (catcodes or {}).items():
            self.context.catcodes[char] = category
        self.reader = TexReader(source, source_id="paper.tex", occurrence_id=7,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, self.resolver)

    def scan(self, *, complete=True):
        items = list(self.dispatcher)
        spans = [item.remainder if isinstance(item, ReadingBoundary) else item.span for item in items]
        self.assertEqual("".join(self.reader.source_slice(span) for span in spans), self.reader.text)
        self.assertEqual([s.start for s in spans[1:]], [s.end for s in spans[:-1]])
        self.assertTrue(all(s.basis is self.reader.basis for s in spans))
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)
        self.assertIsNone(self.dispatcher.next_item())
        if complete:
            self.assertFalse(any(isinstance(item, ReadingBoundary) for item in items), items[-1:])
        else:
            self.assertIsInstance(items[-1], ReadingBoundary)
        return items

    def chars(self, items):
        return "".join(item.token.value for item in items if isinstance(item, ReadEvent)
                       and item.token and item.token.kind == TokenKind.CHARACTER
                       and item.token.catcode != CatCode.SPACE)

    def skipped_text(self, items):
        return [self.reader.source_slice(item.span) for item in items if isinstance(item, SkippedRegion)]

    def aliases(self):
        catalog = deepcopy(self.catalog)
        catalog.package_bindings["aliases"] = {"reading": {"conditionals": [
            {"name": r"\yes", "role": "opener", "evaluation": "always_true"},
            {"name": r"\no", "role": "opener", "evaluation": "always_false"},
            {"name": r"\otherwise", "role": "alternative"},
            {"name": r"\done", "role": "terminator"},
        ]}}
        return catalog

    def test_constant_branches_and_absent_alternatives(self):
        for source, live, skipped in (
                (r"\iftrue A\else B\fi C", "AC", [" B"]),
                (r"\iffalse A\else B\fi C", "BC", [" A"]),
                (r"\iftrue A\fi C", "AC", []),
                (r"\iffalse A\fi C", "C", [" A"])):
            with self.subTest(source=source):
                self.setup_reader(source)
                items = self.scan()
                self.assertEqual(self.chars(items), live)
                self.assertEqual(self.skipped_text(items), skipped)
                self.assertEqual(self.context.scope_depth, 0)

    def test_nested_executed_and_skipped_branches(self):
        self.setup_reader(r"\iftrue A\iffalse B\else C\fi D\else E\iftrue F\fi G\fi H")
        items = self.scan()
        self.assertEqual(self.chars(items), "ACDH")
        self.assertEqual(self.skipped_text(items), [" B", r" E\iftrue F\fi G"])

    def test_all_tex82_predicates_nest_without_argument_evaluation_while_skipping(self):
        predicates = ("if", "ifcat", "ifnum", "ifdim", "ifodd", "ifvmode", "ifhmode",
                      "ifmmode", "ifinner", "ifvoid", "ifhbox", "ifvbox", "ifx", "ifeof", "ifcase")
        for name in predicates:
            with self.subTest(name=name):
                self.setup_reader("\\iffalse A\\" + name + r" invalid\or B\else C\fi D\else E\fi F")
                self.assertEqual(self.chars(self.scan()), "EF")

    def test_unsupported_predicate_stops_before_arguments(self):
        for name in ("ifdim", "ifx"):
            source = "A\\" + name + r"\makeatletter\fi"
            with self.subTest(name=name):
                self.setup_reader(source)
                boundary = self.scan(complete=False)[-1]
                self.assertEqual(boundary.reason, "unsupported_conditional")
                self.assertEqual(self.reader.source_slice(boundary.remainder), source[1:])
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
                self.assertEqual(self.reader.position, 2 + len(name))

    def test_inert_skipped_content_has_no_execution_or_full_resolution(self):
        source = (r"\iffalse }{\endgroup\begingroup\def\x{body}\makeatletter\ExplSyntaxOn"
                  r"\catcode`\%=12\input{missing}\endinput\undefined\verb|% ignored\fi" "\n"
                  r"$&#~\fi @")
        self.setup_reader(source)
        with patch.object(self.dispatcher.literals, "read", side_effect=AssertionError("Literal executed")), \
             patch.object(DefinitionScanner, "read", side_effect=AssertionError("Definition scanned")), \
             patch.object(self.resolver, "resolve_command", wraps=self.resolver.resolve_command) as resolve:
            items = self.scan()
        self.assertEqual([call.args[0] for call in resolve.call_args_list], [])
        self.assertEqual(self.chars(items), "@")
        self.assertIsNone(self.context.lookup_definition("x"))
        self.assertEqual(self.context.scope_depth, 0)
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        self.assertFalse(self.context.expl3_active)

    def test_verbatim_is_not_a_fence_in_a_skipped_branch(self):
        self.setup_reader(r"\iffalse\verb|\fi|LIVE")
        items = self.scan()
        self.assertEqual(self.skipped_text(items), [r"\verb|"])
        self.assertEqual(self.chars(items), "|LIVE")
        self.assertFalse(any(isinstance(item, LiteralRegion) for item in items))

    def test_skipped_definition_does_not_hide_conditional_tokens_or_publish_meanings(self):
        self.setup_reader(r"\iffalse\def\x{\iftrue body\fi}\fi LIVE")
        items = self.scan()
        self.assertEqual(self.chars(items), "LIVE")
        self.assertEqual(self.skipped_text(items), [r"\def\x{\iftrue body\fi}"])
        self.assertIsNone(self.context.lookup_definition("x"))
        # Even the apparent target is a token in skipped text, not a definition.
        self.setup_reader(r"\iffalse\def\fi{body}")
        items = self.scan()
        self.assertEqual(self.skipped_text(items), [r"\def"])
        self.assertEqual(self.chars(items), "{body}")

    def test_active_literals_and_stored_definitions_hide_conditional_tokens(self):
        self.setup_reader(r"\iftrue\verb|\else\fi|\def\x{\else\fi}\else LOST\fi LIVE")
        items = self.scan()
        self.assertEqual(self.chars(items), "LIVE")
        self.assertEqual(sum(isinstance(i, LiteralRegion) for i in items), 1)
        self.assertEqual(sum(isinstance(i, StoredDefinition) for i in items), 1)
        self.assertIsNotNone(self.context.lookup_definition("x"))

    def test_conditionals_do_not_create_lexical_scopes(self):
        self.setup_reader(r"\iftrue{\makeatletter\fi @} @")
        items = self.scan()
        categories = [i.token.catcode for i in items if isinstance(i, ReadEvent) and i.token and i.token.value == "@"]
        self.assertEqual(categories, [CatCode.LETTER, CatCode.OTHER])
        self.assertEqual(self.context.scope_depth, 0)
        self.setup_reader(r"{\iftrue}\else\makeatletter\fi @")
        self.scan()
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_only_selected_branch_publishes_definitions_and_effects(self):
        for truth, chosen in (("iftrue", "yes"), ("iffalse", "no")):
            self.setup_reader("\\" + truth + r"\def\yes{}\makeatletter\else\def\no{}\fi @")
            self.scan()
            self.assertIsNotNone(self.context.lookup_definition(chosen))
            self.assertIsNone(self.context.lookup_definition("no" if chosen == "yes" else "yes"))
            self.assertEqual(self.context.catcodes["@"], CatCode.LETTER if chosen == "yes" else CatCode.OTHER)

    def test_aliases_use_declared_meanings_and_require_activation(self):
        catalog = self.aliases()
        self.setup_reader(r"\no A\yes B\done C\otherwise D\done E", catalog=catalog, packages=("aliases",))
        self.assertEqual(self.chars(self.scan()), "DE")
        self.setup_reader(r"\no A\done", catalog=catalog)
        self.assertEqual(self.scan(complete=False)[-1].reason, "package_not_loaded")
        self.assertIsNone(self.resolver.resolve_conditional("no"))

    def test_package_metadata_cannot_override_native_nesting_meaning(self):
        catalog = deepcopy(self.catalog)
        catalog.package_bindings["shadow"] = {"reading": {"commands": [{"name": r"\iftrue", "family": "opaque"}]}}
        self.setup_reader(r"\iffalse\iftrue X\fi\fi LIVE", catalog=catalog, packages=("shadow",))
        self.assertIsNone(self.resolver.resolve_conditional("iftrue"))
        self.assertEqual(self.chars(self.scan()), "LIVE")

    def test_stored_macros_shadow_conditional_meanings_even_when_spelling_matches(self):
        for name in ("iftrue", "else", "fi"):
            with self.subTest(name=name):
                source = "\\def\\" + name + "{}\\iffalse \\" + name + r"\done LIVE"
                self.setup_reader(source, catalog=self.aliases(), packages=("aliases",))
                items = self.scan()
                self.assertEqual(self.chars(items), "LIVE")
                self.assertEqual(self.skipped_text(items), [" \\" + name])
                self.setup_reader("\\def\\" + name + "{}\\" + name)
                self.assertEqual(self.scan(complete=False)[-1].reason, "stored_macro")

    def test_shadowed_openers_restore_with_source_scope(self):
        self.setup_reader(r"{\def\iftrue{}\iffalse\iftrue\fi}\iftrue LIVE\fi")
        self.assertEqual(self.chars(self.scan()), "{}LIVE")
        self.assertIsNone(self.context.lookup_definition("iftrue"))

    def test_conditional_looking_macro_bodies_are_not_expanded_during_skipping(self):
        self.setup_reader(r"\def\ifbogus{\iftrue}\def\done{\fi}\iffalse\ifbogus\done\fi LIVE")
        self.assertEqual(self.chars(self.scan()), "LIVE")
        self.setup_reader(r"\iffalse\ifundefined\newif\fi LIVE")
        self.assertEqual(self.chars(self.scan()), "LIVE")

    def test_scanner_uses_current_catcodes_comments_and_caret_translation(self):
        source = "\\iffalse % \\fi\r\n^^5ciftrue X^^5cfi Y^^5cfi LIVE"
        self.setup_reader(source)
        self.assertEqual(self.chars(self.scan()), "LIVE")
        self.setup_reader(r"\iffalse%\fi LIVE", catcodes={"%": CatCode.OTHER})
        self.assertEqual(self.skipped_text(self.scan()), ["%"])
        self.setup_reader(r"!iffalse \fi !fi LIVE", catcodes={"!": CatCode.ESCAPE, "\\": CatCode.OTHER})
        self.assertEqual(self.chars(self.scan()), "LIVE")

    def test_control_symbol_and_active_character_do_not_share_meanings(self):
        catalog = self.aliases()
        catalog.package_bindings["aliases"]["reading"]["conditionals"].append({"name": r"\~", "role": "terminator"})
        self.setup_reader(r"\def~{\fi}\iffalse~\~ LIVE", catalog=catalog, packages=("aliases",))
        self.assertEqual(self.chars(self.scan()), "LIVE")

    def test_empty_skips_retain_records_and_delimiters_are_emitted_once(self):
        for source, branch in ((r"\iffalse\fi", "then"), (r"\iftrue\else\fi", "else")):
            with self.subTest(source=source):
                self.setup_reader(source)
                items = self.scan()
                regions = [i for i in items if isinstance(i, SkippedRegion)]
                self.assertEqual(len(regions), 1)
                self.assertEqual(regions[0].span.start, regions[0].span.end)
                self.assertEqual(regions[0].branch, branch)
                self.assertEqual(self.reader.source_slice(regions[0].conditional), source[:source.index("\\", 1)])

    def test_delimiter_handoff_does_not_rescan_or_dispatch_the_following_token_early(self):
        self.setup_reader(r"\iffalse LOST\else\makeatletter @\fi")
        self.dispatcher.next_item()  # opener
        skipped = self.dispatcher.next_item()
        self.assertIsInstance(skipped, SkippedRegion)
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        position = self.reader.position
        with patch.object(self.reader, "next_event", side_effect=AssertionError("Delimiter rescanned")):
            event = self.dispatcher.next_item()
        self.assertEqual(event.token.value, "else")
        self.assertEqual(self.reader.position, position)
        self.dispatcher.next_item()
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)
        list(self.dispatcher)

    def test_skipping_preserves_mouth_state_and_pending_caret_conversion(self):
        for source in (r"\iffalse X\fi^^3f", "\\iffalse X\\fi   \r\nZ"):
            self.setup_reader(source)
            items = self.scan()
            self.assertEqual(self.chars(items), "?" if "^^" in source else "Z")
            # Compare the first post-delimiter event with uninterrupted mouth reading.
            baseline_context = self.resolver.new_context()
            baseline = TexReader(source, catcodes=baseline_context.catcodes,
                                 endline_char=baseline_context.endlinechar)
            events = []
            while (event := baseline.next_event()) is not None:
                events.append(event)
            actual = [i for i in items if isinstance(i, ReadEvent)]
            end = next(i for i in actual if i.token and i.token.value == "fi").span.end
            expected = [i for i in events if i.span.start >= end]
            tail = [i for i in actual if i.span.start >= end]
            self.assertEqual([(i.kind, i.state_before, i.state_after, i.span.start, i.span.end) for i in tail],
                             [(i.kind, i.state_before, i.state_after, i.span.start, i.span.end) for i in expected])

    def test_context_failure_during_handoff_keeps_the_unemitted_delimiter_in_residue(self):
        self.setup_reader(r"\iffalse LOST\else LIVE\fi")
        items = [self.dispatcher.next_item(), self.dispatcher.next_item()]
        self.context.push_scope()
        items.extend(self.dispatcher)
        self.assertEqual(items[-1].reason, "context_changed")
        self.assertEqual(self.reader.source_slice(items[-1].remainder), r"\else LIVE\fi")
        spans = [item.remainder if isinstance(item, ReadingBoundary) else item.span for item in items]
        self.assertEqual("".join(self.reader.source_slice(s) for s in spans), self.reader.text)
        report = ReadingCoverage(self.reader.basis, items)
        self.assertEqual(report.unknown.spans, (items[-1].remainder,))

    def test_extra_delimiters_and_active_duplicate_else_are_explicit(self):
        for source, reason in ((r"\fi suffix", "unmatched_conditional"),
                               (r"\else suffix", "unmatched_conditional"),
                               (r"\or suffix", "unmatched_conditional"),
                               (r"\iffalse A\else B\else C\fi", "extra_conditional_alternative"),
                               (r"\iftrue A\or B\fi", "unexpected_case_alternative"),
                               (r"\iffalse A\or B\fi", "unexpected_case_alternative")):
            with self.subTest(source=source):
                self.setup_reader(source)
                self.assertEqual(self.scan(complete=False)[-1].reason, reason)

    def test_discarded_else_branch_ignores_additional_else_and_or_until_fi(self):
        # TeX's terminate-and-skip route repeatedly calls pass_text until fi.
        self.setup_reader(r"\iftrue A\else B\else C\or D\fi E")
        items = self.scan()
        self.assertEqual(self.chars(items), "AE")
        self.assertEqual(self.skipped_text(items), [r" B\else C\or D"])

    def test_missing_closer_in_executed_branch_has_empty_residue(self):
        self.setup_reader(r"\iftrue A\iftrue B")
        items = self.scan(complete=False)
        boundary = items[-1]
        self.assertEqual(boundary.reason, "unclosed_conditional")
        self.assertEqual(boundary.span.start, self.reader.text.rindex(r"\iftrue"))
        self.assertEqual(boundary.remainder.start, len(self.reader.text))
        self.assertFalse(ReadingCoverage(self.reader.basis, items).unknown)

    def test_failed_skip_keeps_unobserved_tail_unknown_and_restores_mode(self):
        for source, reason in ((r"\iffalse tail", "unclosed_conditional"),
                               (r"\iftrue A\else tail", "unclosed_conditional"),
                               (r"\iffalse\iftrue\fi", "unclosed_conditional"),
                               ("\\iffalse X\x7f\\fi", "invalid_character")):
            with self.subTest(source=source):
                self.setup_reader(source)
                items = self.scan(complete=False)
                boundary = items[-1]
                self.assertEqual(boundary.reason, reason)
                report = ReadingCoverage(self.reader.basis, items)
                self.assertEqual(report.unknown.spans, (boundary.remainder,))
                self.assertEqual(report.skipped_regions, ())
                self.assertFalse(report.query("skipped").matches)

    def test_skipped_coverage_is_known_inactive_and_later_unresolved_tail_stays_unknown(self):
        self.setup_reader(r"\iffalse\verb|fake|\def\x{}\fi\verb|real|\unknown")
        items = self.scan(complete=False)
        report = ReadingCoverage(self.reader.basis, items)
        skipped = report.query("skipped")
        self.assertEqual(len(report.skipped_regions), 1)
        self.assertEqual(len(report.literal_regions), 1)
        self.assertEqual(report.stored_definitions, ())
        self.assertTrue(report.query("literal").nonmatches.covers(skipped.matches))
        self.assertEqual(skipped.unknown, report.unknown)
        self.assertFalse(skipped.negate().matches.intersection(report.unknown))
        self.assertIs(report.skipped_regions[0], items[1])
        window = self.reader.source_span(9, len(self.reader.text) - 1)
        self.assertEqual(report.query("skipped", window=window), skipped.restrict(window))
        with self.assertRaises(ValueError):
            report.query("skipped", part="body")

    def test_empty_skipped_coverage_retains_its_record(self):
        self.setup_reader(r"\iffalse\fi")
        report = ReadingCoverage(self.reader.basis, self.scan())
        self.assertEqual(len(report.skipped_regions), 1)
        self.assertFalse(report.query("skipped").matches)
        self.assertFalse(report.unknown)
        bad = replace(report.skipped_regions[0], conditional=self.reader.basis.whole)
        with self.assertRaises(ValueError):
            ReadingCoverage(self.reader.basis, (bad,))

    def test_standalone_scanner_neither_routes_terminator_nor_executes_content(self):
        self.setup_reader(r"\makeatletter\ifnum?\fi\else\makeatletter")
        scanner = SkippedBranchScanner(self.reader, self.context, self.resolver)
        result = scanner.read(stop_at_alternative=True)
        self.assertEqual(self.reader.source_slice(result.span), r"\makeatletter\ifnum?\fi")
        self.assertEqual(result.rule.role, "alternative")
        self.assertEqual(result.terminator.token.value, "else")
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        self.assertEqual(self.context.scope_depth, 0)
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)

    def test_scanner_declines_inactive_context_without_consuming(self):
        self.setup_reader(r"\fi")
        for mode in (ExecutionMode.ARGUMENT_SCANNING, ExecutionMode.STORED_DEFINITION, ExecutionMode.SKIPPED_BRANCH):
            with self.subTest(mode=mode), self.context.execution_mode(mode):
                with self.assertRaises(ReadingIssue):
                    self.dispatcher.skipped.read(stop_at_alternative=True)
                self.assertEqual(self.reader.position, 0)
                self.assertEqual(self.context.mode, mode)

    def test_deep_skipping_is_iterative_and_scanning_performs_no_file_io(self):
        source = r"\iffalse" + r"\ifnum" * 1500 + "🙂\r\n" + r"\fi" * 1501 + " LIVE"
        self.setup_reader(source)
        with patch("builtins.open", side_effect=AssertionError("Unexpected I/O")), \
             patch.object(Path, "open", side_effect=AssertionError("Unexpected I/O")):
            items = self.scan()
            report = ReadingCoverage(self.reader.basis, items)
        self.assertEqual(self.chars(items), "LIVE")
        self.assertFalse(report.unknown)
        self.assertEqual(len(report.skipped_regions), 1)


if __name__ == "__main__":
    unittest.main()
