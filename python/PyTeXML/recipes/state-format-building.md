# State and format building

This checkpoint extends the document-trace expansion core with state families
and a bounded INITEX build/dump/restore consumer. It executes through the existing
operation catalog, dispatcher, lazy physical reader and transactional context.
A successful build means that the source reached `\dump` and produced a Python
format snapshot. EOF without a dump, retained source and unsupported effects are
reported separately. This is not full LaTeX startup qualification.

## Implemented scope

| Family | Behavior |
| --- | --- |
| Registers | `count`, `dimen`, `skip`, `muskip`, `toks`, their `...def` aliases, local/global assignments and `advance`, `multiply`, `divide`. Integer division truncates toward zero; glue retains independent stretch/shrink orders. Overflow and division by zero roll back. |
| Dimensions | `pt`, `pc`, `in`, `bp`, `cm`, `mm`, `dd`, `cc`, `sp`, magnified true units, established internal dimensions and font-relative `em`/`ex`; finite and `fil`/`fill`/`filll` glue components. |
| Code tables | Existing `catcode`/`chardef`, plus byte-domain `lccode`, `uccode`, `sfcode`, `mathcode`, `delcode` and `mathchardef`. Case conversion changes character values while preserving categories and source origins. |
| Scoped state | Existing braces and `begingroup`/`endgroup`; raw-token `afterassignment` replacement and ordered `aftergroup` insertion. Inserted setup programs use the existing bounded execution owner. |
| Parameters | TeX82 integer, dimension, glue, math-glue and token-list parameter declarations in the parameter/register modules. Storing a layout parameter does not execute layout. Existing `pdfoutput` remains store-only. |
| Input | Explicit finite source inventory for native `input` and existing physical-line `endinput`; transactional `openin`, `read`, raw `readline`, `closein`, `ifeof`. No host search or terminal reads. |
| Fonts | Supplied TFM bytes establish font parameter arrays at design, explicit or scaled sizes; `font`, selection, `fontdimen`, `hyphenchar`, `skewchar`, `textfont`, `scriptfont`, `scriptscriptfont`. Font definitions/selections/families obey scope; font parameters and character properties are global. |
| Format data | Explicit `jobname`, expanded `message`, immediate diagnostic writes to streams -1/16/17, stored expanded `patterns`/`hyphenation` token data, `dump`, and restored `everyjob` execution. |

The native format owner installs `input` and `end` meanings. The ordinary document
baseline retains its existing LaTeX input/end wrappers. No per-macro answer table
or native format dump is used as production state.

## Snapshot contract

`src/engine/format_snapshot.py` writes versioned JSON with a whitelisted object
graph. Aliases, token categories, typed state, original source coordinates and
generated-to-authored token relations survive restoration. Each build copies its
entry context; mutations in one restored document do not change the reusable
entry state. A new source occurrence sequence continues after the saved one.

The key includes decoded source content hashes, metric hashes, explicit clock initialization, the primitive
profile and profile source hash, representation schema, and an implementation
digest of the engine/reading modules. A checksum catches payload corruption.
Changes to the supplied inventory, profile, schema or implementation reject the
snapshot. The complete inventory is deliberately conservative: even an unused
inventory change invalidates this first implementation.

Dump requires balanced, settled core state. Open read streams, pending scheduled
tokens, uncertain values, recovery assumptions and unrepresented extension state
are rejected. Runtime messages and jobname are excluded; resources are supplied
again and jobname is rebound to the new entry. Time/day/month/year are refreshed
from the inventory's optional `initialization` object, which accepts integer
values for those four parameters. An unsupplied value remains unavailable; no
host clock or zero date is silently assumed. Python snapshots are not native
`.fmt` files. The graph interns serialized identities; it does not implement Q4R's
compact runtime representation or close the collection-scale Q4S gate.

## Run a bounded build

From `python/PyTeXML`, using the project Python through `pwsh_exec`:

