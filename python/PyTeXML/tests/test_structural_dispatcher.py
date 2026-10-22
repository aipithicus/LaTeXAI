"""Execution routing witnesses over immutable source and the shared mouth cursor."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.context import ExecutionMode
from src.reading.contracts import LiteralRegion, ReadingBoundary, StateManagementRule
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, EventKind, ReadEvent, ReaderState, TexReader


class StructuralDispatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def setup_reader(self, source, *, mode=ExecutionMode.ACTIVE_EXECUTION, outer_scope=False):
        self.resolver = BindingResolver(self.catalog)
        self.context = self.resolver.new_context(mode=mode)
        if outer_scope:
            self.context.push_scope()
        self.reader = TexReader(source, source_id="paper.tex", occurrence_id=4,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, self.resolver)
        return self.dispatcher

    def next_token(self):
        while (item := self.dispatcher.next_item()) is not None:
            self.assertIsInstance(item, ReadEvent)
            if item.token is not None:
                return item.token
        self.fail("Expected another token")

    def assert_complete(self):
        items = list(self.dispatcher)
        self.assertFalse(any(isinstance(item, ReadingBoundary) for item in items), items)
        return items

    @staticmethod
    def categories(items, character):
        return [item.token.catcode for item in items if isinstance(item, ReadEvent)
                and item.token is not None and item.token.value == character]

    def test_immediate_effect_preserves_converted_lookahead_and_command_boundary(self):
        self.setup_reader(r"\makeatletter^^40\makeatother @")
        first = self.next_token()
        self.assertEqual(first.value, "makeatletter")
        self.assertEqual(self.reader.source_slice(first.span), r"\makeatletter")
        self.assertEqual(self.reader.state, ReaderState.SKIP_BLANKS)
        self.assertEqual(self.reader.position, first.span.end)
        at = self.next_token()
        self.assertEqual((at.value, at.catcode), ("@", CatCode.LETTER))
        self.assertEqual(self.reader.source_slice(at.span), "^^40")
        self.assertTrue(at.transformed)
        self.assertEqual(self.next_token().value, "makeatother")
        self.assertEqual(self.next_token().catcode, CatCode.OTHER)

    def test_effect_is_in_force_when_next_control_word_is_read(self):
        self.setup_reader(r"\makeatletter\foo@bar")
        self.next_token()
        boundary = self.dispatcher.next_item()
        self.assertIsInstance(boundary, ReadingBoundary)
        self.assertEqual(boundary.reason, "unknown_construct")
        self.assertEqual(self.reader.source_slice(boundary.span), r"\foo@bar")

    def test_nested_brace_groups_restore_local_catcodes_in_place(self):
        self.setup_reader(r"{\makeatletter @{\makeatother @}@}@")
        table = self.context.catcodes
        items = self.assert_complete()
        self.assertEqual(self.categories(items, "@"), [CatCode.LETTER, CatCode.OTHER,
                                                     CatCode.LETTER, CatCode.OTHER])
        self.assertIs(self.reader.catcodes, table)
        self.assertIs(self.context.catcodes, table)
        self.assertEqual(self.context.scope_depth, 0)

    def test_command_groups_and_nested_brace_groups_restore_independently(self):
        self.setup_reader(r"\begingroup\makeatletter @{\makeatother @}@\endgroup @")
        items = self.assert_complete()
        self.assertEqual(self.categories(items, "@"), [CatCode.LETTER, CatCode.OTHER,
                                                     CatCode.LETTER, CatCode.OTHER])
        self.assertEqual(self.context.scope_depth, 0)

    def test_grouping_uses_categories_instead_of_brace_spelling(self):
        self.setup_reader(r"[\makeatletter @]@{}")
        for char, category in (("[", 1), ("]", 2), ("{", 12), ("}", 12)):
            self.context.catcodes[char] = category
        items = self.assert_complete()
        self.assertEqual(self.categories(items, "@"), [CatCode.LETTER, CatCode.OTHER])
        self.assertEqual(self.categories(items, "{"), [CatCode.OTHER])
        self.assertEqual(self.context.scope_depth, 0)

    def test_group_exit_keeps_exit_mouth_state(self):
        self.setup_reader(r"{\makeatletter a} b")
        for value in ("{", "makeatletter", "a", "}"):
            self.assertEqual(self.next_token().value, value)
        self.assertEqual(self.reader.state, ReaderState.MID_LINE)
        self.assertEqual(self.next_token().value, " ")
        self.assertEqual(self.next_token().value, "b")

    def test_effect_routing_is_independent_of_command_spelling(self):
        self.setup_reader(r"\letterize @")
        original = self.resolver.resolve_command
        profile = replace(original("makeatletter"), name=r"\letterize")
        with patch.object(self.resolver, "resolve_command", side_effect=lambda name:
                          profile if name == "letterize" else original(name)):
            items = self.assert_complete()
        self.assertEqual(self.categories(items, "@"), [CatCode.LETTER])

    def test_command_group_kind_comes_from_the_binding(self):
        self.setup_reader(r"\open\makeatletter @}@")
        original = self.resolver.resolve_command
        profile = replace(original("begingroup"), name=r"\open",
                          state_management=StateManagementRule(group_kind="simple"))
        with patch.object(self.resolver, "resolve_command", side_effect=lambda name:
                          profile if name == "open" else original(name)):
            items = self.assert_complete()
        self.assertEqual(self.categories(items, "@"), [CatCode.LETTER, CatCode.OTHER])
        self.assertEqual(self.context.scope_depth, 0)

    def test_literals_do_not_route_effects_or_group_tokens_from_their_bodies(self):
        self.setup_reader(r"{\makeatletter\verb|}\endgroup\makeatother\ExplSyntaxOn{|@}@")
        with patch.object(self.resolver, "resolve_command", wraps=self.resolver.resolve_command) as lookup:
            items = self.assert_complete()
        self.assertEqual([call.args[0] for call in lookup.call_args_list], ["makeatletter", "verb"])
        self.assertEqual(sum(isinstance(item, LiteralRegion) for item in items), 1)
        self.assertEqual(self.categories(items, "@"), [CatCode.LETTER, CatCode.OTHER])
        self.assertFalse(self.context.expl3_active)
        self.assertEqual(self.context.scope_depth, 0)

    def test_environment_header_braces_are_arguments_and_literal_scope_is_temporary(self):
        self.setup_reader(r"{\makeatletter\begin{verbatim}}\endgroup\makeatother\end{verbatim}@}@")
        with patch.object(self.resolver, "resolve_group", wraps=self.resolver.resolve_group) as lookup:
            items = self.assert_complete()
        self.assertEqual([call.args[0] for call in lookup.call_args_list], [CatCode.BEGIN_GROUP, CatCode.END_GROUP])
        self.assertEqual(self.categories(items, "@"), [CatCode.LETTER, CatCode.OTHER])
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)
        self.assertEqual(self.context.scope_depth, 0)

    def test_expl3_effect_timing_retains_the_current_physical_line_capture(self):
        self.setup_reader("\\ExplSyntaxOn\n_:\\ExplSyntaxOff\n_")
        self.assertEqual(self.next_token().value, "ExplSyntaxOn")
        self.assertEqual(self.reader.endline_char, 32)
        self.assertEqual(self.reader.current_line.endline_char, 13)
        self.assertEqual(self.reader.state, ReaderState.SKIP_BLANKS)
        first_end = self.dispatcher.next_item()
        self.assertEqual(first_end.kind, EventKind.END_OF_LINE)
        self.assertIsNone(first_end.token)
        for char in "_:":
            token = self.next_token()
            self.assertEqual((token.value, token.catcode), (char, CatCode.LETTER))
        self.assertEqual(self.reader.current_line.endline_char, 32)
        self.assertEqual(self.next_token().value, "ExplSyntaxOff")
        self.assertEqual(self.reader.endline_char, 13)
        self.assertEqual(self.reader.current_line.endline_char, 32)
        self.assertEqual(self.reader.state, ReaderState.SKIP_BLANKS)
        second_end = self.dispatcher.next_item()
        self.assertEqual(second_end.kind, EventKind.IGNORED_SPACE)
        self.assertEqual(self.reader.source_slice(second_end.span), "\n")
        self.assertEqual(self.next_token().catcode, CatCode.SUBSCRIPT)
        self.assertEqual(self.reader.current_line.endline_char, 13)

    def test_nested_expl3_exit_restores_outer_guard_and_saved_categories(self):
        self.setup_reader(r"\ExplSyntaxOn{\ExplSyntaxOff _}_:\ExplSyntaxOff _")
        items = self.assert_complete()
        self.assertEqual(self.categories(items, "_"), [CatCode.SUBSCRIPT, CatCode.LETTER, CatCode.SUBSCRIPT])
        self.assertFalse(self.context.expl3_active)
        self.assertEqual(self.context.expl3_saved_catcodes, {})
        self.assertEqual(self.context.endlinechar, 13)
        self.assertEqual(self.context.scope_depth, 0)

    def test_repeated_expl3_entry_preserves_the_original_snapshot(self):
        self.setup_reader(r"\ExplSyntaxOn\ExplSyntaxOn\ExplSyntaxOff :")
        self.context.catcodes[":"] = CatCode.LETTER
        self.context.catcodes["@"] = CatCode.LETTER
        self.assert_complete()
        self.assertEqual(self.context.catcodes[":"], CatCode.LETTER)
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)
        self.assertEqual(self.context.catcodes["_"], CatCode.SUBSCRIPT)
        self.assertFalse(self.context.expl3_active)

    def test_group_exit_restores_reader_parameter_without_reloading_the_line(self):
        self.setup_reader("{\\ExplSyntaxOn\nx} y\nz")
        self.assertEqual(self.next_token().value, "{")
        self.assertEqual(self.next_token().value, "ExplSyntaxOn")
        self.assertEqual(self.next_token().value, "x")
        self.assertEqual(self.next_token().value, "}")
        self.assertEqual(self.reader.endline_char, 13)
        self.assertEqual(self.reader.current_line.endline_char, 32)
        self.assertEqual(self.reader.state, ReaderState.MID_LINE)
        self.assertFalse(self.context.expl3_active)
        self.assertEqual(self.next_token().value, " ")
        self.assertEqual(self.next_token().value, "y")
        self.assertEqual(self.next_token().value, " ")
        self.assertEqual(self.next_token().value, "z")
        self.assertEqual(self.reader.current_line.endline_char, 13)

    def test_mismatched_group_kind_does_not_pop_or_restore_the_scope(self):
        for source, closer in ((r"{\makeatletter\endgroup", r"\endgroup"),
                               (r"\begingroup\makeatletter}", "}")):
            with self.subTest(source=source):
                self.setup_reader(source)
                items = list(self.dispatcher)
                boundary = items[-1]
                self.assertEqual(boundary.reason, "mismatched_group")
                self.assertEqual(self.reader.source_slice(boundary.remainder), closer)
                self.assertEqual(self.context.scope_depth, 1)
                self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)
                self.assertIsNone(self.dispatcher.next_item())

    def test_unmatched_closers_cannot_pop_a_callers_scope(self):
        for outer_scope in (False, True):
            for source in ("}", r"\endgroup"):
                with self.subTest(outer_scope=outer_scope, source=source):
                    self.setup_reader(source, outer_scope=outer_scope)
                    item = self.dispatcher.next_item()
                    self.assertEqual(item.reason, "unmatched_group")
                    self.assertEqual(self.context.scope_depth, int(outer_scope))

    def test_eof_diagnostic_has_opener_anchor_and_empty_unemitted_residue(self):
        source = r"{\makeatletter\begingroup @"
        self.setup_reader(source)
        items = list(self.dispatcher)
        boundary = items[-1]
        self.assertEqual(boundary.reason, "unclosed_group")
        self.assertEqual(self.reader.source_slice(boundary.span), r"\begingroup")
        self.assertEqual((boundary.remainder.start, boundary.remainder.end), (len(source), len(source)))
        self.assertEqual(self.context.scope_depth, 2)
        self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)
        self.assertIsNone(self.dispatcher.next_item())

    def test_inactive_modes_do_not_consume_or_resolve_effects(self):
        for mode in (ExecutionMode.STORED_DEFINITION, ExecutionMode.ARGUMENT_SCANNING, ExecutionMode.SKIPPED_BRANCH):
            with self.subTest(mode=mode):
                self.setup_reader(r"{\makeatletter\ExplSyntaxOn\begingroup}", mode=mode)
                with patch.object(self.resolver, "resolve_command", side_effect=AssertionError("Unexpected resolution")):
                    item = self.dispatcher.next_item()
                self.assertEqual(item.reason, "inactive_context")
                self.assertEqual(self.reader.position, 0)
                self.assertEqual(self.context.scope_depth, 0)
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_conditionals_remain_execution_boundaries(self):
        for construct in (r"\iftrue\makeatother\fi", r"\iffalse\makeatother\fi"):
            with self.subTest(construct=construct):
                self.setup_reader(r"{\makeatletter" + construct + "}")
                items = list(self.dispatcher)
                self.assertIsInstance(items[-1], ReadingBoundary)
                self.assertEqual(self.reader.source_slice(items[-1].remainder), construct + "}")
                self.assertEqual(self.context.scope_depth, 1)
                self.assertEqual(self.context.catcodes["@"], CatCode.LETTER)

    def test_dynamic_assignment_and_global_prefix_remain_unresolved(self):
        for source, reason in ((r"\catcode`\@=11", "arguments_required"),
                               (r"\global\makeatletter", "unknown_construct")):
            with self.subTest(source=source):
                self.setup_reader(source)
                item = self.dispatcher.next_item()
                self.assertEqual(item.reason, reason)
                self.assertEqual(self.reader.source_slice(item.remainder), source)
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_unhandled_implicit_scopes_stop_before_contained_effects(self):
        for source in (r"$\makeatletter$@", r"&\makeatletter"):
            with self.subTest(source=source):
                self.setup_reader(source)
                item = self.dispatcher.next_item()
                self.assertEqual(item.reason, "unsupported_structure")
                self.assertEqual(self.reader.source_slice(item.remainder), source)
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
                self.assertEqual(self.context.scope_depth, 0)

    def test_unsupported_resolved_effects_are_rejected_before_mutation(self):
        self.setup_reader("")
        base = self.resolver.resolve_command("makeatletter")
        candidates = (
            replace(base, action="unknown_action"),
            replace(base, action=None),
            replace(base, state_management=StateManagementRule(scope="global")),
            replace(base, grammar={"handler": "inline_character"}),
            replace(base, reader_parameters={"unknown_parameter": 1}),
            replace(base, action="push_lexical_scope", state_management=StateManagementRule(group_kind="simple")),
        )
        for profile in candidates:
            with self.subTest(profile=profile):
                self.setup_reader(r"\effect @")
                with patch.object(self.resolver, "resolve_command", return_value=profile):
                    item = self.dispatcher.next_item()
                self.assertIsInstance(item, ReadingBoundary)
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
                self.assertEqual(self.context.scope_depth, 0)

    def test_external_scope_or_parameter_changes_do_not_get_silently_adopted(self):
        for change in (lambda ctx: ctx.push_scope(), lambda ctx: setattr(ctx, "endlinechar", -1)):
            self.setup_reader(r"\makeatletter")
            change(self.context)
            item = self.dispatcher.next_item()
            self.assertEqual(item.reason, "context_changed")
            self.assertEqual(self.reader.position, 0)
            self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_comments_do_not_route_effects(self):
        self.setup_reader("% } \\makeatletter \\ExplSyntaxOn\r\n@")
        items = self.assert_complete()
        self.assertEqual(self.categories(items, "@"), [CatCode.OTHER])
        self.assertFalse(self.context.expl3_active)
        self.assertEqual(self.context.scope_depth, 0)

    def test_source_partition_survives_scopes_literals_and_diagnostics(self):
        for source in ("{\\makeatletter @\\verb|} \\makeatother|}\r\n@  ",
                       r"{\makeatletter @", r"{\endgroup suffix", r"\unknown{\makeatletter}"):
            with self.subTest(source=source):
                self.setup_reader(source)
                items = list(self.dispatcher)
                spans = [item.remainder if isinstance(item, ReadingBoundary) else item.span for item in items]
                self.assertEqual("".join(self.reader.source_slice(span) for span in spans), source)
                self.assertEqual([s.start for s in spans[1:]], [s.end for s in spans[:-1]])
                self.assertTrue(all((s.basis.source_id, s.basis.occurrence_id) == ("paper.tex", 4) for s in spans))
                self.assertEqual(self.reader.text, source)

    def test_dispatch_after_bootstrap_performs_no_file_io(self):
        self.setup_reader(r"{\makeatletter @\verb|literal|}\ExplSyntaxOn _\ExplSyntaxOff @")
        with patch("builtins.open", side_effect=AssertionError("Unexpected I/O")), \
             patch.object(Path, "open", side_effect=AssertionError("Unexpected I/O")):
            self.assert_complete()


if __name__ == "__main__":
    unittest.main()
