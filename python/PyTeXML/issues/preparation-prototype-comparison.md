# Restored prototype comparison — 2026-10-23

The comparison uses the restored `2405.15943v3-tex` source and historical
`extracted` output under `temp/prototype-05f370d`. Neither was modified. New runs
are separate, under the repository's `temp/t/pytexml/20261023-comparison`.
The production workflow still uses the new reader and dispatcher.

## Observed results

| Measure | Historical prototype output | Current workflow before this increment | Current workflow after this increment |
| --- | ---: | ---: | ---: |
| Master characters | 63,271 | 91,347 | 54,587 |
| SVG assets emitted | 9 | 0 | 7 |
| Inline bibliography | Present | Absent | Pending record-conflict resolution |
| Canonical bibliography resource | Absent | Absent | Present; declaration rebased to it |
| Active manuscript traversal | Historical receipt only | Interrupted at local style `\newif` | Reaches document end |

Character counts are not a fidelity score: the historical master contains an
inline bibliography, and the new run does not yet. The restored raw source has
no `.bbl`, although the historical master contains a formatted bibliography.
The original bibliography-generation inputs are therefore not fully reproduced
by this restoration.

The seven common SVG derivatives are byte-identical to the historical output.
Every identity provenance segment was compared against its original source slice;
all 1,061 emitted segments cover the new master continuously. The retained local
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

The reusable reading components do not decide what to delete. Package knowledge
remains in YAML; preparation owns policy and emission. This increment neither
expands arbitrary macros nor establishes the future XML/async binding contract.

## Remaining gaps exposed by this paper

- `neurips_2024.sty:24` uses `\newif`; its effects and later package-option logic
  remain unresolved. Caller continuation uses a recorded preparation assumption,
  not successful style execution.
- `LN.png` and `MSEvsloss.png` occur inside author-defined `suppfigure` environments
  at manuscript lines 531 and 538. Their dependency tokens are located, but those
  environments have no established reading contract. The references remain intact;
  no claim of a complete standalone dependency payload is made.
- The databases contain conflicting versions of twelve keys, plus undefined
  strings and repeated fields. Incomplete citation discovery requests all entries;
  selection encounters `Gome08a` first. The output retains all database records in
  `bibliography.bib` and labels formatting as `deferred-conflict`. No winner is
  silently selected and no formatted `.bbl` is fabricated.
- Metadata footprint still needs attention: the current manifest and provenance
  total roughly 751 KB, versus roughly 37 KB historically. The new records retain
  more source and requirement detail. Compact repeated diagnostics without losing
  occurrence coordinates; do not treat shorter sidecars as evidence of correctness.

The run is deliberately reported as **partial**. Next work should address bounded
author-environment reading/dependency contracts and bibliography record resolution,
using these observed cases. General package execution should remain a separate task.

## Verification

The full PyTeXML suite passed **389 tests**. New cases exercise repeated cached
literal input, delimiter collisions, nested option groups, strict comment endings,
live-catcode incompatibility, source-window bounds, scoped factories, replayed child
inputs and effects, rollback of an unfinished replay, retained-style recovery,
computed image widths, and canonical preservation of conflicting bibliography data.

The physical-line replay behavior follows the
[comment 3.8 manual](https://mirrors.ctan.org/macros/latex/contrib/comment/comment.pdf):
included bodies are read again and do not acquire an implicit group. Fancyvrb's
factory recipe was checked against the vendored package source.
