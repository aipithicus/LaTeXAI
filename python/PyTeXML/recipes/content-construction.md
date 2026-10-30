# Content construction checkpoint

The document trace's third stage now has a bounded **pre-layout content consumer**.
`ContentBuilder` reuses the format builder's explicit inventory, restored context,
physical input owner, current-meaning dispatcher, scanners and token programs.
It returns structured content and a build receipt. It does not typeset pages or
claim general-document coverage.

## Implemented behavior

| Family | Constructed behavior |
| --- | --- |
| Text | Source-linked byte characters with font identity, spaces, paragraphs, `char`, `chardef`, current character aliases, `indent`, `noindent`, control space and pending italic correction. `everypar` runs before the triggering character. |
| Boxes | Live `hbox`, `vbox`, `vtop` groups; `to`/`spread` specifications; local/global `setbox`, `box`, `copy`, `lastbox`, horizontal/vertical unboxing and copying; shifts, `vcenter`, and issued `shipout`. Box content is stored separately from measurement. |
| State queries | `wd`, `ht`, `dp`, explicit measurement mutation, void/hbox/vbox tests, horizontal/vertical/math/inner mode tests and `ifdim`. Known explicit sizes and empty boxes can answer; unresolved natural dimensions stop with `unknown_box_dimension`. |
| List nodes | Ordinary and math glue/kerns, infinite glue, penalties, rules with running dimensions, box leaders, `unskip`, `unkern`, `unpenalty`, and supported internal-list tail queries. Unknown font spacing/italic correction stays unknown. |
| Math | Inline/display math lists; math codes/families, `mathchar`/`mathchardef`, grouped nuclei, scripts, atom classes, operator limits, styles, fractions, delimiters, radicals, accents, over/underlines, four-way `mathchoice`, and `everymath`/`everydisplay`. Lists have not undergone noad conversion. |
| Alignment | Finite `halign` preambles with exactly one parameter marker per column; live cells, templates, tabs, `cr`/`crcr`, `omit`, `noalign`, `everycr`, and the established `tabskip`. Cell and row structure is retained without computed column widths. |
| Events | Expanded marks (including numbered mark classes), insertion/adjustment bodies, specials, issued shipouts and writes. Deferred writes retain raw tokens; immediate writes capture expansion at issuance. No external output is performed. |

Boxes, math groups, insertions and alignment cells execute through the **live
mouth**, so a category-code assignment affects later physical characters. Only
TeX's stored material (macros, hooks, alignment templates, mark/write arguments)
uses frozen tokens. An alias is dispatched by its current meaning, not its name.

Content participates in `LanguageState` rollback. A failed macro invocation
restores both nodes and language effects. Earlier completed content remains in
the result, and unfinished lists are exposed separately as `open_lists`.
Node locations are **origin anchors**, not fabricated full source extents.
Generated macro coordinates are mapped through the existing origin relation.

Box extraction clears the current slot without making a new scope-save entry.
An earlier local `setbox` still restores its saved value. Dimension mutation also
changes the current box without introducing a new save entry. `afterassignment`
at a box assignment executes at box entry, before `everyhbox`/`everyvbox` and the
body; `aftergroup` content follows publication of the closed box.

## Run it

From `python/PyTeXML`, with the project Python through `pwsh_exec`:

```text
python -B -m src.engine.content_builder tests/fixtures/engine/content-construction.inventory.json --output ../../temp/engine-source-work/content-python/content.json
```

The inventory uses the format builder's `entry`, `sources`, `metrics`, `profile`
and optional explicit clock initialization fields. `--restore` accepts its
versioned Python format snapshot, subject to the same source/code/profile checks.
Each execution copies the restored context. `--budget` bounds top-level work;
existing expansion/program/input limits, 64 nested content groups and a 100,000
node-work budget also apply. Expanded references count against that budget, so
sharing copied boxes cannot hide exponential tree growth. Content is written even
on a boundary, with an unsuccessful exit status and a source remainder range.
Without a restored format, execution starts in the format builder's explicit
INITEX state; LaTeX meanings and category codes are not silently assumed.

