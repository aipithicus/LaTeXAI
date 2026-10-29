"""Literal kernel file tests use the declared search environment and shared state."""
from pathlib import Path
import json
import tempfile
import unittest

from src.prepare.pipeline import preprocess_paper


PROJECT = Path(__file__).resolve().parents[1]


class FormatFileTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT / 'temp/tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'source'
        self.root.mkdir()
        self.external = self.base / 'texmf'
        self.external.mkdir()

    def prepare(self, body, roots=()):
        (self.root / 'main.tex').write_text(r'\documentclass{article}' + body, encoding='utf-8')
        return preprocess_paper(str(self.root), tex_resource_roots=roots)

    def test_present_binary_file_is_packaged_and_only_selected_branch_executes(self):
        data = b'\x00\xff\x80PDF'
        (self.root / 'logo.pdf').write_bytes(data)
        (self.root / 'child.tex').write_text('CHILD', encoding='utf-8')
        text, manifest, output, ledger = self.prepare(
            r'\IfFileExists{logo.pdf}{\input{child}}{\input{missing}}TAIL')
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertIn('CHILD', text)
        self.assertNotIn(r'\input{missing}', text)
        self.assertEqual((output / 'logo.pdf').read_bytes(), data)
        decision = next(d for d in manifest.conditional_decisions if d['predicate'] == 'file_exists')
        self.assertTrue(decision['truth'])
        self.assertEqual(decision['resolved'], 'logo.pdf')
        self.assertFalse(any(c['unaccounted'] for c in ledger.source_coverage))

    def test_missing_file_selects_false_branch_without_poisoning_registers(self):
        text, manifest, _, _ = self.prepare(
            r'\IfFileExists{missing.pdf}{\def\chosen{bad}}{\def\chosen{good}}'
            r'\edef\copy{\chosen}\def\expected{good}\ifx\copy\expected PASS\else FAIL\fi')
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertIn('PASS', text)
        self.assertNotIn('FAIL', text)
        self.assertFalse(next(d for d in manifest.conditional_decisions if d['predicate'] == 'file_exists')['truth'])

    def test_external_hit_is_recorded_and_does_not_execute_resource(self):
        package = self.external / 'latex/package'
        package.mkdir(parents=True)
        (package / 'present.sty').write_text(r'\unknown', encoding='utf-8')
        text, manifest, _, _ = self.prepare(r'\IfFileExists{present.sty}{FOUND}{MISSING}', (self.external,))
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertIn('FOUND', text)
        self.assertNotIn('MISSING', text)
        record = next(d for d in manifest.conditional_decisions if d['predicate'] == 'file_exists')
        self.assertEqual(Path(record['resolved']), package / 'present.sty')
        self.assertEqual(record['search']['roots'], [str(self.external.resolve())])

    def test_literal_input_path_is_searched_and_resource_is_retained(self):
        folder = self.root / 'assets'
        folder.mkdir()
        (folder / 'logo.pdf').write_bytes(b'logo')
        text, manifest, output, _ = self.prepare(
            r'\makeatletter\def\input@path{{assets/}}\makeatother'
            r'\IfFileExists{logo.pdf}{FOUND}{MISSING}')
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertIn('FOUND', text)
        self.assertEqual((output / 'assets/logo.pdf').read_bytes(), b'logo')

    def test_unconfigured_external_search_retains_test_and_only_bounds_branch_writes(self):
        body = (r'\IfFileExists{missing.cfg}{\def\maybe{yes}}{\def\maybe{no}}'
                r'\edef\independent{OK}')
        text, manifest, _, _ = self.prepare(body, None)
        self.assertIn(body, text)
        self.assertEqual([r['reason'] for r in manifest.requirements if r['stage'] == 'preparation'],
                         ['file_search_environment'])
        self.assertNotIn('uncertain_integer', [r['reason'] for r in manifest.unresolved])

    def test_computed_filename_is_retained_without_guessing_absence(self):
        source = r'\IfFileExists{\unknown}{YES}{NO}'
        text, manifest, _, _ = self.prepare(source)
        self.assertIn(source, text)
        self.assertFalse(any(d['predicate'] == 'file_exists' for d in manifest.conditional_decisions))
        self.assertTrue(any(r['reason'] == 'computed_argument' for r in manifest.requirements))

    def test_missing_optional_input_executes_else_without_a_source_entry(self):
        text, manifest, _, _ = self.prepare(
            r'\InputIfFileExists{missing.cfg}{\input{bad}}{\def\choice{ok}}'
            r'\def\expected{ok}\ifx\choice\expected PASS\else FAIL\fi')
        self.assertFalse(manifest.unresolved, manifest.unresolved)
        self.assertIn('PASS', text)
        self.assertNotIn('FAIL', text)
        self.assertNotIn(r'\input{bad}', text)

    def test_ambiguous_external_matches_remain_explicit(self):
        for name in ('one', 'two'):
            folder = self.external / name
            folder.mkdir()
            (folder / 'same.sty').write_text('', encoding='utf-8')
        source = r'\IfFileExists{same.sty}{YES}{NO}'
        text, manifest, _, _ = self.prepare(source, (self.external,))
        self.assertIn(source, text)
        self.assertTrue(any(r['reason'] == 'ambiguous_dependency' for r in manifest.requirements))

    def test_missing_file_state_matches_the_pinned_native_kernel(self):
        from src.prepare.session import PreparationSession
        from src.engine.token_text import meaning_text
        source = (r'\documentclass{article}\IfFileExists{missing-pytexml-witness.tex}'
                  r'{\def\Selected{yes}}{\def\Selected{no}}')
        (self.root / 'main.tex').write_text(source, encoding='utf-8')
        session = PreparationSession(self.root, root_tex='main.tex', tex_resource_roots=()).run()
        expected = json.loads((PROJECT / 'tests/fixtures/engine/python-format/expected.json').read_text())['file_test']
        for name in ('@filef@und', '@curr@file', 'reserved@a'):
            self.assertEqual(meaning_text(session.context.lookup_definition(name), session.context), expected[name])

    def test_external_hit_keeps_native_lookup_name_separate_from_absolute_provenance(self):
        from src.prepare.session import PreparationSession
        from src.engine.token_text import meaning_text
        package = self.external / 'latex/etoolbox'
        package.mkdir(parents=True)
        (package / 'etoolbox.sty').write_text('', encoding='utf-8')
        (self.root / 'main.tex').write_text(
            r'\documentclass{article}\IfFileExists{etoolbox.sty}{}{}', encoding='utf-8')
        session = PreparationSession(self.root, root_tex='main.tex', tex_resource_roots=(self.external,)).run()
        self.assertEqual(meaning_text(session.context.lookup_definition('@filef@und'), session.context),
                         'macro:->"etoolbox.sty" ')
        decision = next(d for d in session.manifest.conditional_decisions if d['predicate'] == 'file_exists')
        self.assertEqual(Path(decision['resolved']), package / 'etoolbox.sty')


if __name__ == '__main__':
    unittest.main()
