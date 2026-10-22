"""Character-reading conformance, independent of expansion and normalization.

Expected transitions follow tex.web 343--359. Fixtures specify the lexical
result directly rather than using the existing normalizer as an oracle.
"""

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.reading.tex_reader import (
    CatCode, CatcodeTable, EventKind, InvalidCharacterError, ReaderState,
    TokenKind,
)


from reader_support import new_reader, new_catcodes


def signature(token):
    if token is None:
        return None
    if token.kind == TokenKind.CONTROL_SEQUENCE:
        return ("cs", token.value)
    if token.kind == TokenKind.ACTIVE_CHARACTER:
        return ("active", token.value)
    return (token.value, int(token.catcode))


def values(text, **kwargs):
    return [token.value for token in new_reader(text, **kwargs)]


class ReaderTransitionTests(unittest.TestCase):
    def test_all_48_state_category_combinations(self):
        N, M, S = ReaderState.NEW_LINE, ReaderState.MID_LINE, ReaderState.SKIP_BLANKS
        # Each row gives (token, following state) for N, M, S. End-of-line
        # returns before the next physical line is loaded and state resets.
        ordinary = lambda cat: [(('!', cat), M)] * 3
        expected = {
            0: [(('cs', 'q'), S)] * 3,
            1: ordinary(1), 2: ordinary(2), 3: ordinary(3), 4: ordinary(4),
            5: [(('cs', 'par'), N), ((' ', 10), M), (None, S)],
            6: ordinary(6), 7: ordinary(7), 8: ordinary(8),
            9: [(None, N), (None, M), (None, S)],
            10: [(None, N), ((' ', 10), S), (None, S)],
            11: ordinary(11), 12: ordinary(12),
            13: [(('active', '!'), M)] * 3,
            14: [(None, N), (None, M), (None, S)],
            15: [None, None, None],
        }
        for state_index, (prefix, initial) in enumerate([('', N), ('A', M), ('A ', S)]):
            for category in CatCode:
                with self.subTest(state=initial, category=category):
                    codes = new_catcodes()
                    codes['!'] = category
                    suffix = '!q' if category == CatCode.ESCAPE else '!'
                    reader = new_reader(prefix + suffix, catcodes=codes, endline_char=-1)
                    for _ in prefix:
                        reader.next_event()
                    if category == CatCode.INVALID:
                        with self.assertRaises(InvalidCharacterError):
                            reader.next_event()
                        continue
                    event = reader.next_event()
                    self.assertEqual(event.state_before, initial)
                    token, after = expected[category][state_index]
                    self.assertEqual(signature(event.token), token)
                    self.assertEqual(event.state_after, after)

    def test_spaces_comments_and_indentation(self):
        fixtures = [
            ('foo(x)% ignored\n  bar', list('foo(x)bar ')),
            ('foo(x) % ignored\n  bar', list('foo(x) bar ')),
            ('foo(x)   % ignored\n\tbar', list('foo(x) bar ')),
            ('  a \t  b  ', list('a b ')),
            ('a\n% whole line\n  b', list('a b ')),
            ('a% first\n% second\n b', list('ab ')),
            ('a% first\n\nb', ['a', 'par', 'b', ' ']),
            ('a\n\n\nb', ['a', ' ', 'par', 'par', 'b', ' ']),
        ]
        for source, expected in fixtures:
            with self.subTest(source=source):
                self.assertEqual(values(source), expected)

    def test_control_words_do_not_expand_and_spaces_are_read_later(self):
        reader = new_reader('\\foo % ignored\nbar')
        first = reader.next_token()
        self.assertEqual(signature(first), ('cs', 'foo'))
        self.assertEqual(reader.state, ReaderState.SKIP_BLANKS)
        event = reader.next_event()
        self.assertEqual(event.kind, EventKind.IGNORED_SPACE)
        self.assertEqual([t.value for t in reader], list('bar '))

    def test_control_symbols_control_space_and_active_identity(self):
        reader = new_reader('\\% \\~ ~ \\  x')
        self.assertEqual([signature(t) for t in reader], [
            ('cs', '%'), (' ', 10), ('cs', '~'), (' ', 10),
            ('active', '~'), (' ', 10), ('cs', ' '), ('x', 11), (' ', 10),
        ])

    def test_double_backslash_does_not_escape_a_following_comment(self):
        self.assertEqual([signature(t) for t in new_reader('a\\\\% hidden\nb')], [
            ('a', 11), ('cs', '\\'), ('b', 11), (' ', 10),
        ])

    def test_ignored_character_preserves_skip_state(self):
        self.assertEqual(values('\\foo\x00  x'), ['foo', 'x', ' '])

    def test_invalid_character_is_a_sticky_explicit_failure(self):
        reader = new_reader('a\x7fb', source_id='source.tex', occurrence_id=9)
        reader.next_token()
        for _ in range(2):
            with self.assertRaises(InvalidCharacterError) as caught:
                reader.next_token()
            self.assertEqual(caught.exception.span.basis.source_id, 'source.tex')
            self.assertEqual(caught.exception.span.basis.occurrence_id, 9)
            self.assertEqual((caught.exception.span.start, caught.exception.span.end), (1, 2))

    def test_invalid_characters_in_comments_are_never_read(self):
        self.assertEqual(values('% \x7f ^^7f\nx'), ['x', ' '])


