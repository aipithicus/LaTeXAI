"""Original-source spans and lexical resumption, independently expected from fixtures."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.context import ExecutionMode
from src.reading.dispatcher import LiteralDispatcher, LiteralRegion, ReadingBoundary
from src.reading.tex_reader import CatCode, EventKind, ReadEvent, ReaderState, TexReader


class LiteralDispatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def setup_reader(self, text, *, endlinechar=13, mode=ExecutionMode.ACTIVE_EXECUTION):
        self.resolver = BindingResolver(self.catalog)
        self.context = self.resolver.new_context(endlinechar=endlinechar, mode=mode)
        self.reader = TexReader(text, catcodes=self.context.catcodes, endline_char=endlinechar,
                                source_id="paper.tex", occurrence_id=3)
        self.dispatcher = LiteralDispatcher(self.reader, self.context, self.resolver)
        return self.dispatcher

    def assert_region(self, item, opening, body, closing):
        self.assertIsInstance(item, LiteralRegion)
        self.assertEqual([self.reader.source_slice(span) for span in
                          (item.opening, item.body, item.closing)], [opening, body, closing])
        self.assertEqual(self.reader.source_slice(item.span), opening + body + closing)
        for span in (item.span, item.opening, item.body, item.closing):
            self.assertEqual((span.source_id, span.occurrence_id), ("paper.tex", 3))

    def test_inline_opaque_body_and_normal_comment_after_exit(self):
        source = r"\verb|% \input{x} \endinput { \foo }| % real" + "\nZ"
        dispatch = self.setup_reader(source)
        literal = dispatch.next_item()
        self.assert_region(literal, r"\verb|", r"% \input{x} \endinput { \foo }", "|")
        self.assertEqual(self.reader.state, ReaderState.MID_LINE)
        self.assertEqual(self.reader.catcodes["%"], CatCode.COMMENT)
        space = dispatch.next_item()
        self.assertEqual(space.token.value, " ")
        self.assertEqual(dispatch.next_item().kind, EventKind.COMMENT)
        self.assertEqual(dispatch.next_item().token.value, "Z")
        self.assertEqual(self.reader.text, source)

    def test_star_and_delimiter_grammar(self):
        for source, opening, body, closing, name in (
            (r"\verb*+a b+", r"\verb*+", "a b", "+", r"\verb*"),
            (r"\verb**body*", r"\verb**", "body", "*", r"\verb*"),
            (r"\verb||", r"\verb|", "", "|", r"\verb"),
            (r"\verb%a%b", r"\verb%", "a", "%", r"\verb"),
            (r"\verb{a{z", r"\verb{", "a", "{", r"\verb"),
            (r"\verb^a^z", r"\verb^", "a", "^", r"\verb"),
            (r"\verb  |a|", r"\verb  |", "a", "|", r"\verb"),
            (r"\verb *a*", r"\verb *", "a", "*", r"\verb"),
            (r"\verb  XabcX", r"\verb  X", "abc", "X", r"\verb"),
            (r"\verb*  |a|", r"\verb*  |", "a", "|", r"\verb*"),
        ):
            with self.subTest(source=source):
                item = self.setup_reader(source).next_item()
                self.assert_region(item, opening, body, closing)
                self.assertEqual(item.name, name)

    def test_converted_opener_lookahead_survives_profile_change(self):
        dispatch = self.setup_reader(r"\verb^^7c^^7c|x")
        self.assert_region(dispatch.next_item(), r"\verb^^7c", "^^7c", "|")
        self.assertEqual(dispatch.next_item().token.value, "x")
        self.assertEqual(self.context.catcodes["^"], CatCode.SUPERSCRIPT)

    def test_inline_failure_never_reads_the_next_line(self):
        for endlinechar in (13, -1):
            for head, reason in ((r"\verb|unclosed  ", "unclosed_literal"),
                                 (r"\verb", "missing_delimiter")):
                source = head + "\r\n" + r"\input{later}"
                with self.subTest(endlinechar=endlinechar, source=source):
                    dispatch = self.setup_reader(source, endlinechar=endlinechar)
                    item = dispatch.next_item()
                    self.assertIsInstance(item, ReadingBoundary)
                    self.assertEqual(item.reason, reason)
                    self.assertEqual(self.reader.source_slice(item.remainder), source)
                    self.assertLessEqual(self.reader.position, len(head))
                    self.assertEqual(self.reader.current_line.span.start, 0)
                    self.assertEqual(self.context.catcodes["%"], CatCode.COMMENT)
                    self.assertIsNone(dispatch.next_item())

    def test_block_raw_crlf_trailing_spaces_and_same_line_suffix(self):
        source = "\\begin{verbatim}[literal]  \r\n% \\input{x}\t  \r\n\\end{verbatim} tail"
        dispatch = self.setup_reader(source)
        item = dispatch.next_item()
        self.assert_region(item, r"\begin{verbatim}", "[literal]  \r\n% \\input{x}\t  \r\n", r"\end{verbatim}")
        self.assertEqual(self.reader.state, ReaderState.MID_LINE)
        self.assertEqual(dispatch.next_item().token.value, " ")
        self.assertEqual(dispatch.next_item().token.value, "t")

    def test_header_comments_and_space_are_preserved(self):
        dispatch = self.setup_reader("\\begin % note\n{verbatim}x\\end{verbatim}")
        self.assert_region(dispatch.next_item(), "\\begin % note\n{verbatim}", "x", r"\end{verbatim}")

    def test_block_terminators_are_exact_token_sequences(self):
        body = r"\end {verbatim} \end{verbatim*} \end{verba\end{verbatimX}"
        dispatch = self.setup_reader(r"\begin{verbatim}" + body + r"\end{verbatim}Z")
        self.assert_region(dispatch.next_item(), r"\begin{verbatim}", body, r"\end{verbatim}")
        self.assertEqual(dispatch.next_item().token.value, "Z")
        dispatch = self.setup_reader(r"\begin{verbatim*}\end{verbatim}\end{verbatim*}")
        self.assert_region(dispatch.next_item(), r"\begin{verbatim*}", r"\end{verbatim}", r"\end{verbatim*}")

    def test_terminator_catcodes_are_not_redefined_by_later_assignments(self):
        source = r"\begin{verbatim}x\end{verbatim}"
        dispatch = self.setup_reader(source)
        # 'v' is in the argument/delimiter, but not in the control word 'begin'.
        self.context.catcodes["v"] = CatCode.OTHER
        item = dispatch.next_item()
        self.assertEqual(item.reason, "unclosed_literal")
        self.assertEqual(self.reader.source_slice(item.remainder), source)
        self.assertEqual(self.context.catcodes["v"], CatCode.OTHER)

    def test_block_matches_tokens_across_ignored_source_characters(self):
        closing = "\\end{verba\x00tim}"
        dispatch = self.setup_reader(r"\begin{verbatim}body" + closing)
        self.assert_region(dispatch.next_item(), r"\begin{verbatim}", "body", closing)
        closing = "\\end{verba  \r\ntim}"
        dispatch = self.setup_reader(r"\begin{verbatim}body" + closing, endlinechar=-1)
        self.assert_region(dispatch.next_item(), r"\begin{verbatim}", "body", closing)

    def test_literal_caret_notation_does_not_create_a_false_terminator(self):
        body = r"\end{verba^^74im}"
        dispatch = self.setup_reader(r"\begin{verbatim}" + body + r"\end{verbatim}")
        self.assert_region(dispatch.next_item(), r"\begin{verbatim}", body, r"\end{verbatim}")

    def test_exit_restores_parameter_but_keeps_current_line_capture(self):
        dispatch = self.setup_reader("\\begin{verbatim}\nbody\\end{verbatim}x\ny")
        profile = self.resolver.resolve_environment("verbatim")
        profile = replace(profile, reader_parameters={"endlinechar": 32})
        with patch.object(self.resolver, "resolve_environment", return_value=profile):
            item = dispatch.next_item()
        self.assertIsInstance(item, LiteralRegion)
        self.assertEqual(self.reader.endline_char, 13)
        self.assertEqual(self.context.endlinechar, 13)
        self.assertEqual(self.reader.current_line.endline_char, 32)
        self.assertEqual(dispatch.next_item().token.value, "x")
        self.assertEqual(dispatch.next_item().token.value, " ")
        self.assertEqual(dispatch.next_item().token.value, "y")
        self.assertEqual(self.reader.current_line.endline_char, 13)

    def test_repeated_literals_do_not_share_body_or_scope(self):
        dispatch = self.setup_reader(r"\verb|one|\verb+two+\begin{verbatim}three\end{verbatim}")
        table = self.context.catcodes
        items = [dispatch.next_item() for _ in range(3)]
        self.assertEqual([self.reader.source_slice(item.body) for item in items], ["one", "two", "three"])
        self.assertIs(self.context.catcodes, table)
        self.assertIs(self.reader.catcodes, table)
        self.assertEqual(table["|"], CatCode.OTHER)
        self.assertFalse(self.context.pop_scope())

    def test_unsupported_package_override_never_falls_back_to_kernel(self):
        for package, source in (("verbatim", r"\begin{verbatim}x\end{verbatim}"),
                                ("alltt", r"\begin{alltt}x\end{alltt}")):
            with self.subTest(package=package):
                dispatch = self.setup_reader(source)
                self.assertTrue(self.resolver.load_package(package))
                item = dispatch.next_item()
                self.assertIsInstance(item, ReadingBoundary)
                self.assertEqual(item.reason, "unsupported_literal_grammar")
                self.assertEqual(self.reader.source_slice(item.remainder), source)

    def test_definitions_conditionals_and_unknown_commands_are_frontiers(self):
        for source in (r"\def\x{\verb|body|}", r"\iffalse\verb|\fi|LIVE",
                       r"\unknown{\begin{verbatim}x\end{verbatim}}",
                       r"\begin{\which}body", r"\begin{document}body"):
            with self.subTest(source=source):
                dispatch = self.setup_reader(source)
                item = dispatch.next_item()
                self.assertIsInstance(item, ReadingBoundary)
                self.assertEqual(self.reader.source_slice(item.remainder), source)
                self.assertIsNone(dispatch.next_item())

    def test_inactive_modes_do_not_consume_or_dispatch(self):
        for mode in (ExecutionMode.STORED_DEFINITION, ExecutionMode.ARGUMENT_SCANNING,
                     ExecutionMode.SKIPPED_BRANCH):
            with self.subTest(mode=mode):
                dispatch = self.setup_reader(r"\verb|\fi|", mode=mode)
                item = dispatch.next_item()
                self.assertEqual(item.reason, "inactive_context")
                self.assertEqual(self.reader.position, 0)
                self.assertEqual(self.context.catcodes["%"], CatCode.COMMENT)

    def test_comment_and_paragraph_tokens_do_not_dispatch(self):
        dispatch = self.setup_reader("% \\verb|ignored|\n\nx")
        items = list(dispatch)
        self.assertTrue(all(isinstance(item, ReadEvent) for item in items))
        self.assertEqual(items[0].kind, EventKind.COMMENT)
        self.assertEqual(items[1].token.value, "par")

    def test_unclosed_block_and_invalid_character_retain_residue(self):
        for source, reason in ((r"\begin{verbatim}body", "unclosed_literal"),
                               ("\\verb|a\x7f|", "invalid_character"),
                               ("\\verb\ttext", "unsupported_literal_grammar")):
            with self.subTest(source=source):
                dispatch = self.setup_reader(source)
                item = dispatch.next_item()
                self.assertEqual(item.reason, reason)
                self.assertEqual(self.reader.source_slice(item.remainder), source)
                self.assertEqual(self.context.catcodes["%"], CatCode.COMMENT)
                self.assertFalse(self.context.pop_scope())

    def test_unexpected_literal_execution_stops_reading(self):
        for source in (r"\verb|a@b|", r"\begin{verbatim}a@b\end{verbatim}"):
            for category in (CatCode.ACTIVE, CatCode.ESCAPE, CatCode.BEGIN_GROUP,
                             CatCode.MATH_SHIFT, CatCode.ALIGNMENT_TAB, CatCode.PARAMETER):
                with self.subTest(source=source, category=category):
                    dispatch = self.setup_reader(source)
                    self.context.catcodes["@"] = category
                    item = dispatch.next_item()
                    self.assertEqual(item.reason, "unsupported_literal_grammar")
                    self.assertEqual(self.context.catcodes["@"], category)

    def test_handler_selection_does_not_depend_on_command_spelling(self):
        dispatch = self.setup_reader(r"\literal|body|")
        base = self.resolver.resolve_command("verb")
        with patch.object(self.resolver, "resolve_command", return_value=replace(base, name=r"\literal")):
            self.assert_region(dispatch.next_item(), r"\literal|", "body", "|")

    def test_reading_after_bootstrap_performs_no_file_io(self):
        dispatch = self.setup_reader(r"\verb|body|\begin{verbatim}text\end{verbatim}")
        with patch("builtins.open", side_effect=AssertionError("Unexpected file I/O")), \
             patch.object(Path, "open", side_effect=AssertionError("Unexpected path I/O")):
            items = list(dispatch)
        self.assertEqual(sum(isinstance(item, LiteralRegion) for item in items), 2)

    def test_events_regions_and_final_residue_partition_original_source(self):
        for source in ("text  % comment\r\n\\verb|a\x00b| tail  \r\n",
                       "a\\begin{verbatim}\r\n body  \r\n\\end{verbatim}z",
                       "a\\verb|x|\\unknown{rest}\n",
                       "a\\verb|unclosed  \r\nrest"):
            with self.subTest(source=source):
                items = list(self.setup_reader(source))
                spans = [item.remainder if isinstance(item, ReadingBoundary) else item.span for item in items]
                self.assertEqual("".join(self.reader.source_slice(span) for span in spans), source)
                self.assertEqual([span.start for span in spans[1:]], [span.end for span in spans[:-1]])

    def test_reader_context_identity_and_parameters_must_agree(self):
        self.setup_reader("x")
        with self.assertRaises(ValueError):
            LiteralDispatcher(self.reader, self.context.copy(), self.resolver)
        self.reader.endline_char = -1
        with self.assertRaises(ValueError):
            LiteralDispatcher(self.reader, self.context, self.resolver)


if __name__ == "__main__":
    unittest.main()
