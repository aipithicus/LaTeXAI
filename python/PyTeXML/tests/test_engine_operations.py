"""Catalog assembly and direct operation calls over the reader's live state.

Detailed operand/scope witnesses remain in the existing definition, meaning,
boolean, environment and structural-dispatch suites, which use this catalog too.
"""
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.engine.catalog import CORE_OPERATIONS
from src.engine.operations import OperationFamily, build_catalog
from src.reading.context import ExecutionMode
from src.reading.contracts import ReadingIssue, StoredDefinition, UncertainMeaning
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader


class EngineOperationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bindings = BindingCatalog()

    def host(self, text):
        resolver = BindingResolver(self.bindings)
        context = resolver.new_context()
        reader = TexReader(text, source_id="operations.tex", occurrence_id=1,
                           catcodes=context.catcodes, endline_char=context.endlinechar)
        return StructuralDispatcher(reader, context, resolver)

    def execute(self, host, identity):
        opening = host.reader.next_event()
        from src.engine.primitive import PrimitiveMeaning
        profile = (PrimitiveMeaning(identity, "simple")
                   if opening.token.catcode in {CatCode.BEGIN_GROUP, CatCode.END_GROUP}
                   else host.context.resolve_meaning(host.knowledge, opening.token.value))
        from src.reading.contracts import BoundMeaning
        if isinstance(profile, BoundMeaning):
            profile = profile.profile
        return CORE_OPERATIONS[identity].execute(host, opening, profile)

    def test_catalog_rejects_duplicates_across_families_and_cannot_be_mutated(self):
        operation = CORE_OPERATIONS["meaning.assign"]
        with self.assertRaisesRegex(ValueError, "Duplicate operation identity: meaning.assign"):
            build_catalog(OperationFamily((operation,)), OperationFamily((operation,)))
        with self.assertRaises(TypeError):
            CORE_OPERATIONS["another"] = operation
        with self.assertRaises(FrozenInstanceError):
            operation.identity = "another"

    def test_direct_definition_and_let_share_state_without_dispatching_body(self):
        host = self.host(r"\def\donor#1{\makeatletter#1}\let\saved\donor\def\donor{new}")
        with patch.object(host, "_next_item", side_effect=AssertionError("Operation delegated back to dispatcher")):
            original = self.execute(host, "definition.store")
            assignment = self.execute(host, "meaning.assign")
            replacement = self.execute(host, "definition.store")
        self.assertIsInstance(original, StoredDefinition)
        self.assertIs(host.context.lookup_meaning("saved"), original)
        self.assertIs(host.context.lookup_meaning("donor"), replacement)
        self.assertTrue(assignment.metadata["donor_resolved"])
        self.assertEqual(host.context.catcodes["@"], CatCode.OTHER)
        self.assertEqual([t.value for t in original.body_tokens], ["makeatletter", "#", "1"])
        self.assertEqual(host.units.records[original.unit_id].span, original.span)
        self.assertEqual(host.reader.position, len(host.reader.text))

    def test_shared_catalog_does_not_share_document_meanings(self):
        first, second = self.host(r"\def\value{A}"), self.host(r"\let\saved\value")
        self.execute(first, "definition.store")
        command = self.execute(second, "meaning.assign")
        self.assertFalse(command.metadata["donor_resolved"])
        self.assertIsInstance(second.context.lookup_meaning("saved"), UncertainMeaning)
        self.assertIsNone(second.context.lookup_meaning("value"))
        self.assertEqual([t.value for t in first.context.lookup_definition("value").body_tokens], ["A"])

    def test_direct_scope_operations_restore_same_state_and_captured_catcodes(self):
        host = self.host(r"{\makeatletter\def\local{@}}")
        table = host.context.catcodes
        self.execute(host, "scope.begin")
        self.execute(host, "reading.apply_lexical_profile")
        definition = self.execute(host, "definition.store")
        self.execute(host, "scope.end")
        self.assertIs(host.reader.catcodes, table)
        self.assertIs(host.context.catcodes, table)
        self.assertEqual(table["@"], CatCode.OTHER)
        self.assertEqual(definition.body_tokens[0].catcode, CatCode.LETTER)
        self.assertIsNone(host.context.lookup_definition("local"))
        self.assertEqual(host.context.scope_depth, 0)

    def test_direct_call_refuses_inactive_or_detached_state_before_scanning(self):
        for condition in ("inactive", "detached"):
            with self.subTest(condition=condition):
                host = self.host(r"\let\saved\iftrue")
                opening = host.reader.next_event()
                profile = host.knowledge.resolve_command("let")
                if condition == "inactive":
                    host.context.mode = ExecutionMode.STORED_DEFINITION
                else:
                    host.reader.catcodes = host.context.catcodes.copy()
                position = host.reader.position
                with self.assertRaises(ReadingIssue) as caught:
                    CORE_OPERATIONS["meaning.assign"].execute(host, opening, profile)
                self.assertEqual(caught.exception.reason, "inactive_context" if condition == "inactive" else "context_changed")
                self.assertEqual(host.reader.position, position)
                self.assertIsNone(host.context.lookup_meaning("saved"))

    def test_direct_failed_definition_does_not_publish_partial_meaning(self):
        host = self.host(r"\def\target#1{unclosed")
        with self.assertRaises(ReadingIssue):
            self.execute(host, "definition.store")
        self.assertIsNone(host.context.lookup_meaning("target"))
        self.assertEqual(host.context.mode, ExecutionMode.ACTIVE_EXECUTION)


if __name__ == "__main__":
    unittest.main()
