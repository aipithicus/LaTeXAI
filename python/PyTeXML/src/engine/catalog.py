"""The single assembly point for implemented language operations."""
from .operations import build_catalog
from .primitives import assignments, definitions, grouping, expansion, parameters, conditionals, input, conversions, lookahead, registers, modes, rescanning
from . import file_hooks


CORE_CATALOG = build_catalog(definitions.FAMILY, grouping.FAMILY, assignments.FAMILY,
                             expansion.FAMILY, parameters.FAMILY, conditionals.FAMILY, input.FAMILY,
                             conversions.FAMILY, lookahead.FAMILY, registers.FAMILY, modes.FAMILY, rescanning.FAMILY, file_hooks.FAMILY)
CORE_OPERATIONS = CORE_CATALOG.operations
COMMON_PRIMITIVES = CORE_CATALOG.common_primitives
EXTENSIONS = CORE_CATALOG.extensions
