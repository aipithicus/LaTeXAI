"""Execute hash-checked upstream definitions; never seed optional wrappers."""
import hashlib
import json
import re
from pathlib import Path
import unittest

from src.bindings.resolver import BindingResolver
from src.engine.programs import evaluate, SETUP
from src.reading.context import ReaderContext
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader

PROJECT = Path(__file__).resolve().parents[1]
ORACLE = PROJECT.parents[1] / "temp/texlive-oracle"
FIXTURE = PROJECT / "tests/fixtures/engine/kernel-optional"


@unittest.skipUnless((ORACLE / "texmf-dist/tex/latex/base/latex.ltx").is_file(), "Pinned native source snapshot unavailable")
class KernelSourceTests(unittest.TestCase):
    def run_source(self, text, name):
        context = self.host.context
        reader = TexReader(text, source_id=name, catcodes=context.catcodes, endline_char=context.endlinechar)
        try:
            return evaluate(self.host, tuple(reader), reader.basis.whole, policy=SETUP, budget=100000)
        except Exception as error:
            error.add_note(name)
            raise

    def setUp(self):
        resolver = BindingResolver()
        base = resolver.new_context()
        context = ReaderContext(baseline=base.baseline, primitive_initial_state=True)
        context.catcodes['@'] = 11
        reader = TexReader('', catcodes=context.catcodes, endline_char=context.endlinechar)
        self.host = StructuralDispatcher(reader, context, resolver, preparation=True, source_commands=True)
        self.run_source(r'\dimendef\z@=12 \dimen12=0pt ', 'initial-typed-dimension')
        boundary = json.loads((FIXTURE / 'source-boundary.json').read_text())
        source = (ORACLE / boundary['fragments'][0]['source']).read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), boundary['source_sha256'])
        for fragment in boundary['fragments']:
            part = source[fragment['byte_start']:fragment['byte_end']]
            self.assertEqual(hashlib.sha256(part).hexdigest(), fragment['sha256'])
            self.run_source(part.decode(), fragment['file'])

    def test_real_optional_public_and_hidden_meanings(self):
        self.run_source(r'\newcommand{\gmopt}[1][dflt]{\gdef\Observed{(#1)}}\relax', 'declaration')
        public = self.host.context.lookup_definition('gmopt')
        hidden = self.host.context.lookup_definition('\\gmopt')
        self.assertIsNotNone(public)
        self.assertIsNotNone(hidden)
        self.assertTrue(hidden.long)
        self.run_source(r'\gmopt\relax', 'default-call')
        self.assertEqual(''.join(t.value for t in self.host.context.lookup_definition('Observed').replacement_tokens), '(dflt)')
        self.run_source(r'\gmopt[set]\relax', 'explicit-call')
        self.assertEqual(''.join(t.value for t in self.host.context.lookup_definition('Observed').replacement_tokens), '(set)')

    def test_native_boundary_observations_through_definition_capture(self):
        # Instrument only the witness's write16 observation sites. The kernel
        # definitions and every exercised declaration/call remain unchanged.
        self.check_witness('witness.tex', 'source-boundary.json')

    def check_witness(self, witness, boundary):
        expected = json.loads((FIXTURE / boundary).read_text())['expected_trace']
        labels = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'[:len(expected)]
        names = iter(labels)
        source = (FIXTURE / witness).read_text()
        source = re.sub(r'\\immediate\\write16', lambda _: '\\xdef\\Trace' + next(names), source)
        source = source.removesuffix('\\end\n')
        self.run_source(source, 'instrumented-native-witness')
        actual = [''.join(t.value for t in self.host.context.lookup_definition('Trace' + n).replacement_tokens)
                  for n in labels]
        self.assertEqual(actual, expected)

    def test_etoolbox_patch_source_changes_the_hidden_implementation(self):
        for fragment in json.loads((FIXTURE / 'patch-boundary.json').read_text())['fragments']:
            source = (ORACLE / fragment['source']).read_bytes()
            self.assertEqual(hashlib.sha256(source).hexdigest(), fragment['source_sha256'])
            part = source[fragment['byte_start']:fragment['byte_end']]
            self.assertEqual(hashlib.sha256(part).hexdigest(), fragment['sha256'])
            self.run_source(part.decode(), fragment['source'] + ':' + str(fragment['line_start']))
        self.check_witness('patch-witness.tex', 'patch-boundary.json')


if __name__ == '__main__':
    unittest.main()
