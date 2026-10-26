"""Structural work continues without interpreting retained source owners."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from src.prepare.pipeline import preprocess_paper
from src.bindings.resolver import BindingResolver
from src.reading.contracts import ScannedArgument
from src.reading.deferred_scanner import DeferredScanner
from src.reading.dispatcher import StructuralDispatcher
from src.reading.token_cursor import TokenCursor
from src.reading.tex_reader import TexReader


class DeferredPreparationTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / 'temp/tests'
        scratch.mkdir(parents=True, exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def put(self, name, source):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding='utf-8', newline='')

    def prepare(self, body):
        source = r'\documentclass{article}' + body
        self.put('main.tex', source)
        result = preprocess_paper(str(self.root), root_tex='main.tex')
        self.assertEqual((self.root / 'main.tex').read_text(), source)
        _, manifest, _, ledger = result
        self.assertFalse([u for u in manifest.units if u['location_status'] in {'unmapped', 'partial'}])
        self.assertFalse([s for s in ledger.source_coverage if s['unaccounted']])
        return result

    def test_ordinary_deferred_input_allows_protected_conditional_tokens_and_compacts(self):
        definition = '\\def\\later{\\iftrue % STORED\n A  B\\fi}'
        literal = '\\begin{verbatim}\n\\fi % LITERAL\n  unchanged  \n\\end{verbatim}'
        self.put('one.tex', definition + '\n' + literal + '\nA  % DROP CHILD\n B\\input{two}')
        self.put('two.tex', 'NESTED')
        text, manifest, _, _ = self.prepare('\\begin{unknown}\n Before   % DROP OUTER\n'
            '\\input{one}\nAfter   words\n\\end{unknown}')
        self.assertIn(definition, text)
        self.assertIn(literal, text)
        self.assertIn('Before ', text)
        self.assertIn('After words', text)
        self.assertIn('A B', text)
        self.assertIn('NESTED', text)
        self.assertNotIn('DROP', text)
        self.assertNotIn(r'\input', text)
        self.assertFalse(manifest.dependencies)
        self.assertEqual({d['target'] for d in manifest.candidate_dependencies}, {'one.tex', 'two.tex'})

    def test_unresolved_conditional_keeps_its_stricter_insertion_rule(self):
        self.put('one.tex', r'\verb|\fi|')
        self.put('after.tex', 'AFTER')
        text, manifest, output, _ = self.prepare(r'\ifx\unknown\other\input{one}\else ELSE\fi\input{after}')
        self.assertIn(r'\input{one}', text)
        self.assertNotIn(r'\verb', text)
        self.assertEqual((output / 'one.tex').read_text(), r'\verb|\fi|')
        self.assertIn('AFTER', text)
        self.assertTrue(any(r['reason'] == 'conditional_input' and r['stage'] == 'preparation'
                            for r in manifest.requirements))

    def test_skipping_context_propagates_through_nested_candidate_inputs(self):
        self.put('one.tex', r'ONE \input{two}')
        self.put('two.tex', r'\def\later{\fi}')
        text, manifest, output, _ = self.prepare(r'\ifx\unknown\other\input{one}\fi TAIL')
        self.assertNotIn(r'\input{one}', text)
        self.assertIn(r'\input{two}', text)
        self.assertEqual((output / 'two.tex').read_text(), r'\def\later{\fi}')
        self.assertIn('TAIL', text)

    def test_conditionals_in_ordinary_candidate_are_captured_without_selecting_branches(self):
        self.put('one.tex', r'\iftrue LEFT \input{left}\else RIGHT \input{right}\fi')
        self.put('left.tex', 'LEFT CHILD')
        self.put('right.tex', 'RIGHT CHILD')
        text, manifest, _, _ = self.prepare(r'\begin{unknown}\input{one}\end{unknown}')
        for kept in (r'\iftrue', r'\else', r'\fi', 'LEFT CHILD', 'RIGHT CHILD'):
            self.assertIn(kept, text)
        self.assertNotIn(r'\input', text)
        self.assertFalse(manifest.dependencies)
        units = {u['id']: u for u in manifest.units}
        self.assertTrue(all(units[d['unit_id']]['activity'] == 'unresolved'
                            for d in manifest.candidate_dependencies))

    def test_failed_candidate_does_not_prevent_compaction_or_a_later_input(self):
        child = r'\catcode`\%=\computed'
        self.put('bad.tex', child)
        self.put('good.tex', 'GOOD    CHILD')
        text, _, output, _ = self.prepare('\\begin{unknown} Before   % DROP\n'
            '\\input{bad} Between   words \\input{good} After   words\\end{unknown}')
        self.assertIn(r'\input{bad}', text)
        self.assertEqual((output / 'bad.tex').read_text(), child)
        self.assertIn('Between words', text)
        self.assertIn('GOOD CHILD', text)
        self.assertIn('After words', text)
        self.assertNotIn('DROP', text)

    def test_compaction_preserves_tokens_and_protected_arguments(self):
        source = ('\\begin{unknown}foo% REMOVE\nbar foo % REMOVE\nbar\n\n'
                  '\\mystery{ A  % KEEP\n B } \\bare   next \\?symbol\\end{unknown}')
        text, _, _, _ = self.prepare(source)
        self.assertIn(r'\mystery{ A  % KEEP', text)
        self.assertIn(r'\bare next', text)
        self.assertIn('foobar foo bar', text)
        self.assertIn(r'\par', text)
        self.assertNotIn('REMOVE', text)
        def tokens(value):
            context = BindingResolver().new_context()
            return [(t.kind, t.catcode, t.value) for t in TexReader(value,
                    catcodes=context.catcodes, endline_char=context.endlinechar)]
        self.assertEqual(tokens(r'\documentclass{article}' + source), tokens(text))

    def test_comment_at_input_eof_does_not_introduce_a_paragraph(self):
        self.put('one.tex', 'JOIN% remove')
        self.put('empty.tex', '')
        text, _, _, _ = self.prepare(r'\begin{unknown}\input{one}NEXT\input{empty}\end{unknown}')
        self.assertIn('JOIN%\nNEXT', text)
        self.assertNotIn('%\n\n', text)
        self.assertNotIn(r'\par', text)

    def test_capture_does_not_install_definitions_or_select_a_known_branch(self):
        knowledge = BindingResolver()
        context = knowledge.new_context()
        reader = TexReader(r'\def\captured{X}\iftrue YES\else NO\fi', catcodes=context.catcodes,
                           endline_char=context.endlinechar)
        region, changed = StructuralDispatcher(reader, context, knowledge, preparation=True).observe_input()
        self.assertIsNone(context.lookup_meaning('captured'))
        self.assertEqual(changed, ('captured',))
        self.assertEqual(reader.source_slice(region.span), reader.text)

    def test_frozen_tokens_keep_control_word_separator_information(self):
        for source, expected in ((r'\q next', True), (r'\?next', False)):
            with self.subTest(source=source):
                context = BindingResolver().new_context()
                reader = TexReader(source, catcodes=context.catcodes, endline_char=context.endlinechar)
                argument = ScannedArgument('body', reader.basis.whole, tuple(reader))
                cursor = TokenCursor(argument, source, context)
                region = DeferredScanner(cursor, context).command(cursor.next_token(), 'unknown', '')
                self.assertEqual(region.trailing_control_word, expected)


if __name__ == '__main__':
    unittest.main()
