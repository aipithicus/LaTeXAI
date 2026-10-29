"""Registration errors fail before a document reaches the offending primitive."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from src.engine.catalog import CORE_CATALOG, CORE_OPERATIONS
from src.engine.operations import (ExecutableOperation, ExpansionKind, OperationFamily,
                                   PrimitiveDeclaration, PrimitiveOperation, build_catalog)
from src.engine.primitives import definitions, expansion, parameters
from src.engine.profiles import engine_profile


class EngineRegistrationTests(unittest.TestCase):
    def test_native_operand_contract_is_checked_at_declaration(self):
        for operation, operand in ((definitions.STORE, "def"), (parameters.ASSIGN, None),
                                   (expansion.RELAX, "relax")):
            with self.subTest(operation=operation.identity), self.assertRaisesRegex(TypeError, "operand"):
                operation.declare("bad", operand)
        with self.assertRaisesRegex(TypeError, "operand"):
            PrimitiveDeclaration("bad", definitions.STORE, None)

    def test_shared_handler_preserves_distinct_primitive_identities(self):
        meanings = CORE_CATALOG.common_primitives
        self.assertEqual({meanings[name].operation for name in ("def", "gdef", "edef", "xdef")},
                         {definitions.STORE.identity})
        self.assertEqual(len({meanings[name].identity for name in ("def", "gdef", "edef", "xdef")}), 4)
        self.assertNotEqual(meanings["widowpenalty"].identity, meanings["clubpenalty"].identity)

    def test_dangling_or_replaced_operation_reference_is_rejected(self):
        declaration = expansion.RELAX.declare("test", None)
        for operations in ((), (replace(expansion.RELAX),)):
            with self.subTest(operations=operations), self.assertRaisesRegex(ValueError, "Dangling operation"):
                build_catalog(OperationFamily(operations, (declaration,)))

    def test_conflicting_names_are_rejected_including_common_extension_overlap(self):
        first = expansion.RELAX.declare("same", None)
        for extension in (False, True):
            second = expansion.RELAX.declare("same", None, extension=extension)
            with self.subTest(extension=extension), self.assertRaisesRegex(ValueError, "Conflicting primitive"):
                build_catalog(OperationFamily((expansion.RELAX,), (first,)), OperationFamily((), (second,)))

    def test_invalid_capability_combinations_are_rejected(self):
        cases = (
            (expansion.RELAX, {"expansion": expansion.noexpand}),
            (expansion.RELAX, {"handler": None}),
            (expansion.RELAX, {"expansion_unavailable": True}),
            (expansion.NOEXPAND, {"expansion": None}),
            (expansion.NOEXPAND, {"expansion_unavailable": True}),
            (expansion.NOEXPAND, {"integer_value": parameters.integer_value}),
            (expansion.NOEXPAND, {"continuation": True}),
            (expansion.RELAX, {"capture": "handler.location"}),
            (expansion.RELAX, {"expansion_kind": "unexpandable"}),
            (expansion.RELAX, {"expansion_kind": ExpansionKind.INTERNAL}),
            (CORE_OPERATIONS["kernel.define_command"], {"capture": expansion.capture_relax}),
        )
        for operation, changes in cases:
            with self.subTest(operation=operation.identity, changes=changes), self.assertRaises((ValueError, TypeError)):
                replace(operation, **changes)

    def test_expansion_classification_is_required_and_unavailability_explicit(self):
        with self.assertRaises(TypeError):
            ExecutableOperation("missing.classification")
        conditional = CORE_OPERATIONS["conditional.route"]
        self.assertEqual(conditional.expansion_kind, ExpansionKind.EXPANDABLE)
        self.assertTrue(conditional.expansion_unavailable)
        self.assertIsNotNone(conditional.handler)
        self.assertIsNone(conditional.expansion)

    def test_kernel_bridge_cannot_be_declared_as_a_native_primitive(self):
        with self.assertRaisesRegex(TypeError, "native operation"):
            PrimitiveDeclaration("bad", CORE_OPERATIONS["kernel.define_command"], None)

    def test_assembled_indexes_and_selected_environments_are_immutable(self):
        for mapping in (CORE_CATALOG.operations, CORE_CATALOG.common_primitives, CORE_CATALOG.extensions,
                        engine_profile().primitives):
            with self.subTest(mapping=type(mapping)), self.assertRaises(TypeError):
                mapping["new"] = None
        self.assertIs(engine_profile().lookup("def"), CORE_CATALOG.common_primitives["def"])
        self.assertIs(engine_profile().lookup("pdfoutput"), engine_profile().primitives["pdfoutput"])

    def test_context_and_catalog_can_each_be_the_first_import(self):
        for module in ("src.reading.context", "src.engine.catalog", "src.engine.profiles"):
            result = subprocess.run([sys.executable, "-B", "-c", f"import {module}; from src.engine.profiles import engine_profile; assert engine_profile().lookup('def')"],
                                    cwd=PROJECT, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