class PhysicalInputTests(unittest.TestCase):
    def test_empty_and_final_lines_follow_file_input_semantics(self):
        fixtures = [('', ['par']), ('\n', ['par']), ('\n\n', ['par', 'par']),
                    ('a', ['a', ' ']), ('a\n', ['a', ' ']), ('   ', ['par'])]
        for source, expected in fixtures:
            with self.subTest(source=source):
                self.assertEqual(values(source), expected)
        self.assertEqual(values('', endline_char=-1), [])

    def test_only_cr_lf_crlf_are_physical_line_endings(self):
        source = 'a\r\nb\rc\n'
        tokens = list(new_reader(source, source_id='mixed', occurrence_id=2))
        self.assertEqual([t.value for t in tokens], list('a b c '))
        self.assertEqual([(t.span.start, t.span.end) for t in tokens],
                         [(0, 1), (1, 3), (3, 4), (4, 5), (5, 6), (6, 7)])
        self.assertTrue(all(t.span.basis.source_id == 'mixed' and t.span.basis.occurrence_id == 2
                            for t in tokens))
        for character in ('\x0b', '\x85', '\u2028', '\u2029', '\u200b', '\ufffd'):
            with self.subTest(character=character):
                self.assertEqual(values('a' + character + 'b'), ['a', character, 'b', ' '])

    def test_disabled_endline_keeps_physical_line_boundaries(self):
        for endline_char in (-1, 256):
            self.assertEqual(values('a\n  b\n', endline_char=endline_char), list('ab'))
            self.assertEqual(values('\\foo\nbar', endline_char=endline_char), ['foo', 'b', 'a', 'r'])

    def test_endline_character_is_captured_per_line(self):
        reader = new_reader('a\nb\n')
        self.assertEqual(reader.next_token().value, 'a')
        reader.endline_char = -1
        self.assertEqual([t.value for t in reader], [' ', 'b'])

    def test_endline_catcode_is_looked_up_at_consumption(self):
        reader = new_reader('a\n')
        reader.next_token()
        reader.catcodes['\r'] = CatCode.OTHER
        self.assertEqual(signature(reader.next_token()), ('\r', 12))
        self.assertIsNone(reader.next_token())

    def test_endline_character_can_extend_control_word_or_start_comment(self):
        token = new_reader('\\foo', endline_char=ord('x')).next_token()
        self.assertEqual(signature(token), ('cs', 'foox'))
        self.assertTrue(token.transformed)
        self.assertEqual(values('a', endline_char=ord('%')), ['a'])

    def test_trailing_ascii_spaces_removed_before_catcode_lookup(self):
        codes = new_catcodes()
        codes[' '] = CatCode.OTHER
        codes['\t'] = CatCode.OTHER
        self.assertEqual(values('a  ', catcodes=codes, endline_char=-1), ['a'])
        self.assertEqual(values('a \t', catcodes=codes, endline_char=-1), ['a', ' ', '\t'])

    def test_endline_and_null_control_symbols(self):
        self.assertEqual(signature(new_reader('\\').next_token()), ('cs', '\r'))
        self.assertEqual(signature(new_reader('\\', endline_char=-1).next_token()), ('cs', ''))

    def test_advancing_to_eof_resets_line_state_without_an_extra_token(self):
        reader = new_reader('a')
        self.assertEqual([t.value for t in reader], ['a', ' '])
        self.assertEqual(reader.state, ReaderState.NEW_LINE)
        self.assertIsNone(reader.next_token())

    def test_paragraph_from_empty_line_has_ordinary_control_sequence_identity(self):
        self.assertEqual(signature(new_reader('\n').next_token()),
                         signature(new_reader('\\par').next_token()))

    def test_control_space_identity_keeps_the_actual_escape_argument(self):
        self.assertEqual([signature(t) for t in new_reader('\\\t  x')],
                         [('cs', '\t'), ('x', 11), (' ', 10)])

    def test_custom_endline_category_discards_remaining_physical_line(self):
        codes = new_catcodes()
        codes['!'] = CatCode.END_OF_LINE
        reader = new_reader('a!discard\nb', catcodes=codes)
        reader.next_token()
        event = reader.next_event()
        self.assertEqual(signature(event.token), (' ', 10))
        self.assertEqual((event.token.span.start, event.token.span.end), (1, 2))
        self.assertEqual((event.span.start, event.span.end), (1, 10))
        self.assertEqual([t.value for t in reader], ['b', ' '])


