"""Operand, value, scope and source-preservation witnesses for code assignments."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.engine.integers import IntegerScanner
from src.reading.contracts import CharacterCodeMeaning, ReadingBoundary, ReadingIssue, ScannedArgument, SourceCommand
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader, TokenKind
from src.reading.token_cursor import TokenCursor


class IntegerOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()
        cls.oracle = json.loads((Path(__file__).parent / "fixtures/engine/integers.expected.json").read_text(encoding="utf-8"))

    def host(self, text, *, preparation=False):
        knowledge = BindingResolver(self.catalog)
        context = knowledge.new_context()
        reader = TexReader(text, catcodes=context.catcodes, endline_char=-1)
        context.endlinechar = -1
        return StructuralDispatcher(reader, context, knowledge, preparation=preparation)

    def run_source(self, text, **kwargs):
        host = self.host(text, **kwargs)
        items = list(host)
        self.assertFalse([i for i in items if isinstance(i, ReadingBoundary)], items)
        return host, items

    def test_shared_integer_forms_and_signed_limit(self):
        for source, expected in (("--+ 12 ", 12), ("- '17 ", -self.oracle["octal"]), ('"AF ', self.oracle["hex"]),
                                 (r"`\@ ", 64), ("`x ", self.oracle["rawbacktick"]), ("2147483647", 2147483647),
                                 ("-2147483647", -2147483647)):
            with self.subTest(source=source):
                self.assertEqual(IntegerScanner(self.host(source)).integer(), expected)
        for source in ("2147483648", "-2147483648", "'8", '"ff', "`"):
            with self.subTest(source=source), self.assertRaises(ReadingIssue):
                IntegerScanner(self.host(source)).integer()

    def test_digit_categories_and_hex_letter_categories(self):
        host = self.host("12 ")
        host.context.catcodes["1"] = CatCode.LETTER
        with self.assertRaises(ReadingIssue):
            IntegerScanner(host).integer()
        host = self.host('"AF ')
        host.context.catcodes["A"] = CatCode.OTHER
        self.assertEqual(IntegerScanner(host).integer(), 175)

    def test_t6_save_change_restore_and_freeze_lookahead(self):
        host, items = self.run_source(r"\chardef\saved=\catcode`\@ \catcode`\@=11@ @\catcode`\@=\saved @")
        self.assertEqual(host.context.lookup_meaning("saved").value, self.oracle["saved"])
        ats = [i.token.catcode for i in items if getattr(i, "token", None) and i.token.value == "@"]
        self.assertEqual([cat.name for cat in ats[:2]], self.oracle["terminators"])
        self.assertEqual(ats[-1], self.oracle["restored"])
        self.assertEqual(host.context.catcodes["@"], self.oracle["restored"])

    def test_scoped_values_and_let_copies_the_value(self):
        host, items = self.run_source(r"\chardef\saved=12 {\chardef\saved=11 \let\copy\saved\chardef\saved=10 \catcode64=\copy @}\catcode64=\saved @")
        ats = [i.token.catcode for i in items if getattr(i, "token", None) and i.token.value == "@"]
        self.assertEqual(ats, [self.oracle["copied"], self.oracle["outer"]])
        self.assertIsNone(host.context.lookup_meaning("copy"))

    def test_primitive_aliases_use_current_meanings_for_both_roles(self):
        host, _ = self.run_source(r"\let\code\catcode\let\definecode\chardef\definecode\saved=\code64 \code64=11 \catcode64=\saved ")
        self.assertEqual(host.context.lookup_meaning("saved").value, 12)
        self.assertEqual(host.context.catcodes["@"], CatCode.OTHER)

    def test_redefined_catcode_is_not_read_by_spelling(self):
        host = self.host(r"\def\catcode{12}\chardef\saved=\catcode64 ")
        items = list(host)
        # The redefined command expands to digits, giving 1264 rather than
        # reading category 64 through the shadowed primitive.
        self.assertEqual(items[-1].reason, "invalid_assignment")
        self.assertIsNone(host.context.lookup_meaning("saved"))

    def test_stored_and_skipped_code_assignments_do_not_install_values(self):
        host, _ = self.run_source(r"\def\later{\chardef\saved=11 }\iffalse\chardef\never=12 \fi")
        self.assertIsNone(host.context.lookup_meaning("saved"))
        self.assertIsNone(host.context.lookup_meaning("never"))

    def test_internal_values_leave_spaces_but_constants_consume_one(self):
        host = self.host(r"\saved  X")
        host.context.record_meaning("saved", CharacterCodeMeaning(host.reader.source_span(0, 0), 12))
        self.assertEqual(IntegerScanner(host).integer(), 12)
        # A control word's following source spaces are mouth-discarded. Use a
        # control symbol to observe the actual space token after an internal value.
        host = self.host(r"\! X")
        host.context.record_meaning("!", CharacterCodeMeaning(host.reader.source_span(0, 0), 12))
        self.assertEqual(IntegerScanner(host).integer(), 12)
        self.assertEqual(host.reader.next_token().catcode, CatCode.SPACE)
        host = self.host("12 X")
        self.assertEqual(IntegerScanner(host).integer(), 12)
        self.assertEqual(host.reader.next_token().value, "X")

    def test_chardef_temporarily_relaxes_its_target_then_publishes(self):
        host = self.host(r"\def\saved{9}\chardef\saved=12\saved")
        host.next_item()
        command = host.next_item()
        self.assertEqual(command.metadata["value"], self.oracle["selftarget"])
        self.assertEqual(host.reader.next_token().value, "saved")
        host = self.host(r"\chardef\saved=12 \chardef\saved=\saved")
        host.next_item()
        self.assertEqual(host.next_item().reason, "computed_assignment")
        self.assertEqual(host.context.lookup_meaning("saved").value, 12)

    def test_unsupported_expansion_does_not_publish_partial_assignment(self):
        for text in (r"\chardef\saved=12\unknown", r"\chardef\saved=256 ",
                     r"\chardef\saved=-1 ", r"\chardef\saved=\widowpenalty",
                     r"\chardef\saved=12\ifdim", r"\chardef\saved=`\word"):
            with self.subTest(text=text):
                host = self.host(text)
                self.assertIsInstance(host.next_item(), ReadingBoundary)
                self.assertIsNone(host.context.lookup_meaning("saved"))

    def test_backtick_operand_is_raw_and_relax_is_returned(self):
        host, _ = self.run_source(r"\def\x{BAD}\chardef\saved=`\x ")
        self.assertEqual(host.context.lookup_meaning("saved").value, ord("x"))
        host = self.host(r"\catcode64=11\relax")
        command = host.next_item()
        self.assertEqual(command.span.end, len(r"\catcode64=11"))
        self.assertEqual(host.next_item().action, "reading_noop")

    def test_unknown_effects_invalidate_current_and_suspended_numeric_meanings(self):
        host = self.host(r"\chardef\saved=12 {\chardef\saved=11 \unknown}\catcode64=\saved", preparation=True)
        items = list(host)
        self.assertEqual(items[-1].reason, "uncertain_meaning")
        self.assertIsNotNone(host.context.lookup_meaning("saved").uncertain)

    def test_active_target_and_catcode_internal_value_do_not_execute_assignment(self):
        host, _ = self.run_source(r"\chardef~=11 \catcode64=~ @")
        self.assertEqual(host.context.lookup_meaning("~", TokenKind.ACTIVE_CHARACTER).value, 11)
        host = self.host(r"\catcode64 =11")
        self.assertEqual(IntegerScanner(host).integer(), 12)
        self.assertEqual(host.context.catcodes["@"], CatCode.OTHER)
        self.assertEqual(host.reader.next_token().value, "=")

    def test_token_cursor_uses_captured_categories_and_supports_checkpointed_pushback(self):
        host = self.host("11@")
        tokens = tuple(host.reader)
        argument = ScannedArgument("body", host.reader.source_span(0, 3), tokens, "stored")
        cursor = TokenCursor(argument, host.reader.text, host.context)
        host.reader = cursor
        self.assertEqual(IntegerScanner(host).integer(), 11)
        saved = cursor.checkpoint()
        host.context.catcodes["@"] = CatCode.LETTER
        self.assertIs(cursor.next_token(), tokens[-1])
        cursor.restore(saved)
        self.assertIs(cursor.next_token(), tokens[-1])
        self.assertEqual(tokens[-1].catcode, CatCode.OTHER)

    def test_mouth_pushback_checkpoint_and_raw_handoff_guards(self):
        host = self.host("11@X")
        self.assertEqual(IntegerScanner(host).integer(), 11)
        saved = host.reader.checkpoint()
        with self.assertRaises(ValueError):
            host.reader.consume_raw_to(3)
        host.context.catcodes["@"] = CatCode.LETTER
        token = host.reader.next_token()
        self.assertEqual(token.catcode, CatCode.OTHER)
        host.reader.restore(saved)
        self.assertIs(host.reader.next_token(), token)
        host.reader.unread_token(token)
        with self.assertRaises(ValueError):
            host.reader.unread_token(token)

    def test_returned_endline_token_retains_full_event_extent(self):
        host = self.host("11\nX")
        host.context.endlinechar = host.reader.endline_char = 64
        self.assertEqual(IntegerScanner(host).integer(), 11)
        self.assertEqual(host.reader.position, 2)
        host.context.catcodes["@"] = CatCode.LETTER
        event = host.reader.next_event()
        self.assertEqual(event.span.end, 3)
        self.assertEqual(event.token.catcode, CatCode.OTHER)


if __name__ == "__main__":
    unittest.main()
