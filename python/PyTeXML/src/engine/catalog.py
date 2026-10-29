"""The single assembly point for implemented language operations."""
from .operations import build_catalog
from .primitives import assignments, definitions, grouping, expansion, parameters, conditionals


CORE_CATALOG = build_catalog(definitions.FAMILY, grouping.FAMILY, assignments.FAMILY,
                             expansion.FAMILY, parameters.FAMILY, conditionals.FAMILY)
CORE_OPERATIONS = CORE_CATALOG.operations
COMMON_PRIMITIVES = CORE_CATALOG.common_primitives
EXTENSIONS = CORE_CATALOG.extensions
