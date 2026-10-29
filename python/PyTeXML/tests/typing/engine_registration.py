"""Static registration witnesses; run with the command in recipes/engine-registry.md.

Unused-ignore checking makes each negative witness fail if its error disappears.
This module is checked, not executed by the runtime test suite.
"""
from typing import assert_type

from src.engine.operations import ExpansionKind, PrimitiveOperation
from src.engine.primitive import PrimitiveMeaning
from src.engine.primitives.definitions import STORE, DefinitionSpec, store_primitive_definition
from src.engine.primitives.expansion import RELAX, relax

assert_type(STORE, PrimitiveOperation[DefinitionSpec])
assert_type(STORE.declare("customdef", DefinitionSpec()).meaning(), PrimitiveMeaning[DefinitionSpec])
assert_type(RELAX, PrimitiveOperation[None])

STORE.declare("bad", "wrong operand")  # type: ignore[arg-type]
PrimitiveOperation[DefinitionSpec]("bad.handler", ExpansionKind.UNEXPANDABLE,
                                  relax, operand_type=DefinitionSpec)  # type: ignore[arg-type]
PrimitiveOperation[DefinitionSpec]("bad.operand.type", ExpansionKind.UNEXPANDABLE,
                                  store_primitive_definition, operand_type=str)  # type: ignore[arg-type]


def wrong_capture(reader: object, context: object, token: object) -> None:
    pass


PrimitiveOperation[None]("bad.capture", ExpansionKind.UNEXPANDABLE, relax,
                         operand_type=type(None), capture=wrong_capture)  # type: ignore[arg-type]