class CharacterPreprocessingTests(unittest.TestCase):
    def test_classic_expanded_characters(self):
        fixtures = [(r'^^41', ['A', ' ']), (r'^^A', ['\x01', ' ']),
                    (r'^^a', ['!', ' ']), (r'^^7', ['w', ' ']),
                    (r'^^AF', ['\x01', 'F', ' ']),
                    (r'^^5e^41', ['A', ' ']),
                    (r'^^20x', ['x', ' ']),
                    ('^^25ignored\nx', ['x', ' ']),
                    ('^^0dignored', ['par'])]
        for source, expected in fixtures:
            with self.subTest(source=source):
                self.assertEqual(values(source), expected)

    def test_expanded_escape_and_control_word_characters(self):
        for source in (r'^^5cfoo', r'\f^^6fo'):
            with self.subTest(source=source):
                token = new_reader(source).next_token()
                self.assertEqual(signature(token), ('cs', 'foo'))
                self.assertEqual((token.span.start, token.span.end), (0, len(source)))
                self.assertTrue(token.transformed)

    def test_superscript_character_is_selected_by_catcode(self):
        codes = new_catcodes()
        codes['!'] = CatCode.SUPERSCRIPT
        codes['^'] = CatCode.OTHER
        self.assertEqual(values('!!41 ^^41', catcodes=codes), ['A', ' ', '^', '^', '4', '1', ' '])

    def test_non_ascii_following_character_is_not_toggled(self):
        self.assertEqual(values('^^é'), ['^', '^', 'é', ' '])

    def test_control_word_lookahead_conversion_survives_a_catcode_change(self):
        reader = new_reader(r'\foo^^25tail')
        self.assertEqual(signature(reader.next_token()), ('cs', 'foo'))
        reader.catcodes['^'] = CatCode.OTHER
        reader.catcodes['%'] = CatCode.OTHER
        token = reader.next_token()
        self.assertEqual(signature(token), ('%', 12))
        self.assertEqual((token.span.start, token.span.end), (4, 8))
        self.assertTrue(token.transformed)


