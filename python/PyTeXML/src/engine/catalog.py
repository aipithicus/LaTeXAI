"""The single assembly point for implemented language operations."""
from .operations import build_catalog
from .primitives import assignments, definitions, grouping, expansion


CORE_OPERATIONS = build_catalog(definitions.OPERATIONS, grouping.OPERATIONS, assignments.OPERATIONS, expansion.OPERATIONS)
