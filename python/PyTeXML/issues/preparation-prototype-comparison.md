# Restored prototype comparison — 2026-10-23

The comparison uses the restored `2405.15943v3-tex` source and historical
`extracted` output under `temp/prototype-05f370d`. Neither was modified. New runs
are separate, under the repository's `temp/t/pytexml/20261023-comparison`.
The production workflow still uses the new reader and dispatcher.

## Observed results

| Measure | Historical prototype output | Current workflow before this increment | Current workflow after this increment |
| --- | ---: | ---: | ---: |
| Master characters | 63,271 | 91,347 | 67,836 |
| SVG assets emitted | 9 | 0 | 9 |
| Inline bibliography | 33 entries | Absent | 33 entries; identical key set |
| Canonical bibliography resource | Absent | Absent | Both complete databases in one resource |
| Active manuscript traversal | Historical receipt only | Interrupted at local style `\newif` | Reaches document end |

Character counts are not a fidelity score. The current native bibliography uses
field-labelled content, while the historical output uses publisher-style formatting.
The restored raw source has no `.bbl`; the current run generates one directly from
the two `.bib` databases without a compiler. All 33 references resolve: eleven
come from `chaos.bib`, twenty-two from `ref.bib`.

All nine SVG derivatives are byte-identical to the historical output.
In the first reader-integration run, every identity provenance segment was compared
against its original source slice; all 1,061 emitted segments covered that master
continuously. The bibliography follow-up verifies all 1,060 current segments cover
the master continuously and all 412 identity segments match original slices. The retained local
style is byte-identical to the restored original. Source-cache receipts contain
four physical text reads: the manuscript, its style, and the two BibTeX databases.
These receipts do not claim that image inspection/conversion uses the text cache.

## Implemented sequence

1. **External literal resources:** `\verbatiminput`, `\VerbatimInput`, and
   `\lstinputlisting` use declarative argument grammars and cached source reads.
   Safe bodies are inserted as exact source slices with separate occurrences.
   A delimiter collision or unsupported reading option retains one necessary
   payload resource and rebases the reference. Original assets are not copied
   as a general fallback.
2. **Physical-line literals and preparation policy:** package-specific regex,
   column-zero and suffix rules select the reusable scanner. Recognized comment
   regions can be eliminated, ordinary literals preserved, and included-comment
   wrappers unwrapped. Discarded closing-line suffixes produce warnings. Other
   policy/event/projection settings remain provisional.
3. **Bounded reading effects:** local decimal/backtick catcode assignments route
   through the dispatcher. Computed numbers, unsupported numeric forms and
   general frozen-token pushback remain pending. YAML factory recipes register
   custom literal/excluded/included environments with scoped restoration.
   Included bodies are captured first, then replayed from the same in-memory
   source basis, without adding a group or writing a temporary cut file.
4. **Real-paper integration fixes:** a retained style's unsupported operation no
   longer aborts manuscript discovery; an explicit input checkpoint restores the
   caller's entry state and records missing style effects. Image dimensions such
   as `width=0.5\linewidth` no longer make an otherwise literal filename unresolved.
   Conflicting bibliography records remain together in a canonical payload and
   defer formatting instead of preventing publication of the master.
5. **Bibliography discovery:** the narrow `natbib` YAML contract describes citation
   headers without package-specific Python. Pending activation retains a provisional
   command observation; it does not prevent literal key collection. Selection uses
   those keys, not overall dependency closure. Only `\nocite{*}` requests all entries;
   the complete canonical resource retains uncited metadata and unresolved variants.
6. **Assets inside deferred environments:** direct image headers captured by the
   dispatcher remain observations with their binding grammar and original spans.
   Preparation resolves their literal filenames against entry search settings,
   emits the SVGs, and changes only those filenames in the preserved environment.
   Candidate dependency records retain the unexecuted context and payload path;
   they are not promoted to established active edges. No `suppfigure` special case
   or general author-macro expansion was added.

The reusable reading components do not decide what to delete. Package knowledge
remains in YAML; preparation owns policy and emission. This increment neither
expands arbitrary macros nor establishes the future XML/async binding contract.

## Remaining gaps exposed by this paper

- `neurips_2024.sty:24` uses `\newif`; its effects and later package-option logic
  remain unresolved. Caller continuation uses a recorded preparation assumption,
  not successful style execution.
- `LN.png` and `MSEvsloss.png` occur inside author-defined `suppfigure` environments
  at manuscript lines 531 and 538. Both are now packaged as `LN.svg` and
  `MSEvsloss.svg`, and the master references those payloads. The environments still
  have no established reading contract: their declarations and bodies remain
  unexpanded, and the manifest reports seven active images plus two prepared
  candidate images. Discovery is resolved under the recorded entry-state
  assumptions; complete environment interpretation is not claimed.
- The databases contain differing versions of twelve keys, plus undefined strings
  and repeated fields, but none of those conflicting keys is among the paper's 33
  references. The earlier wildcard selection made these unrelated records block
  formatting. The new run embeds all 33 references and retains both full databases
  in `bibliography.bib` (424,249 bytes). `\citep` activation through the local style
  is still pending, explicitly recorded separately from key observation. Author
  macros and citations inside uninterpreted arguments still need later resolution.
- Metadata footprint still needs attention: the current manifest and provenance
  total 764,222 bytes, versus roughly 37 KB historically. The new records retain
  more source and requirement detail. Compact repeated diagnostics without losing
  occurrence coordinates; do not treat shorter sidecars as evidence of correctness.

The run is reported as **partial** because reading/interpretation requirements
remain. The next comparison task is an optional rendering adapter for the SVG
payload and a consistent font configuration. Broader author-environment contracts
and general package execution remain separate work.

## Verification

The first increment passed **389 tests**. Its cases exercise repeated cached
literal input, delimiter collisions, nested option groups, strict comment endings,
live-catcode incompatibility, source-window bounds, scoped factories, replayed child
inputs and effects, rollback of an unfinished replay, retained-style recovery,
computed image widths, and canonical preservation of conflicting bibliography data.

The bibliography follow-up passes the full suite of **400 tests**, including split databases, unused conflicting
records, late/repeated citations, active and pending package grammars, optional
notes, source protection, explicit wildcards and incomplete citation discovery.
The real-paper rerun confirms 33 unique inlined items, matching the historical key
set, exact retention of both databases, and one cached read per text source. Original
manuscript/style/database files and the historical master remain unchanged.

The environment-asset follow-up passes **409 tests**. Nine new cases cover repeated
cached input, exact preservation around multiple filename edits, lossless embedded
image bytes, protected and skipped source, provisional package syntax, unresolved
filenames/pages, search context, shadowed commands, and emission rollback. The
paper rerun emits all nine images; the two newly included derivatives match the
historical SVGs and preserve the original PNG bytes. Only the two filenames change
in the master. The other seven derivatives, all 33 inlined references, and the
canonical bibliography are unchanged. All 1,060 provenance segments still cover
the master continuously, and the 412 identity segments match their source slices.

The editor's optional PDF validation failed inside XeTeX, reporting
`Fontconfig error: Cannot load default config file` and
`unable to read an entire line (buf_size=200000)`. This is not a successful PDF
validation. It did not change the preparation result or add a runtime compiler
dependency; the rerun's master bytes are identical before and after the final
diagnostic refinement.

The physical-line replay behavior follows the
[comment 3.8 manual](https://mirrors.ctan.org/macros/latex/contrib/comment/comment.pdf):
included bodies are read again and do not acquire an implicit group. Fancyvrb's
factory recipe was checked against the vendored package source.
