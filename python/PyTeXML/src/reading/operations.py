"""Adapt prototype reading profiles to fixed Python operation identities.

Resolve the current meaning before using this adapter: the catalog is not a
table of control-sequence spellings. Keeping this map in the reader prevents
the prototype binding vocabulary from becoming the engine's dispatch contract.
"""
from types import MappingProxyType

from ..engine.catalog import CORE_OPERATIONS


FAMILY_OPERATIONS = MappingProxyType({
    "parameter_assignment": CORE_OPERATIONS["parameter.assign_integer"],
    "expansion_control": CORE_OPERATIONS["expansion.noexpand"],
    "catcode_assignment": CORE_OPERATIONS["reading.assign_catcode"],
    "character_code_definition": CORE_OPERATIONS["meaning.define_character_code"],
    "meaning_assignment": CORE_OPERATIONS["meaning.assign"],
    "stored_definition": CORE_OPERATIONS["definition.store"],
    "collected_environment_definition": CORE_OPERATIONS["definition.store_environment"],
    "conditional_factory": CORE_OPERATIONS["definition.declare_boolean"],
    "environment_factory": CORE_OPERATIONS["definition.declare_environment"],
})

EFFECT_OPERATIONS = MappingProxyType({
    "push_lexical_scope": CORE_OPERATIONS["scope.begin"],
    "pop_lexical_scope": CORE_OPERATIONS["scope.end"],
    "assign_catcode": CORE_OPERATIONS["reading.apply_lexical_profile"],
    "expl3_lexical_enter": CORE_OPERATIONS["reading.apply_lexical_profile"],
    "expl3_lexical_exit": CORE_OPERATIONS["reading.apply_lexical_profile"],
})
