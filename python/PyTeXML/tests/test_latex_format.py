"""Python format routines construct native macro state; TeX is an oracle only."""
from pathlib import Path
import json
import unittest

from src.bindings.resolver import BindingResolver
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader
from src.reading.contracts import CommandDefinition, ReadingBoundary, UncertainMeaning
from src.engine.token_text import meaning_text
from src.engine.latex.registry import PROFILES


class LatexFormatTests(unittest.TestCase):
    def read(self, source, preparation=False):
        self.resolver = BindingResolver()
        self.context = self.resolver.new_context()
        reader = TexReader(source, catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.host = StructuralDispatcher(reader, self.context, self.resolver,
                                        preparation=preparation, source_commands=preparation)
        self.items = list(self.host)
        self.assertFalse(any(isinstance(i, ReadingBoundary) for i in self.items), self.items[-1:])

    def test_native_oracle_public_and_hidden_meanings(self):
        self.read(r'\newcommand\zero{body}\newcommand\one[1]{#1}'
                  r'\newcommand*\short[1]{#1}\newcommand\opt[1][dflt]{(#1)}')
        expected = json.loads((Path(__file__).parent / 'fixtures/engine/python-format/expected.json').read_text())['meanings']
        self.assertEqual({n: meaning_text(self.context.lookup_definition(n), self.context) for n in expected}, expected)
        self.assertTrue(all(s.kind == 'constructed_definition' for s in self.host.program_sources))
        self.assertTrue(all(not isinstance(self.context.lookup_definition(n), CommandDefinition) for n in expected))

    def test_provide_keeps_existing_and_installs_known_absent_only(self):
        self.read(r'\def\existing{old}\providecommand\existing{new}'
                  r'\let\absent\undefined\providecommand\absent[1]{#1}'
                  r'\providecommand\unestablished{maybe}')
        self.assertEqual(meaning_text(self.context.lookup_definition('existing'), self.context), 'macro:->old')
        self.assertEqual(meaning_text(self.context.lookup_definition('absent'), self.context), r'\long macro:#1->#1')
        self.assertIsInstance(self.context.lookup_meaning('unestablished'), UncertainMeaning)

    def test_provide_rejects_a_forbidden_absent_target(self):
        self.read(r'\let\endthing\undefined')
        reader = TexReader(r'\providecommand\endthing{body}',
                           catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        host = StructuralDispatcher(reader, self.context, self.resolver)
        self.assertEqual(host.next_item().reason, 'invalid_definition_target')
        self.assertIsNone(self.context.lookup_definition('endthing'))

    def test_public_alias_observes_replaced_hidden_implementation(self):
        self.read(r'\newcommand*\pick[1][default]{\gdef\chosen{old}}\let\alias\pick'
                  r'\expandafter\def\csname\string\pick\endcsname[#1]{\gdef\chosen{#1}}'
                  r'\alias[new]\def\expected{new}\ifx\chosen\expected YES\else NO\fi', preparation=True)
        self.assertEqual([d['truth'] for d in self.host.decisions], [True])

    def test_registry_is_immutable_and_named_routines_are_not_yaml_entries(self):
        self.assertIn('newcommand', PROFILES)
        with self.assertRaises(TypeError):
            PROFILES['newcommand'] = None
        self.assertNotIn(r'\newcommand', BindingResolver().catalog.commands)


if __name__ == '__main__':
    unittest.main()
