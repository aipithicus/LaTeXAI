"""Raw long-argument capture, independent of command installation or expansion."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.argument_scanner import ArgumentScanner
from src.reading.contracts import ReadingIssue
from src.reading.tex_reader import CatCode, TexReader


class UndelimitedArgumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def scanner(self, source):
        context = BindingResolver(self.catalog).new_context()
        reader = TexReader(source, catcodes=context.catcodes, endline_char=-1)
        return ArgumentScanner(reader, context)

    def test_group_strips_only_outer_delimiters_and_preserves_categories(self):
        scanner = self.scanner(" {a{b} c}TAIL")
        arg = scanner.undelimited("argument")
        self.assertEqual(scanner.reader.source_slice(arg.span), "a{b} c")
        self.assertEqual([t.value for t in arg.tokens], list("a{b} c"))
        self.assertEqual(scanner.reader.next_token().value, "T")

    def test_empty_group_and_skipped_comments(self):
        scanner = self.scanner(" % not an operand\n{}X")
        arg = scanner.undelimited("argument")
        self.assertEqual(arg.tokens, ())
        self.assertEqual(arg.span.start, arg.span.end)
        self.assertEqual(scanner.reader.next_token().value, "X")

    def test_no_resolution_or_execution_for_single_control_sequence(self):
        scanner = self.scanner(r"\makeatletter{tail}")
        arg = scanner.undelimited("argument")
        self.assertEqual(arg.tokens[0].value, "makeatletter")
        self.assertEqual(scanner.context.catcodes["@"], CatCode.OTHER)
        self.assertEqual(scanner.reader.next_token().catcode, CatCode.BEGIN_GROUP)

    def test_missing_extra_closer_and_unbalanced_group_are_explicit(self):
        for source, reason in (("", "argument_required"), ("}", "argument_required"),
                               ("{a", "unclosed_argument")):
            with self.subTest(source=source), self.assertRaises(ReadingIssue) as caught:
                self.scanner(source).undelimited("argument")
            self.assertEqual(caught.exception.reason, reason)

    def test_parameter_and_par_tokens_are_raw_capture_not_replacement_validation(self):
        for source, expected in (("#1", "#"), (r"\par X", "par")):
            scanner = self.scanner(source)
            self.assertEqual(scanner.undelimited("argument").tokens[0].value, expected)


if __name__ == "__main__":
    unittest.main()
