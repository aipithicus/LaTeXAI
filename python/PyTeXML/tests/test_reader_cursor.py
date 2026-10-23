"""Cursor handoff must retain mouth state and original source independently."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reader_support import new_reader
from src.reading.spans import SourceBasis
from src.reading.tex_reader import CatCode, InvalidCharacterError, ReaderState


class ReaderCursorTests(unittest.TestCase):
    def test_line_replay_retains_basis_and_does_not_read_beyond_window(self):
        source = "HEAD\r\nBODY  \r\nTAIL"
        reader = new_reader(source)
        start, end = source.index("BODY"), source.index("TAIL")
        replay = reader.line_window(reader.source_span(start, end))
        self.assertIs(replay.text, reader.text)
        self.assertIs(replay.basis, reader.basis)
        self.assertEqual("".join(t.value for t in replay), "BODY ")
        self.assertEqual(replay.position, end)
        self.assertIsNone(replay.next_event())
        self.assertEqual(reader.position, 0)
        empty = reader.line_window(reader.source_span(end, end))
        self.assertIsNone(empty.next_event())
        with self.assertRaises(ValueError):
            reader.line_window(reader.source_span(start + 1, end))
        with self.assertRaises(ValueError):
            reader.line_window(reader.source_span(5, end))  # between CR and LF
        with self.assertRaises(ValueError):
            replay.line_window(reader.source_span(0, end))

    def test_raw_handoff_resumes_at_suffix_and_respects_endinput(self):
        reader = new_reader("a%not tokens\r\nZ")
        reader.next_token()
        reader.consume_raw_to(reader.text.index("Z"))
        self.assertEqual(reader.next_token().value, "Z")
        with self.assertRaises(ValueError):
            reader.consume_raw_to(0)
        reader = new_reader("abc\nZ")
        reader.next_token()
        reader.end_input_after_line()
        with self.assertRaises(ValueError):
            reader.consume_raw_to(len(reader.text))
        reader.consume_raw_to(2)
        self.assertEqual(reader.next_token().value, "c")

    def test_pending_converted_character_is_not_reinterpreted_on_handoff(self):
        reader = new_reader(r"\foo^^25tail")
        self.assertEqual(reader.next_token().value, "foo")
        self.assertEqual(reader.position, 4)
        checkpoint = reader.checkpoint()
        reader.catcodes["^"] = CatCode.OTHER
        reader.catcodes["%"] = CatCode.OTHER
        unit = reader.peek_character()
        self.assertEqual((unit.value, unit.span.start, unit.span.end), ("%", 4, 8))
        self.assertTrue(unit.transformed)
        self.assertFalse(unit.synthetic_endline)
        self.assertEqual(reader.position, 4)
        self.assertEqual(reader.next_token().value, "%")
        table = reader.catcodes
        reader.restore(checkpoint)
        self.assertIs(reader.catcodes, table)
        self.assertEqual(reader.state, ReaderState.SKIP_BLANKS)
        self.assertEqual(reader.next_event().kind.value, "comment")
        self.assertEqual(reader.position, len(reader.text))

    def test_checkpoint_replays_physical_window_and_captured_endline(self):
        reader = new_reader("ab  \r\ncd", source_id="paper.tex", occurrence_id=7)
        beginning = reader.checkpoint()
        self.assertIsNone(reader.current_line)
        self.assertIsNone(reader.peek_character())
        reader.next_token()
        line = reader.current_line
        self.assertEqual((line.span.start, line.content_end, line.mouth_end, line.span.end), (0, 4, 2, 6))
        reader.endline_char = -1  # Applies to the next physical line only.
        saved = reader.checkpoint()
        events = list(iter(reader.next_event, None))
        reader.restore(saved)
        self.assertEqual(reader.endline_char, -1)
        self.assertEqual(reader.current_line, line)
        self.assertEqual(list(iter(reader.next_event, None)), events)
        reader.restore(beginning)
        self.assertIsNone(reader.current_line)
        self.assertEqual(reader.position, 0)
        self.assertEqual(reader.endline_char, 13)
        self.assertEqual(reader.next_token().value, "a")

    def test_peek_never_crosses_physical_lines(self):
        reader = new_reader("x  \r\ny")
        reader.next_token()
        unit = reader.peek_character()
        self.assertTrue(unit.synthetic_endline)
        self.assertEqual(reader.source_slice(unit.span), "  \r\n")
        self.assertEqual(reader.position, 1)
        reader.next_event()
        self.assertIsNone(reader.peek_character())
        self.assertIsNone(reader.current_line)
        self.assertEqual(reader.next_token().value, "y")

    def test_disabled_endline_leaves_raw_tail_available(self):
        reader = new_reader("x  \ny", endline_char=-1)
        reader.next_token()
        self.assertIsNone(reader.peek_character())
        self.assertEqual(reader.current_line.span.end, 4)
        saved = reader.checkpoint()
        tail = reader.next_event()
        self.assertEqual(reader.source_slice(tail.span), "  \n")
        reader.restore(saved)
        self.assertEqual(reader.next_event(), tail)

    def test_restore_before_and_after_sticky_invalid_character(self):
        reader = new_reader("a\x7fb")
        reader.next_token()
        before = reader.checkpoint()
        with self.assertRaises(InvalidCharacterError):
            reader.next_event()
        failed = reader.checkpoint()
        reader.restore(before)
        reader.catcodes["\x7f"] = CatCode.OTHER
        self.assertEqual(reader.next_token().value, "\x7f")
        reader.restore(failed)
        with self.assertRaises(InvalidCharacterError):
            reader.peek_character()

    def test_foreign_checkpoint_and_source_ranges_rejected(self):
        reader = new_reader("abc", source_id="p", occurrence_id=2)
        with self.assertRaises(ValueError):
            reader.restore(new_reader("abc").checkpoint())
        for basis in (SourceBasis("q", 2, 3), SourceBasis("p", 1, 3), SourceBasis("p", 2, 3)):
            with self.subTest(basis=basis), self.assertRaises(ValueError):
                reader.source_slice(basis.span(0, 1))
        for start, end in ((-1, 1), (2, 1), (0, 4)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                reader.source_span(start, end)
        self.assertEqual(reader.source_slice(reader.source_span(1, 3)), "bc")

    def test_eof_checkpoint_does_not_create_another_empty_line(self):
        for source in ("", "x", "x\n"):
            with self.subTest(source=source):
                reader = new_reader(source)
                list(reader)
                saved = reader.checkpoint()
                self.assertIsNone(reader.next_event())
                reader.restore(saved)
                self.assertIsNone(reader.next_event())
                self.assertEqual(reader.position, len(source))


if __name__ == "__main__":
    unittest.main()