```text
python -B -m src.engine.format_builder tests/fixtures/engine/state-format.inventory.json --output ../../temp/engine-source-work/state-format-python/format.json --receipt ../../temp/engine-source-work/state-format-python/build.json
python -B -m src.engine.format_builder tests/fixtures/engine/state-format.inventory.json --restore ../../temp/engine-source-work/state-format-python/format.json --entry state-format-resume.tex --no-dump --receipt ../../temp/engine-source-work/state-format-python/restore.json
```

The inventory names an entry and maps logical source/metric names to explicit
local files relative to the inventory. The receipt records status, source hashes,
state counts, diagnostics, stopping source/offsets, wall/CPU counters and process
peak RSS. Failed builds do not write a snapshot. The default limits are 10,000
top-level steps, 64 nested input occurrences and four million decoded inventory
characters, in addition to the existing expansion/program budgets.

## Qualification

`tests/fixtures/engine/state-format.tex` and its included source build a small
format in both Python and pdfTeX. `state-format-resume.tex` then runs against each
saved format. The fixed reference denominator is **13 observations: 13 matched,
zero mismatching, zero unqualified**. These are behavior observations, not a
whole-format meaning census or a claim about the trace note's percentages.

The comparison covers code tables, math character values, glue orders and signed
arithmetic, exact unit rounding, scheduling order, case conversion, parameter
scope, TFM scaling, raw-line categories, immediate diagnostics, restored aliases,
register/font state, and `everyjob`/jobname. Native evidence was acquired with
pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026), first in INITEX extended mode and
then using its generated `.fmt`. Expected observations are tracked in
`state-format.expected.json`.

The unmodified `cmr10.tfm` fixture comes from the pinned TeX Live oracle's
`texmf-dist/fonts/tfm/public/cm/cmr10.tfm`; SHA-256 is
`87f2d8981927644cbecaf3d639e96e348ea4e7be49d8804468bd8ba9ff3f5244`.
Algorithms follow primary [TeX82 source](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web),
including `scan_dimen`, `scan_glue`, `prefixed_command`, `after_token`,
`save_for_after`, `read_font_info`/`store_scaled`, and font parameter access.

Native reproduction, with a disposable output directory:

```text
pdftex -ini -etex -interaction=nonstopmode -halt-on-error -output-directory=<output> state-format.tex
pdftex -fmt=<output>/state-format.fmt -interaction=nonstopmode -halt-on-error -output-directory=<output> state-format-resume.tex
```

The 15 focused tests also cover restored provenance sharing, independent document
mutation, local restoration, failed-assignment rollback, source-inventory and
checksum invalidation, rejection of unsettled dumps, uncertainty instead of
invented zero state, preparation preservation/separators, and manifest JSON
serialization. The final broad run ran 1,269 tests: 1,266 passed and three optional
native checks skipped. The final true-unit rounding correction was qualified
separately by all 15 state/format and 79 expansion tests, plus the native fixture.
The registry type check passes. Full regression receipts live
under `temp/engine-source-work/state-format-suite-*`; native transcripts and Python
build/restore artifacts are in adjacent `state-format-native` and
`state-format-python` directories.

The final counter-only CLI run measured build 0.325 s wall / 0.313 s CPU /
37,212,160 bytes process peak RSS; restore plus the resume source measured
0.344 s wall / 0.313 s CPU / 37,986,304 bytes peak RSS. Both include inventory and
resolver construction. They perform different work;
these are reproducibility observations, not a speedup claim or a collection
throughput qualification.

## Remaining boundaries

Physical-source insertions must form complete bounded setup programs. General
operands spanning inserted tokens and the physical continuation, case conversion
of typeset content, and macro-generated input/dump ownership still need the
general continuation work. `\the` of a font whose original selector was redefined
stops explicitly pending a frozen font-token representation.

The TFM reader establishes parameter state; glyph lists, ligatures and full TFM
validation are not implemented here. Pattern/hyphenation data is stored without
building a native trie. Deferred writes, output files, shell escapes, terminal
interaction, layout, additional pdfTeX/e-TeX state families and exhaustive numeric
scanning remain outside qualification. Snapshots deliberately reject extension
state they cannot represent.

Full `latex.ltx` startup, whole-format census matching, package patching across a
restored production format and controlled collection CPU/memory comparisons
remain open. The queue's Q4R prerequisite continues to apply before broad startup.