class ContextAndSourceTests(unittest.TestCase):
    def test_consumption_uses_current_categories_without_reclassifying_tokens(self):
        reader = new_reader(r'\foo@bar')
        first = reader.next_token()
        reader.catcodes['@'] = CatCode.LETTER
        self.assertEqual(signature(first), ('cs', 'foo'))
        self.assertEqual(signature(reader.next_token()), ('@', 11))
        reader.catcodes['b'] = CatCode.OTHER
        stored = reader.next_token()
        reader.catcodes['b'] = CatCode.LETTER
        self.assertEqual(signature(stored), ('b', 12))
        with self.assertRaises(FrozenInstanceError):
            stored.catcode = CatCode.LETTER

    def test_control_word_character_set_is_not_hardcoded(self):
        codes = new_catcodes()
        codes['@'] = CatCode.LETTER
        codes['é'] = CatCode.LETTER
        self.assertEqual(signature(new_reader('\\a@é', catcodes=codes).next_token()), ('cs', 'a@é'))
        self.assertEqual(signature(new_reader('\\a@é').next_token()), ('cs', 'a'))

    def test_escape_character_is_not_hardcoded(self):
        codes = new_catcodes()
        codes['!'] = CatCode.ESCAPE
        codes['\\'] = CatCode.OTHER
        self.assertEqual([signature(t) for t in new_reader('!foo\\', catcodes=codes)],
                         [('cs', 'foo'), ('\\', 12), (' ', 10)])

    def test_default_profiles_and_copies_do_not_leak(self):
        first, second = new_reader('x'), new_reader('x')
        first.catcodes['x'] = CatCode.OTHER
        self.assertEqual(signature(second.next_token()), ('x', 11))
        copied = first.catcodes.copy()
        copied['x'] = CatCode.ACTIVE
        self.assertEqual(first.catcodes['x'], CatCode.OTHER)
        with self.assertRaises(ValueError):
            copied['xx'] = CatCode.LETTER
        with self.assertRaises(ValueError):
            copied['x'] = 16

    def test_comment_event_preserves_original_extent_and_occurrence(self):
        source = 'é % note\r\nx'
        reader = new_reader(source, source_id='part.tex', occurrence_id=4)
        events = []
        while (event := reader.next_event()) is not None:
            events.append(event)
        comment = next(e for e in events if e.kind == EventKind.COMMENT)
        self.assertEqual(source[comment.span.start:comment.span.end], '% note\r\n')
        self.assertEqual(comment.span.basis.occurrence_id, 4)
        self.assertEqual((events[0].span.start, events[0].span.end), (0, 1))
        self.assertEqual(reader.text, source)

    def test_disabled_endline_event_accounts_for_removed_tail(self):
        reader = new_reader('a  \r\nb', endline_char=-1)
        reader.next_event()
        event = reader.next_event()
        self.assertEqual(event.kind, EventKind.DISABLED_ENDLINE)
        self.assertEqual(reader.text[event.span.start:event.span.end], '  \r\n')

    def test_normalized_space_has_its_original_source_span(self):
        reader = new_reader('a\tb')
        reader.next_token()
        token = reader.next_token()
        self.assertEqual(signature(token), (' ', 10))
        self.assertEqual(reader.text[token.span.start:token.span.end], '\t')

    def test_commands_are_not_executed_and_names_have_no_builtin_meaning(self):
        reader = new_reader('\\makeatletter\\foo@bar')
        self.assertEqual([signature(t) for t in reader], [
            ('cs', 'makeatletter'), ('cs', 'foo'), ('@', 12),
            ('b', 11), ('a', 11), ('r', 11), (' ', 10),
        ])


if __name__ == '__main__':
    unittest.main()