The output has a `pytexml-content-build/1` receipt and a `pytexml-content/1` tree.
Characters are unshaped, paragraphs unbroken, boxes unpacked and math unconverted.
Unknown dimensions serialize as `null`. The context also retains unshipped box
registers. This strict bounded runner is a development API/CLI; production
preparation and best-effort extraction retain their separate ownership contracts.

## Qualification

`tests/test_content_construction.py` covers current meanings, raw physical category
changes inside boxes/cells, frozen templates, macro-created groups, register
restoration, scheduling, modes, fields/scripts, list-tail mutations, partial
results and rollback, input, restored formats and event timing.

The tracked `content-construction-source.tex` is run under two observer wrappers.
The native wrapper defines `observe`/`peek` as `showbox`/`showlists`; the Python
wrapper makes those observers inert and copies the retained boxes into its tree.
The shared source and wrappers are hash-pinned in
`tests/fixtures/engine/content-construction.expected.json`.

The native comparison matches every recorded field: four boxes' character
contents, two table rows/four cells, three math atoms with family/character values
and scripts/limits, ordered glue/kern/penalty nodes and values, and explicit box
width plus its mutation across a group. This is a selected structural comparison,
not equality of complete native list dumps or geometry. The fixture extends a
font parameter array to satisfy native math-list conversion; those artificial
math-font parameters are not a rendering reference.

Native evidence uses pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026), INITEX extended
mode. The receipt pins its executable hash. Algorithms and scope behavior follow
[TeX82 source](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web),
especially `main_control`, `begin_box`/`box_end`, `package`, `scan_math`,
`fin_mlist`, `init_align`/`fin_col`, and box-dimension assignment.

Reproduce with an explicit native executable:

```text
python -B -m src.validation.content_native --pdftex <pdftex.exe> --output ../../temp/engine-source-work/content-native
```

The validator requires exactly five intentional `! OK.` diagnostics and TeX's
corresponding exit 1, a completion marker, every expected observation, and equality
with the Python projection. Unexpected native errors invalidate the receipt.
The successful acquired receipt is under
`temp/engine-source-work/content-native-final/receipt.json`.

The broad regression run executed **1,301 tests: 1,298 passed and three optional
native tests skipped**, with its complete harness streams under
`temp/engine-source-work/content-suite-final/`. The final depth/copy bounds and
remainder assertions were subsequently covered by **all 31 focused content
tests**; the native comparison was rerun successfully on that implementation.
The registry type check passed for 26 source files, and the example CLI completed.
Earlier regression runs exposed the duplicate YAML ownership of `noindent`,
environment fixtures using the newly established primitive name `box`, and old
expectations that `ifdim` had no operand scanner. The YAML duplicate was removed;
fixtures now use a free name with a separate primitive-conflict test; conditional
tests retain cursor/state rollback assertions and expect unresolved-operand
diagnostics. The source fixture also exposed and now covers provisional font
target handling in `font` definitions followed immediately by font selection.

## Remaining boundaries

This checkpoint does not implement ligatures, kerning, glyph metrics, interword
space-factor measurement, line/page breaking, output routines or PDF generation.
Character/font identity is captured before shaping, including characters which a
later missing-glyph check may reject. Outer vertical tail queries stop because
their answer depends on the absent page builder. Natural box geometry is not
guessed. Unboxing preserves the existing nodes; it does not calculate packing.

Alignment repetition, `span`, preamble `tabskip` assignments/expansion, `valign`
and display-alignment special handling remain explicit boundaries. Equation
numbers, generalized fractions, active math characters, discretionary lists,
rule leaders and other unsupported mode operations remain open. Math-choice
alternatives are retained rather than selected before a style/layout consumer.

PDF links/destinations/outlines/info/color stacks and pinned semantic drivers
remain L16 work. Marks and writes are issuance events, not page-selected marks or
completed auxiliary files. There is no output stream or shell execution here.

The existing execution-continuation limits still apply: an operand that needs to
cross from a bounded inserted program into unread physical input can stop rather
than consume that continuation incorrectly. Macro-generated physical input and
arbitrary hook continuations are not newly qualified. No full LaTeX startup,
collection performance, universal TeX-document support or production extraction
integration is claimed. Q4R/Q4S and the remaining queue gates stay open.
