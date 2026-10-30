"""Bounded atlas-derived checks; original documents and staged resolver are not run."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.resolver import BindingResolver
from src.engine.programs import evaluate, SETUP
from src.engine.token_text import meaning_text
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader, TokenKind
from src.validation.behavioral_atlas import load, excerpt
from src.validation.meaning_assay.model import Candidates, descriptor


class AtlasWitnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas = load()
        cls.resolver = BindingResolver()

    def reader(self, text, *, endline=-1):
        context = self.resolver.new_context()
        return TexReader(text, source_id="atlas-derived", catcodes=context.catcodes, endline_char=endline)

    def run_source(self, source):
        context = self.resolver.new_context()
        context.endlinechar = -1
        reader = TexReader(source, source_id="atlas-derived", catcodes=context.catcodes, endline_char=-1)
        host = StructuralDispatcher(reader, context, self.resolver, preparation=True, source_commands=True)
        # These two derived witnesses do not change the reading context. This
        # eager token capture is not appropriate for the full conditional generator.
        evaluate(host, tuple(reader), reader.basis.whole, policy=SETUP, budget=10000)
        return context

    def test_physical_spaces_and_tabs_from_source(self):
        source = excerpt(self.atlas, "trailing_body").decode("ascii")
        reader = self.reader(source)
        tokens = list(reader)
        actual = "".join(token.value for token in tokens)
        self.assertEqual(actual, "Supercalifragilisticexpialidocious must be a single word, despite the trailing spaces. "
                         "Whereas other whitespace characters should not be stripped, preserving the spaces in this sentence.")
        self.assertIn(" \n", source)
        self.assertIn("\t\n", source)
        tab_spaces = [token for token in tokens if token.value == " " and "\t" in source[token.span.start:token.span.end]]
        # The first tab follows an ordinary space, so it is skipped in S state.
        # Only the second tab itself produces a semantic space token.
        self.assertEqual(len(tab_spaces), 1)
        self.assertTrue(all(token.catcode == 10 for token in tab_spaces))

    def test_provisional_reading_replayed_with_refined_context(self):
        source = r"\alpha_beta{ x }"
        reader = self.reader(source)
        checkpoint = reader.checkpoint()
        provisional = list(reader)
        reader.restore(checkpoint)
        reader.catcodes["_"] = 11
        revised = list(reader)
        fresh = self.reader(source)
        fresh.catcodes["_"] = 11
        expected = list(fresh)
        signature = lambda rows: [(t.kind, t.value, t.catcode, t.span.start, t.span.end) for t in rows]
        self.assertEqual(signature(revised), signature(expected))
        self.assertEqual(revised[0].value, "alpha_beta")
        self.assertEqual(provisional[0].value, "alpha")
        self.assertEqual(provisional[1].catcode, 8)
        self.assertEqual(source[provisional[1].span.start:provisional[1].span.end], "_")
        self.assertEqual(provisional[0].span.basis, revised[0].span.basis)

    def test_generated_name_display_is_not_token_serialization(self):
        context = self.run_source(
            r"\expandafter\def\csname T1-cmd\endcsname{X}"
            r"\expandafter\def\expandafter\Original\expandafter{\csname T1-cmd\endcsname}")
        original = context.lookup_definition("Original")
        self.assertEqual([(t.kind, t.value) for t in original.replacement_tokens],
                         [(TokenKind.CONTROL_SEQUENCE, "T1-cmd")])
        display = meaning_text(original, context)
        _, reconstructed = Candidates().parse(display, "latex", "atlas-reconstruction")
        self.assertEqual(reconstructed.replacement_tokens[0].value, "T")
        self.assertNotEqual(descriptor(original)["semantic_key"], descriptor(reconstructed)["semantic_key"])
        self.assertNotEqual(meaning_text(reconstructed, context), display)

    def test_constructed_parameter_from_upstream_fragment(self):
        source = excerpt(self.atlas, "constructed_parameter").decode("ascii")
        # The original meaning operation prints to the document; keep the
        # definition construction unchanged and observe the typed result instead.
        source = source.replace(r"\meaning\ddd", "")
        context = self.run_source(source + r"\edef\Observed{\ddd{OK}}")
        definition = context.lookup_definition("ddd")
        self.assertEqual(definition.parameter_count, 1)
        self.assertEqual(meaning_text(definition, context), "macro:#1->#1")
        self.assertEqual("".join(t.value for t in context.lookup_definition("Observed").replacement_tokens), "OK")


if __name__ == "__main__":
    unittest.main()
