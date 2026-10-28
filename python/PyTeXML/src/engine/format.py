"""Established LaTeX-format meanings, installed in each document's mutable state.

These are format declarations, not engine primitives or spelling-based values.
Keep the supported set explicit and source-backed as consumers are added.
"""
from ..reading.contracts import CharacterCodeMeaning, TokenListMeaning, UndefinedMeaning
from ..reading.tex_reader import TokenKind


def latex_meanings():
    # ltplain.dtx v2.3m (2025/04/14), initial catcode setup:
    # \chardef\active=13. No manuscript source span is fabricated for the format.
    return {(TokenKind.CONTROL_SEQUENCE, "active"): CharacterCodeMeaning(
        None, 13, format_origin="https://github.com/latex3/latex2e/blob/develop/base/ltplain.dtx#L118"),
        # ltclass.dtx: \let\CurrentOption\@empty.
        (TokenKind.CONTROL_SEQUENCE, "CurrentOption"): TokenListMeaning(
            None, (), format_origin="https://github.com/latex3/latex2e/blob/develop/base/ltclass.dtx#L572"),
        # Explicit entry facts for the LaTeX baseline, checked by the format
        # witness. Missing catalog entries in general are NOT undefined.
        **{(TokenKind.CONTROL_SEQUENCE, name): UndefinedMeaning(
            None, format_origin="latex baseline: undefined sentinels; tests/fixtures/engine/meaning-comparison.tex")
           for name in ("undefined", "@undefined")}}
