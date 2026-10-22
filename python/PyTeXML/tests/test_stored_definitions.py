"""Definition-time token capture and dispatcher-owned local meaning witnesses.

Primitive parameter rules are taken from TeX82 scan_toks/get_r_token, not from
the implementation under test. No TeX engine is required or invoked.
"""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.context import ExecutionMode
from src.reading.contracts import LiteralRegion, ReadingBoundary, ReadingIssue, StoredDefinition
from src.reading.definition_scanner import DefinitionScanner
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, ReadEvent, ReaderState, TexReader, TokenKind


class StoredDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def setup_reader(self, source):
        self.resolver = BindingResolver(self.catalog)
        self.context = self.resolver.new_context()
        self.reader = TexReader(source, source_id="paper.tex", occurrence_id=7,
                                catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.dispatcher = StructuralDispatcher(self.reader, self.context, self.resolver)
        return self.dispatcher

    def complete(self):
        items = list(self.dispatcher)
        self.assertFalse(any(isinstance(item, ReadingBoundary) for item in items), items)
        return items

    def capture(self):
        item = self.dispatcher.next_item()
        self.assertIsInstance(item, StoredDefinition)
        return item

    def values(self, tokens):
        return [token.value for token in tokens]

    def test_capture_keeps_delimited_parameters_body_tokens_and_exact_spans(self):
        source = r"\def\pair prefix#1,#2;{[{#2}]#1} tail"
        self.setup_reader(source)
        definition = self.capture()
        self.assertEqual(definition.target.value, "pair")
        self.assertEqual(definition.parameter_count, 2)
        self.assertEqual(self.values(definition.parameter_tokens), list("prefix#1,#2;"))
        self.assertEqual(self.values(definition.body_tokens), list("[{#2}]#1"))
        self.assertEqual(self.reader.source_slice(definition.parameter_text), " prefix#1,#2;")
        self.assertEqual(self.reader.source_slice(definition.body), "[{#2}]#1")
        self.assertEqual(self.reader.source_slice(definition.opening), r"\def\pair prefix#1,#2;{")
        self.assertEqual(self.reader.source_slice(definition.closing), "}")
        self.assertEqual(definition.binding_id, "engine/core_latex")
        self.assertEqual(self.reader.position, source.index(" tail"))
        self.assertEqual(self.reader.state, ReaderState.MID_LINE)
        self.assertIs(self.context.lookup_definition("pair"), definition)
        self.assertEqual(self.dispatcher.next_item().token.value, " ")

    def test_bodies_do_not_dispatch_literals_effects_inclusions_or_nested_definitions(self):
        source = (r"\def\outerbody{\def\inner##1{##1}\verb|\fi|"
                  r"\begin{verbatim}\end{verbatim}\makeatletter\ExplSyntaxOn"
                  r"\input{missing}\endinput\begingroup\iffalse$&}" + "@")
        self.setup_reader(source)
        with patch.object(self.resolver, "resolve_command", wraps=self.resolver.resolve_command) as lookup, \
             patch.object(self.resolver, "resolve_group", side_effect=AssertionError("Body group executed")), \
             patch.object(self.resolver, "resolve_environment", side_effect=AssertionError("Body environment executed")):
            items = self.complete()
        self.assertEqual([call.args[0] for call in lookup.call_args_list], ["def"])
        self.assertIsNone(self.context.lookup_definition("inner"))
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        self.assertFalse(self.context.expl3_active)
        self.assertEqual(self.context.scope_depth, 0)
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)
        self.assertEqual([t.value for t in items[0].body_tokens if t.kind == TokenKind.CONTROL_SEQUENCE],
                         ["def", "inner", "verb", "fi", "begin", "end", "makeatletter", "ExplSyntaxOn",
                          "input", "endinput", "begingroup", "iffalse"])

    def test_apparent_verb_braces_have_ordinary_definition_scanning_behavior(self):
        self.setup_reader(r"\def\foo{\verb|}| tail")
        definition = self.capture()
        self.assertEqual(self.reader.source_slice(definition.body), r"\verb|")
        self.assertEqual(self.dispatcher.next_item().token.value, "|")
        self.assertEqual(self.context.scope_depth, 0)

    def test_definition_time_categories_survive_later_catcode_changes(self):
        self.setup_reader(r"\makeatletter\def\foo@bar{\foo@baz @\makeatother}\makeatother @")
        items = self.complete()
        definition = next(i for i in items if isinstance(i, StoredDefinition))
        self.assertEqual(definition.target.value, "foo@bar")
        self.assertEqual(self.values(definition.body_tokens), ["foo@baz", "@", "makeatother"])
        self.assertEqual(definition.body_tokens[1].catcode, CatCode.LETTER)
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)
        self.assertIs(self.context.lookup_definition("foo@bar"), definition)

    def test_definition_mode_uses_normal_comments_spaces_and_newline_tokens(self):
        self.setup_reader("\\def\\x{a% dropped } \\makeatletter\r\nb  \n\n c}")
        definition = self.capture()
        self.assertEqual(self.values(definition.body_tokens), ["a", "b", " ", "par", "c"])
        self.assertEqual(self.reader.source_slice(definition.body), "a% dropped } \\makeatletter\r\nb  \n\n c")
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_double_markers_remain_lexical_tokens_for_later_compilation(self):
        self.setup_reader(r"\def\outerbody#1{\def\inner##1{#1##1}}")
        definition = self.capture()
        self.assertEqual(definition.parameter_count, 1)
        self.assertEqual(self.values(definition.body_tokens), ["def", "inner", "#", "#", "1", "{", "#", "1", "#", "#", "1", "}"])
        for token in definition.body_tokens:
            if token.catcode == CatCode.PARAMETER:
                self.assertEqual(self.reader.source_slice(token.span), "#")

    def test_escaped_braces_do_not_nest_but_category_one_and_two_do(self):
        self.setup_reader(r"\def\x[\{\}[]{}]")
        for char, category in (("[", 1), ("]", 2), ("{", 12), ("}", 12)):
            self.context.catcodes[char] = category
        definition = self.capture()
        self.assertEqual(self.reader.source_slice(definition.body), r"\{\}[]{}")
        self.assertEqual([t.catcode for t in definition.body_tokens],
                         [None, None, CatCode.BEGIN_GROUP, CatCode.END_GROUP, CatCode.OTHER, CatCode.OTHER])
        self.assertEqual(self.context.scope_depth, 0)

    def test_parameter_category_is_not_hardcoded_to_hash(self):
        self.setup_reader(r"\def\x!1{#!!1!1}")
        self.context.catcodes["!"] = CatCode.PARAMETER
        self.context.catcodes["#"] = CatCode.OTHER
        definition = self.capture()
        self.assertEqual(definition.parameter_count, 1)
        self.assertEqual(self.values(definition.parameter_tokens), ["!", "1"])
        self.assertEqual(self.values(definition.body_tokens), list("#!!1!1"))
        self.assertEqual(definition.body_tokens[0].catcode, CatCode.OTHER)

    def test_digit_tokens_need_other_category(self):
        self.setup_reader(r"\def\x#1{#1}")
        self.context.catcodes["1"] = CatCode.LETTER
        boundary = self.dispatcher.next_item()
        self.assertEqual(boundary.reason, "invalid_definition_parameter")
        self.assertIsNone(self.context.lookup_definition("x"))

    def test_special_hash_brace_is_recorded_without_synthesizing_source_tokens(self):
        for header, count in (("#", 0), ("#1#", 1), ("#1#2#3#4#5#6#7#8#9#", 9)):
            with self.subTest(header=header):
                self.setup_reader(r"\def\x" + header + "{body}")
                definition = self.capture()
                self.assertEqual(definition.parameter_count, count)
                self.assertEqual(self.values(definition.parameter_tokens), list(header))
                self.assertEqual(self.reader.source_slice(definition.hash_brace.span), "{")
                self.assertEqual(definition.hash_brace.catcode, CatCode.BEGIN_GROUP)
                self.assertEqual(self.values(definition.body_tokens), list("body"))

    def test_nine_parameters_and_repeated_body_references(self):
        self.setup_reader(r"\def\x#1#2#3#4#5#6#7#8#9{#9#1#9}")
        definition = self.capture()
        self.assertEqual(definition.parameter_count, 9)
        self.assertEqual(self.values(definition.body_tokens), list("#9#1#9"))

    def test_invalid_parameters_never_install_a_definition(self):
        for header, body in (("#2", ""), ("#0", ""), ("##", ""), ("#1#1", ""),
                             ("#1#2#3#4#5#6#7#8#9#1", ""),
                             ("", "#1"), ("#1", "#2"), ("#1", "#0"),
                             ("", "#"), ("", r"#\makeatletter"), ("", "#{")):
            with self.subTest(header=header, body=body):
                source = r"\def\x" + header + "{" + body + "}"
                self.setup_reader(source)
                boundary = self.dispatcher.next_item()
                self.assertEqual(boundary.reason, "invalid_definition_parameter")
                self.assertEqual(self.reader.source_slice(boundary.remainder), source)
                self.assertIsNone(self.context.lookup_definition("x"))
                self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)

    def test_control_symbol_parameter_text_keeps_its_leading_space(self):
        self.setup_reader(r"\def\! #1;{#1}")
        definition = self.capture()
        self.assertEqual(definition.target.value, "!")
        self.assertEqual(self.values(definition.parameter_tokens), list(" #1;"))

    def test_active_character_and_same_spelled_control_symbol_are_distinct(self):
        self.setup_reader(r"\def~{active}\def\~{control}")
        definitions = [i for i in self.complete() if isinstance(i, StoredDefinition)]
        self.assertEqual(len(definitions), 2)
        self.assertIs(self.context.lookup_definition("~", TokenKind.ACTIVE_CHARACTER), definitions[0])
        self.assertIs(self.context.lookup_definition("~"), definitions[1])

    def test_active_invocation_is_a_stored_macro_boundary(self):
        self.setup_reader(r"\def~{\makeatletter}~@")
        self.capture()
        boundary = self.dispatcher.next_item()
        self.assertEqual(boundary.reason, "stored_macro")
        self.assertEqual(self.reader.source_slice(boundary.remainder), "~@")
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_implicit_paragraph_cannot_bypass_a_stored_redefinition(self):
        self.setup_reader("\\def\\par{\\makeatletter}\n\n@")
        self.capture()
        self.assertIsInstance(self.dispatcher.next_item(), ReadEvent)
        boundary = self.dispatcher.next_item()
        self.assertEqual(boundary.reason, "stored_macro")
        self.assertEqual(self.reader.source_slice(boundary.remainder), "\n@")
        self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_redefinitions_shadow_all_command_routes_including_def_itself(self):
        for name in ("verb", "makeatletter", "ExplSyntaxOn", "begingroup", "begin", "def", "unknown"):
            with self.subTest(name=name):
                self.setup_reader("\\def\\" + name + "{\\makeatletter}\\" + name + "{tail}")
                with patch.object(self.resolver, "resolve_command", wraps=self.resolver.resolve_command) as lookup:
                    self.capture()
                    boundary = self.dispatcher.next_item()
                self.assertEqual(boundary.reason, "stored_macro")
                self.assertEqual([call.args[0] for call in lookup.call_args_list], ["def"])
                self.assertEqual(self.context.scope_depth, 0)
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_redefined_environment_entry_or_exit_cannot_use_literal_binding(self):
        for name in ("verbatim", "endverbatim"):
            with self.subTest(name=name):
                source = "\\def\\" + name + "{custom}\\begin{verbatim}body\\end{verbatim}"
                self.setup_reader(source)
                self.capture()
                with patch.object(self.resolver, "resolve_environment", side_effect=AssertionError("Stale environment route")):
                    boundary = self.dispatcher.next_item()
                self.assertEqual(boundary.reason, "stored_macro")
                self.assertEqual(self.reader.source_slice(boundary.remainder), r"\begin{verbatim}body\end{verbatim}")

    def test_local_shadow_disappears_after_brace_or_command_group(self):
        for opening, closing in (("{", "}"), (r"\begingroup", r"\endgroup")):
            with self.subTest(opening=opening):
                self.setup_reader(opening + r"\def\verb{custom}" + closing + r"\verb|literal|")
                items = self.complete()
                self.assertEqual(sum(isinstance(i, LiteralRegion) for i in items), 1)
                self.assertIsNone(self.context.lookup_definition("verb"))
                self.assertEqual(self.context.scope_depth, 0)

    def test_nested_and_repeated_redefinitions_restore_first_outer_meaning(self):
        self.setup_reader(r"\def\x{outer}{\def\x{middle}\def\x{again}{\def\x{inner}}}")
        outer = self.capture()
        self.complete()
        self.assertIs(self.context.lookup_definition("x"), outer)

    def test_unknown_meaning_is_restored_after_local_definition(self):
        self.setup_reader(r"{\def\unknown{body}}\unknown")
        items = list(self.dispatcher)
        self.assertEqual(items[-1].reason, "unknown_construct")
        self.assertIsNone(self.context.lookup_definition("unknown"))

    def test_copied_context_has_independent_meanings_and_scope_journals(self):
        self.setup_reader(r"\def\x{outer}{\def\x{inner}")
        outer = self.capture()
        self.dispatcher.next_item()
        inner = self.capture()
        copied = self.context.copy()
        self.assertIs(copied.lookup_definition("x"), inner)
        self.assertTrue(copied.pop_scope())
        self.assertIs(copied.lookup_definition("x"), outer)
        self.assertIs(self.context.lookup_definition("x"), inner)
        self.assertEqual(self.context.scope_depth, 1)
        self.assertTrue(self.context.pop_scope())
        self.assertIs(self.context.lookup_definition("x"), outer)

    def test_scanner_returns_capture_without_installing_and_restores_mode(self):
        self.setup_reader(r"\def\verb{body}")
        command = self.reader.next_event()
        scanner = DefinitionScanner(self.reader, self.context)
        modes = []
        original = self.reader.next_token
        def next_token():
            modes.append(self.context.mode)
            return original()
        with patch.object(self.reader, "next_token", side_effect=next_token):
            definition = scanner.read(command.span.start, self.resolver.resolve_command("def"))
        self.assertIsInstance(definition, StoredDefinition)
        self.assertTrue(modes)
        self.assertEqual(set(modes), {ExecutionMode.STORED_DEFINITION})
        self.assertIsNone(self.context.lookup_definition("verb"))
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)
        with self.context.stored_definition(), self.assertRaises(ValueError):
            self.context.record_definition(definition)

    def test_scanner_rejects_inactive_call_without_consuming(self):
        self.setup_reader(r"\def\x{body}")
        self.reader.next_event()
        position = self.reader.position
        with self.context.argument_scanning(), self.assertRaises(ReadingIssue) as error:
            DefinitionScanner(self.reader, self.context).read(0, self.resolver.resolve_command("def"))
        self.assertEqual(error.exception.reason, "inactive_context")
        self.assertEqual(self.reader.position, position)

    def test_routing_uses_binding_grammar_not_command_spelling(self):
        self.setup_reader(r"\declare\x{body}")
        profile = replace(self.resolver.resolve_command("def"), name=r"\declare")
        with patch.object(self.resolver, "resolve_command", return_value=profile):
            definition = self.capture()
        self.assertEqual(self.reader.source_slice(definition.span), r"\declare\x{body}")
        self.assertIs(self.context.lookup_definition("x"), definition)

    def test_expanding_global_prefixed_and_wrapper_forms_remain_boundaries(self):
        for command in ("edef", "gdef", "xdef", "global", "long", "outer", "protected", "newcommand", "renewcommand"):
            with self.subTest(command=command):
                source = "\\" + command + r"\x{\makeatletter}"
                self.setup_reader(source)
                boundary = self.dispatcher.next_item()
                self.assertIsInstance(boundary, ReadingBoundary)
                self.assertEqual(self.reader.source_slice(boundary.remainder), source)
                self.assertEqual(self.reader.position, len(command) + 1)
                self.assertIsNone(self.context.lookup_definition("x"))
                self.assertEqual(self.context.catcodes["@"], CatCode.OTHER)

    def test_failed_redefinition_does_not_replace_previous_meaning(self):
        self.setup_reader(r"\def\x{good}\def\x{missing")
        good = self.capture()
        boundary = self.dispatcher.next_item()
        self.assertEqual(boundary.reason, "unclosed_definition")
        self.assertIs(self.context.lookup_definition("x"), good)
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)
        self.assertIsNone(self.dispatcher.next_item())

    def test_missing_target_opener_and_body_closer_are_located_boundaries(self):
        cases = ((r"\def", "unclosed_definition"), (r"\def x{}", "invalid_definition_target"),
                 (r"\def\x}", "invalid_definition"), (r"\def\x prefix", "unclosed_definition"),
                 (r"\def\x{nested{body}", "unclosed_definition"))
        for source, reason in cases:
            with self.subTest(source=source):
                self.setup_reader(source)
                boundary = self.dispatcher.next_item()
                self.assertEqual(boundary.reason, reason)
                self.assertEqual(self.reader.source_slice(boundary.span), r"\def")
                self.assertEqual(self.reader.source_slice(boundary.remainder), source)
                self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)
                self.assertEqual(self.context.scope_depth, 0)
                self.assertIsNone(self.context.lookup_definition("x"))

    def test_invalid_character_in_body_is_preserved_and_does_not_install(self):
        source = "\\def\\x{a\x7fb}tail"
        self.setup_reader(source)
        boundary = self.dispatcher.next_item()
        self.assertEqual(boundary.reason, "invalid_character")
        self.assertEqual(self.reader.source_slice(boundary.remainder), source)
        self.assertIsNone(self.context.lookup_definition("x"))
        self.assertEqual(self.context.mode, ExecutionMode.ACTIVE_EXECUTION)

    def test_caret_conversion_retains_original_token_occurrences(self):
        self.setup_reader(r"\def\x^^7b^^41\^^7b^^7d")
        definition = self.capture()
        self.assertEqual(self.values(definition.body_tokens), ["A", "{"])
        self.assertEqual([self.reader.source_slice(t.span) for t in definition.body_tokens], ["^^41", r"\^^7b"])
        self.assertTrue(all(t.transformed for t in definition.body_tokens))
        self.assertEqual(self.reader.source_slice(definition.closing), "^^7d")

    def test_empty_definition_body_and_parameter_text_have_empty_token_lists(self):
        self.setup_reader(r"\def\x{}")
        definition = self.capture()
        self.assertEqual(definition.parameter_tokens, ())
        self.assertEqual(definition.body_tokens, ())
        self.assertEqual(definition.parameter_count, 0)
        self.assertEqual(definition.body.start, definition.body.end)
        self.assertIsNone(definition.hash_brace)

    def test_source_partition_and_definition_subspans_cover_unchanged_source(self):
        for source in ("{\\def\\x#1{#1%comment\r\n}}\\verb|text|  ",
                       r"\def\x#{body}\x", r"{\def\x{body}", r"a\def\x#2{oops}"):
            with self.subTest(source=source):
                self.setup_reader(source)
                items = list(self.dispatcher)
                spans = [item.remainder if isinstance(item, ReadingBoundary) else item.span for item in items]
                self.assertEqual("".join(self.reader.source_slice(s) for s in spans), source)
                self.assertEqual([s.start for s in spans[1:]], [s.end for s in spans[:-1]])
                for item in items:
                    if isinstance(item, StoredDefinition):
                        parts = (item.opening, item.body, item.closing)
                        self.assertEqual("".join(self.reader.source_slice(s) for s in parts), self.reader.source_slice(item.span))
                        for token in (item.target, *item.parameter_tokens, *item.body_tokens):
                            self.assertEqual((token.span.basis.source_id, token.span.basis.occurrence_id), ("paper.tex", 7))
                            self.assertGreaterEqual(token.span.start, item.span.start)
                            self.assertLessEqual(token.span.end, item.span.end)
                self.assertEqual(self.reader.text, source)

    def test_deep_definition_scanning_is_iterative_and_performs_no_file_io(self):
        source = r"\def\x{" + "{" * 1500 + "a" + "}" * 1501
        self.setup_reader(source)
        with patch("builtins.open", side_effect=AssertionError("Unexpected I/O")), \
             patch.object(Path, "open", side_effect=AssertionError("Unexpected I/O")):
            definition = self.capture()
            self.complete()
        self.assertEqual(len(definition.body_tokens), 3001)
        self.assertEqual(self.context.scope_depth, 0)


if __name__ == "__main__":
    unittest.main()
