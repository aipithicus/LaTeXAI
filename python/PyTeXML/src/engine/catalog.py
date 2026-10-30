"""The single assembly point for implemented language operations."""
from .operations import build_catalog
from .primitives import read_streams
from .primitives import code_tables, format_state, content, math_lists, content_events, alignments
from .primitives import assignments, definitions, grouping, expansion, parameters, conditionals, input, conversions, lookahead, registers, modes, rescanning, fonts
from . import file_hooks, semantic_drivers
from .latex import declarations, lookahead as latex_lookahead


CORE_CATALOG = build_catalog(definitions.FAMILY, grouping.FAMILY, assignments.FAMILY,
                             expansion.FAMILY, parameters.FAMILY, conditionals.FAMILY, input.FAMILY,
                             conversions.FAMILY, lookahead.FAMILY, registers.FAMILY, modes.FAMILY, rescanning.FAMILY, file_hooks.FAMILY,
                             declarations.FAMILY, latex_lookahead.FAMILY, fonts.FAMILY, read_streams.FAMILY, code_tables.FAMILY,
                             format_state.FAMILY, content.FAMILY, math_lists.FAMILY, content_events.FAMILY, alignments.FAMILY,
                             semantic_drivers.FAMILY)
CORE_OPERATIONS = CORE_CATALOG.operations
COMMON_PRIMITIVES = CORE_CATALOG.common_primitives
EXTENSIONS = CORE_CATALOG.extensions
