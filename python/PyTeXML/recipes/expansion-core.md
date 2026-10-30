# Expansion core

This checkpoint implements the 31 named operations from
[the document-trace note](../../../../aipithicus-issues/LaTeXAI/notes/opus-chat-doc-trace.md)
through the existing catalog, reader, expansion cursor, conditional frames and
transactional context. It does not establish the note's dispatch percentages or
claim a complete LaTeX format build. No manuscript or macro-name answer table is
installed.

This records the expansion-core checkpoint. The later
[state and format checkpoint](state-format-building.md) extends its glue,
dimension-unit, font-loading and format-snapshot boundaries; the limits below
describe this earlier qualification.

## Implemented scope

| Mechanism | Operations and qualification |
| --- | --- |
| Definitions and assignment | Existing `def`, `gdef`, `edef`, `let`, `long`, `global`; current meanings, aliases, frozen tokens and scope remain authoritative. |
| Expansion and conversion | Existing `expandafter`, `csname`, `expanded`, `noexpand`, `detokenize`, `number`, `string`; new general `romannumeral`, including positive, zero and negative integers and bounded output allocation. |
| Conditional execution | Existing `ifx`, `if`, `ifnum`, `iffalse`, `ifdefined`, `ifodd`, `ifcsname`, `else`, `fi`; new `ifcase`/`or`, `ifpdfabsnum`, `ifeof`. Execution and expansion use the same frame owner. pdfTeX alone exposes `ifpdfabsnum`. |
| Internal values | `the` distinguishes integers, dimensions and token lists. Dimensions use TeX's decimal display; token-list insertion retains categories and source occurrences. Supporting `toks`/`toksdef` provide assignment, copy, aliases and local/global scope. |
| Arithmetic | `advance` updates count/dimension registers and integer parameters, including aliases, optional expanded `by`, `globaldefs`, overflow boundaries and rollback. Glue arithmetic remains outside this checkpoint. |
| Font arrays | `fontdimen` reads/writes established arrays; writes are global, and only the most recently established font can extend its array. `nullfont` supplies the primitive initial array. Font loading and selection are later work. |
| Read streams | `read` tokenizes raw physical lines with current catcodes/endlinechar, balances groups across lines, preserves literal parameter tokens and source identity, and defines a scoped parameterless macro. `ifeof` observes stream state, including the extra EOF read. Supporting `openin`/`closein` operate on an explicit closed source inventory. |

Explicit dimensions currently accept `pt`, `sp`, and established internal
dimensions. Other units and font-relative measurements remain boundaries.
The supported integer and dimension ranges are unchanged. Expansion/read token
budgets and a 10,000-cell font-array budget fail before publishing partial state.
Native error recovery is not emulated: malformed operands, missing font state,
unbalanced EOF and terminal reads produce typed boundaries.

## Source-owner interface

The physical input owner supplies immutable decoded snapshots. Configuring the
inventory is explicit; an absent entry then means a known file miss. An
unconfigured inventory is unavailable, not an empty filesystem.

```python
from src.engine.read_streams import ReadSource

context = resolver.new_context(primitive_initial_state=True)
context.read_streams.configure({
    "UnicodeData.txt": ReadSource.from_text("UnicodeData.txt", decoded_text),
})
```

This interface performs no filesystem or terminal I/O. Source acquisition,
resource closure and preparation manifests still belong to the physical source
owner; automatic inventory construction for a full format build is later work.
The ordinary preparation route retains these commands and preserves an explicit
boundary when required state is absent.

An owner with source-derived font metrics can call
`context.fonts.establish(identity, scaled_point_parameters)` and install a
`PrimitiveMeaning("font.identifier", identity)` through `record_meaning`.
This is a state input contract, not a native font-dump import or a TFM loader.
The default document context guesses neither font metrics nor open-stream state.

## Evidence and reproduction

The algorithms follow primary
[TeX82 source](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web):
`print_roman_int`, `print_scaled`, `conditional`, `scan_something_internal`,
`find_font_dimen`, `read_toks` and register arithmetic. The existing insertion
algorithm retains its separately pinned pdfTeX source reference.

`tests/fixtures/engine/expansion-core-source.tex` is executed by both Python and
the native wrapper `expansion-core.tex`. Its 12 observations were acquired with
pdfTeX 1.40.29 (TeX Live 2026), INITEX extended mode, and are frozen in
`expansion-core.expected.json`. The witness covers all 31 named primitives,
including the nonzero Roman and multi-line read paths. It compares macro results
and displays, not rendering or an exhaustive primitive conformance suite.

From `tests/fixtures/engine`, with output directed into a disposable directory:

```text
pdftex -ini -etex -interaction=nonstopmode -halt-on-error -output-directory=<output> expansion-core.tex
```

From `python/PyTeXML`, through the configured project Python:

```text
python -B -m unittest discover -s tests -p "test_expansion_core.py" -v
python -B -m unittest discover -s tests -p "test_atlas_native.py" -v
python -B -m unittest discover -s tests -p "test_*.py"
```

The earlier P02-7 token-register, P02-8 group-alias and P03 Roman boundaries are
closed: all 14 atlas programs match their existing native references, including
all nine P03 invocation observations and helper redefinition/restoration.
The core tests additionally exercise aliases, scoping, catcodes, EOF, overflow,
source provenance, and rollback of stream positions/global font changes when a
later setup-program operation fails. Native logs and test receipts are retained
under `temp/expansion-core-20261030/`.

Regression qualification: 1,250 passed / three optional native checks skipped in
the 1,253-test broad run, followed by 25 passing focused tests that include the
final invalid-file-character provenance guard. The registry type check passes.

Full format startup, its reached-line metric and a derived format snapshot have
not been qualified here. The queue's compact-representation prerequisite still
applies before broad bootstrap; these bounded witnesses do not waive it.
