"""Expansion witnesses exercise the live reader/state rather than a second engine."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.engine.expansion import ExpansionCursor
from src.reading.contracts import ReadingBoundary, ReadingIssue, StoredDefinition
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader, TokenKind


class MacroExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def host(self, source):
        knowledge = BindingResolver(self.catalog)
        context = knowledge.new_context()
        reader = TexReader(source, source_id="expansion.tex", catcodes=context.catcodes, endline_char=context.endlinechar)
        return StructuralDispatcher(reader, context, knowledge)

    def declarations(self, host, count):
        result = []
        while len(result) < count:
            item = host.next_item()
            self.assertNotIsInstance(item, ReadingBoundary)
            self.assertIsNotNone(item)
            if isinstance(item, StoredDefinition):
                result.append(item)
        return result

    def cursor(self, host, **kwargs):
        return ExpansionCursor(host.reader, host.context, host.knowledge, host.operations, **kwargs)

    def expanded(self, cursor):
        result = []
        while (token := cursor.next_expanded()) is not None:
            result.append(token)
        return result

    def test_replacement_resumes_source_and_keeps_original_token_objects(self):
        host = self.host(r"\def\a{AB}\a C%")
        definition, = self.declarations(host, 1)
        tokens = self.expanded(self.cursor(host))
        self.assertEqual("".join(t.value for t in tokens), "ABC")
        self.assertIs(tokens[0], definition.body_tokens[0])
        self.assertIs(tokens[1], definition.body_tokens[1])
        self.assertGreater(tokens[-1].span.start, definition.span.end)

    def test_undelimited_arguments_cross_replacement_frames_without_expansion(self):
        host = self.host(r"\def\pair#1#2{#2#1}\def\start{\pair{A}}\start{B}TAIL%")
        self.declarations(host, 2)
        cursor = self.cursor(host)
        tokens = self.expanded(cursor)
        self.assertEqual("".join(t.value for t in tokens), "BATAIL")
        self.assertEqual([call.invocation.value for call in cursor.calls], ["start", "pair"])
        self.assertEqual([len(a) for a in cursor.calls[-1].arguments], [1, 1])

    def test_empty_group_and_nested_braces_are_arguments_not_execution_scopes(self):
        host = self.host(r"\def\pair#1#2{#1/#2}\pair{}{{B}}%")
        self.declarations(host, 1)
        tokens = self.expanded(self.cursor(host))
        self.assertEqual("".join(t.value for t in tokens), "/{B}")
        self.assertEqual(host.context.scope_depth, 0)

    def test_alias_freezes_definition_but_body_lookup_uses_current_meanings(self):
        host = self.host(r"\def\a{A}\let\saved\a\def\a{B}\def\late{\a}\saved\late%")
        self.declarations(host, 3)
        self.assertEqual("".join(t.value for t in self.expanded(self.cursor(host))), "AB")

    def test_categories_are_frozen_and_source_remains_lazy(self):
        host = self.host(r"\def\a{@}\a @%")
        definition, = self.declarations(host, 1)
        host.context.catcodes["@"] = CatCode.LETTER
        tokens = self.expanded(self.cursor(host))
        self.assertEqual([t.catcode for t in tokens], [CatCode.OTHER, CatCode.LETTER])
        self.assertIs(tokens[0], definition.body_tokens[0])

    def test_short_argument_rejects_paragraph_and_unstarred_command_is_long(self):
        short = self.host(r"\def\a#1{#1}\a{\par}%")
        self.declarations(short, 1)
        with self.assertRaises(ReadingIssue) as caught:
            self.expanded(self.cursor(short))
        self.assertEqual(caught.exception.reason, "runaway_argument")
        long = self.host(r"\newcommand\a[1]{A}\a{\par}%")
        self.declarations(long, 1)
        self.assertEqual("".join(t.value for t in self.expanded(self.cursor(long))), "A")

    def test_unsupported_parameter_pattern_is_a_requirement(self):
        host = self.host(r"\def\a#1,{#1}\a A,%")
        self.declarations(host, 1)
        with self.assertRaises(ReadingIssue) as caught:
            self.expanded(self.cursor(host))
        self.assertEqual(caught.exception.reason, "macro_parameters")

    def test_noexpand_reads_one_raw_token_and_suppression_does_not_persist(self):
        host = self.host(r"\def\a{A}\noexpand\a\a%")
        self.declarations(host, 1)
        tokens = self.expanded(self.cursor(host))
        self.assertEqual([(t.kind, t.value) for t in tokens],
                         [(TokenKind.CONTROL_SEQUENCE, "a"), (TokenKind.CHARACTER, "A")])

    def test_noexpand_alias_and_shadowing_use_current_meaning(self):
        host = self.host(r"\let\save\noexpand\def\noexpand{X}\def\a{A}\save\a\noexpand%")
        self.declarations(host, 2)
        self.assertEqual([t.value for t in self.expanded(self.cursor(host))], ["a", "X"])

    def test_recursion_is_a_bounded_requirement(self):
        host = self.host(r"\def\a{\a}\a%")
        self.declarations(host, 1)
        with self.assertRaises(ReadingIssue) as caught:
            self.expanded(self.cursor(host, budget=30))
        self.assertEqual(caught.exception.reason, "expansion_budget")

    def test_argument_duplication_is_budgeted_before_replacement_allocation(self):
        host = self.host(r"\def\a#1{#1#1#1#1#1#1#1#1}\a{ABCDEFGHIJ}%")
        self.declarations(host, 1)
        cursor = self.cursor(host, budget=40)
        with self.assertRaises(ReadingIssue) as caught:
            cursor.next_expanded()
        self.assertEqual(caught.exception.reason, "expansion_budget")
        self.assertEqual(cursor.remaining, 0)
        self.assertEqual(cursor.calls, [])
        self.assertFalse(cursor.pending)

    def test_checkpoint_restores_frames_and_source_without_refunding_budget(self):
        host = self.host(r"\def\a{AB}\a C%")
        self.declarations(host, 1)
        cursor = self.cursor(host)
        self.assertEqual(cursor.next_expanded().value, "A")
        saved, remaining = cursor.checkpoint(), cursor.remaining
        self.assertEqual([t.value for t in self.expanded(cursor)], ["B", "C"])
        cursor.restore(saved)
        self.assertLess(cursor.remaining, remaining)
        self.assertEqual([t.value for t in self.expanded(cursor)], ["B", "C"])

    def test_edef_keeps_authored_capture_and_expanded_replacement_separate(self):
        host = self.host(r"\def\part{xspace}\edef\load{\noexpand\RequirePackage{\part}}")
        part, load = self.declarations(host, 2)
        self.assertEqual([t.value for t in load.body_tokens], ["noexpand", "RequirePackage", "{", "part", "}"])
        self.assertEqual([t.value for t in load.expanded_tokens], ["RequirePackage", "{", *"xspace", "}"])
        self.assertIs(load.expanded_tokens[2], part.body_tokens[0])
        self.assertIs(host.context.lookup_definition("load"), load)

    def test_edef_uses_old_target_during_expansion_then_installs_new_meaning(self):
        host = self.host(r"\def\a{OLD}\edef\a{\a NEW}\a%")
        self.declarations(host, 2)
        self.assertEqual("".join(t.value for t in self.expanded(self.cursor(host))), "OLDNEW")

    def test_edef_parameters_are_validated_after_expansion(self):
        host = self.host(r"\def\hash{##}\edef\copy#1{\hash1}\copy{VALUE}%")
        self.declarations(host, 2)
        self.assertEqual("".join(t.value for t in self.expanded(self.cursor(host))), "VALUE")

    def test_failed_edef_preserves_old_meaning(self):
        host = self.host(r"\def\a{OLD}\edef\a{\unknown}")
        original, = self.declarations(host, 1)
        boundary = host.next_item()
        self.assertIsInstance(boundary, ReadingBoundary)
        self.assertEqual(boundary.reason, "expansion_required")
        self.assertIs(host.context.lookup_definition("a"), original)

    def test_parameter_number_is_expanded_in_edef(self):
        host = self.host(r"\def\numbertoken{1}\edef\copy#1{#\numbertoken}\copy{VALUE}%")
        self.declarations(host, 2)
        self.assertEqual("".join(t.value for t in self.expanded(self.cursor(host))), "VALUE")

    def test_edef_copies_unexpandable_assignments_without_executing_them(self):
        host = self.host(r"\edef\a{\catcode64=11}\a%")
        definition, = self.declarations(host, 1)
        self.assertEqual(definition.expanded_tokens[0].value, "catcode")
        self.assertEqual(host.context.catcodes["@"], CatCode.OTHER)

    def test_replacements_match_recorded_independent_tex_observations(self):
        expected = json.loads((Path(__file__).parent / "fixtures/engine/macro-expansion.expected.json").read_text())
        host = self.host(
            r"\def\part{xspace}\edef\load{\noexpand\RequirePackage{\part}}"
            r"\def\pair#1#2{#2#1}\def\start{\pair{A}}\edef\joined{\start{B}TAIL}"
            r"\def\original{OLD}\let\saved\original\def\original{NEW}\edef\aliases{\saved/\original}"
            r"\def\hash{##}\def\numbertoken{1}\edef\copy#1{\hash\numbertoken}\edef\result{\copy{VALUE}}"
            r"\def\old{A}\edef\held{\noexpand\old}\def\old{B}\edef\later{\held}"
            r"\edef\inert{\catcode64=11}")
        definitions = {d.target.value: d for d in self.declarations(host, 17)}
        for name in ("load", "joined", "aliases", "copy", "result", "held", "later"):
            with self.subTest(name=name):
                definition = definitions[name]
                # A test-only rendering of this fixture's simple token vocabulary,
                # not an implementation of TeX's meaning printer.
                replacement = "".join(
                    "\\" + t.value + " " if t.kind == TokenKind.CONTROL_SEQUENCE else t.value
                    for t in definition.replacement_tokens).rstrip()
                header = "".join(t.value for t in definition.parameter_tokens)
                self.assertEqual(f"macro:{header}->{replacement}", expected[name])
        self.assertEqual(str(int(host.context.catcodes["@"])), expected["atcode"])


if __name__ == "__main__":
    unittest.main()
