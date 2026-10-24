# PyTeXML: preparation contract

The [project README](../README.md) records current module locations and execution
commands. Preparation code lives in `src/prepare/`; reusable reading machinery
and binding resolution live in `src/reading/` and `src/bindings/`.

## Purpose

Preparation turns a source project into a compact extraction package. After a
complete preparation, `extracted/master.tex` is the authoritative manuscript
for subsequent stages. Raw-source paths in diagnostics are bookkeeping, not
runtime dependencies. The package does not duplicate original image assets.

The target is a canonical XML substrate for model consumption, retrieval, and
later projections. Content and metadata take priority over the source layout.
An optional future presentation sidecar may retain style choices and formatting
intent for more faithful visual projections. It is not implemented or required
by preparation, and does not imply copying original assets.

Filesystem I/O and persistent footprint are both design constraints. Repeated
preparation passes should share source buffers and derived records in memory.
Only designed outputs and intentional diagnostic/publication checkpoints belong
on disk. The prototype combines source-assembly ideas from latexpand,
dependency-selected packaging from arxiv_collector, source/asset cleanup from
arxiv_latex_cleaner, and the author's whitespace-normalization work. Their original
submission workflows do not define this project's output or engine requirements.

The target is an extraction-ready representation. Compilation, layout equality,
complete dependency discovery, and byte-exact provenance are separate properties;
this prototype has not established those properties for arbitrary TeX projects.

The emitted manifest's `entrypoint` is `master.tex`. Its `root_file` and absolute
source paths record the discovery inputs for diagnostics.

Emission is not gated on a complete binding library. Missing package bindings
and ordinary unexpanded expressions produce located `requirements` while later
literal inputs continue to assemble. Requirements identify preparation, binding
or interpretation work. `preparation_status: complete` means the implemented
preparation operations finished; it does not certify expanded semantics.
`source_dependency_closure` describes source-visible requests under the recorded
`reading_assumptions`; `dependency_closure` also accounts for outstanding
interpretation and binding knowledge. Pending preparation work produces `partial`
status. A partial master can retain unresolved references. Neither an emitted
entrypoint nor a completed lexical pass proves raw-source independence.

## Package

| File | Role |
| --- | --- |
| `master.tex` | Flattened manuscript, including the prepared bibliography |
| `bibliography.bbl` | Prepared classic `thebibliography`, also embedded in the master |
| `bibliography.bib` | One package-local database for optional metadata enrichment, when source databases are available |
| `*.svg` | Converted file-backed assets, preserving relative subdirectories |
| Local styles/code | Discovered local dependencies needed by the master |
| `manifest.json` | Discovery results, bibliography preparation fields, image dimensions/diagnostics, implicit graphics candidates |
| `master.provenance.json` | Version 2 emitted-character intervals with source occurrence identity |
| `preparation.log` | `STARTED`, `SUCCESS`, `PARTIAL`, or `FAILED`, with located diagnostics |

Complete preparation uses SVG derivatives only. A missing active image, conversion
failure, or unavailable raster dimensions is an error, not permission to
fabricate dimensions, leave an unresolved image reference, or copy all originals.
An unsupported reading request, such as unimplemented PDF page selection, is
preserved in a partial master and diagnosed; it is never converted as page one.
The current converter supports raster wrapping and PDF/SVG conversion. EPS needs
a functioning converter; raw EPS bytes must not be mislabeled as PNG.

Preparation writes the master only after its preceding phases succeed. A rerun invalidates its previous master before traversal; `preparation.log` appends the new attempt and result. Callers must check the exception/exit status. Atomic replacement of an
entire existing output package remains future work. Knowledge gaps are successful
partial emissions, not exceptions; callers must inspect `preparation_status` and
`dependency_closure` before treating output as a complete payload.

## Current stages

1. **Index/cache:** enumerate source files once, excluding generated output;
   lazily cache raw bytes, decoded buffers and decoding failures.
2. **Select root:** recognize class declarations and actual comment metadata
   through the reader. Multiple candidates require an explicit root.
3. **Traverse:** follow each active input occurrence in order through the same
   dispatcher. Share catcodes, scopes and package activation across input mouths;
   keep cursor state and source identity specific to each occurrence.
4. **Resolve:** gather file, package, image and bibliography requests at established
   command spans. Scan local styles and retain their required code. Missing
   package knowledge becomes a requirement. A fully scanned computed reference
   defers only that command. Ordinary unexpanded commands, dollar-delimited math
   and unbound environments are captured without executing their contents.
5. **Emit:** retain literal/definition slices; serialize established mouth events,
   discard comments and skipped bodies, and replace active input directives.
   Explicit paragraph tokens prevent accidental paragraphs at input seams. At a
   genuine reading boundary in emitted source, preserve the original root suffix. If an input
   traversal is unfinished, undo that root operation's emissions before keeping
   its original directive and following source. This avoids inventing EOF seams
   under unknown reading state. Previously completed root operations remain.
   Separately retained local code has an input checkpoint: unresolved code stays
   in the payload, its missing effects are diagnosed, and the caller resumes under
   its recorded entry-state assumptions. This does not establish package closure.
6. **Survey:** inspect every indexed `.tex`, `.sty`, `.cls`, `.bbl` and `.tikz`
   buffer with the same reader and scanners. Record candidate commands and
   protected regions independently of active occurrences. After a reading
   boundary, a lexical census uses an explicit independent entry profile; it
   does not authorize rewrites or establish active dependencies. Unreadable
   unreferenced sources receive survey diagnostics. No source copies are written.
7. **Prepare resources:** generate/emit/embed classic bibliography, convert assets,
   and rewrite resolved argument spans. Existing BBLs enter the traversal at
   their source site; generated TeX values receive a diagnostic reading audit,
   whose unsupported results do not veto bibliography serialization.
8. **Publish:** write master, dependency payload, manifest and character-span
   provenance. Publication is not yet a transactional directory swap.

Input lookup uses the root document directory then the project root, with an
explicit import directory when present. It never guesses by basename. Repeated
inputs share buffers but retain separate occurrences. Cycles, missing files and
ambiguous candidates fail explicitly. Braced and space-terminated primitive
input forms are supported. Endinput finishes its physical line before leaving
that input; the document's closing environment ends the document.

Root paths remain project-relative. Discovery excludes extracted/, the actual
output directory, .git/, artifacts/ and build/. Output cannot equal or contain
the source project. No external probe is invoked; execute_probe=True is rejected.

Source decoding is strict UTF-8, with located original-byte errors logged.
Cached buffers preserve CR/LF spelling and valid Unicode. Literal and definition
slices retain their characters. Ordinary whitespace emission follows bounded
mouth records; invisible characters are not deleted indiscriminately.
Provenance uses decoded Unicode codepoints, not UTF-8 byte offsets.

## Bibliography contract

The normal downstream interface is an inline `thebibliography` with its original
citation keys. Later extraction does not need to find raw `.bib` or `.bbl` paths.

- A supplied classic BBL is validated and reused. Its source databases are not
  required; if available, they provide optional enrichment data.
  With `natbib` active, this includes Harvard-family `\harvarditem` entries:
  declarative argument metadata identifies the citation key while preserving the
  author/year arguments and entry body. No macro expansion or style emulation is
  needed to assemble this bibliography. Plain `harvard` package activation still
  needs its own binding; this contract belongs to natbib's compatibility surface.
- When a BBL is missing, `bibtex.py` parses the declared databases without an
  engine or additional dependency. It handles balanced braced/quoted values,
  concatenation, string definitions, month abbreviations, preambles, and both
  entry delimiters. TeX field contents and unfamiliar fields are retained.
- Generated entries use a consistent extraction representation: keyed `bibitem`
  records with labelled type and fields. No publisher style or name formatting
  is emulated. Citation keys select entries; `nocite{*}` selects all. Explicit
  `crossref` and `xdata` parents are included as separate keyed records. Their
  fields are not silently inherited or renamed. A later interpreter can resolve
  those relationships with package-specific rules.
- Repeated fields and keys retain all occurrences and produce diagnostics.
  Conflicting records cannot be selected for inline output; uncited
  conflicts remain in the enrichment database with warnings. Exactly identical
  duplicates produce one inline item. Undefined strings are diagnosed during
  parsing and block emission only when a selected field or preamble uses them.
  Missing referenced entries, malformed syntax, and cyclic parent references
  fail explicitly. No
  first/last-value policy silently chooses between conflicting records.
  When a selected key conflicts, preparation emits the combined canonical database,
  rebases the bibliography declaration to it, and publishes a partial master with
  a located conflict. Inline formatting remains pending; variants are not discarded.
- `bibliography.bib` combines declared databases in declaration order without
  dropping fields that the formatted bibliography omits. It is a canonical
  package resource name, not a newly invented parsed bibliography schema. It can
  contain uncited entries; safe database subsetting is deferred.
- Preparation checks that every recognized literal citation key has a prepared
  `bibitem`. Missing entries and missing databases needed for generation are
  explicit errors. A bibliography that failed to prepare is never deleted.
- Biblatex metadata BBLs and multiple bibliography sites require additional
  support. The first classic site is prepared; subsequent sites are preserved
  and diagnosed. When citation discovery is incomplete, computed, or has no
  supported citations, native formatting uses only observed literal keys;
  unobserved metadata remains in the canonical bibliography resource. Only an
  explicit `\nocite{*}` requests all entries.
  Rich-format formatting and metadata adapters belong in a later expansion of
  this contract.

This is a bounded data reader and serializer, not the future Python binding
framework. The local `Pre/BibTeX.pm`, `Engine/BibTeX.pool.ltxml`, and
`Post/MakeBibliography.pm` illustrate separate parsing, field interpretation, and
formatting responsibilities. Harvesting/adapting those responsibilities must not
require executing the Perl engine or interpreting BST programs during normal
preparation. The eventual XML fields, rather than visual labels, own semantics.

## File-backed and implicit graphics

Direct image headers inside a captured, unbound environment are provisional
observations under its entry reading and search state. Existing package YAML
grammars supply the headers; the dispatcher protects comments, literals, stored
bodies, math and opaque arguments. Preparation resolves literal filenames, emits
SVG derivatives, and rewrites only the captured filename spans. It preserves the
environment's other source and its unresolved reading contract.

`candidate_dependencies` records these observations, their context spans and
resolved payloads; `candidate_images` inventories resolved images not already in
`active_images`. Neither is a claim that the environment executed. Missing,
computed or ambiguous candidates and unsupported pages remain requirements, and
an unexecuted search declaration prevents reuse of stale search settings. A
rolled-back source operation does not retain its candidate assets in the payload.
No per-environment Python exception or extra source-file read is required.

Implicit assets are recorded from dispatched environment metadata. Initial
coverage includes figure candidates; the old regex drawing/morphism detector
has been removed. Broader drawing environments require their reading bindings.
This stage does not render latent code or build the downstream XML.

## I/O, discovery and logging ownership

SourceStore supplies one file index and cached bytes/text to root selection,
traversal, local-code packaging and bibliography processing. Failures are cached.
Images still use library file APIs for inspection and conversion; these binary
reads are not covered by the source cache.

Dependency edges, input occurrences and unresolved locations belong to the
source owner. Coverage is built per occurrence. Unobserved gaps remain explicit.
Preserved root extents are recorded in `preserved_source_spans` and provenance as
`PRESERVE_UNRESOLVED`. This records exact source retention, not resolved reading
coverage. Files not established active while discovery is incomplete go into
`unclassified_files`; they are not labelled dormant. Diagnostics remain anchored
at the actual failing child/package location even when its splice is undone.
Image references resolve before conversion; argument spans own their rewrites.
Explicit image extensions sharing a stem get distinct SVG names; any remaining
destination collision fails rather than overwriting.

preparation.log appends start/outcome/error records. A reusable structured logger
remains future work. Resource writes can precede master publication; transactional
publication and obsolete-derivative cleanup remain open.

## Reusable lexical reader

The [source span engine specification](../../../../aipithicus-issues/LaTeXAI/briefs/source-span-engine.md)
defines the next integration layer: context-qualified spans, YAML-selected
structural/literal handlers, a shared reader cursor, staged dependency resolution,
and checked rewrite materialization. It distinguishes current foundations from
proposed APIs and implementation milestones.

[tex_reader.py](../src/reading/tex_reader.py) supplies a dependency-free,
in-memory character reader. It supplies preparation's structural dispatcher and emission layer, replacing heuristic normalization
by the preparation pipeline.

- It implements the N/M/S transitions for all 16 catcodes, control words and
  symbols, active-character identities, ignored/invalid characters, comments,
  spaces and paragraph tokens. Paragraph runs are not capped.
- It implements file-like physical-line handling (CRLF/CR/LF, trailing ASCII
  spaces, final and empty lines), configurable TeX82 `endlinechar`, and classic
  `^^` character preprocessing, including control-sequence lookahead.
- Catcodes are supplied through a document-owned mutable table. The caller selects
  a YAML mouth baseline; `latex_ascii` declares ASCII letters and TeX specials,
  with other Unicode characters defaulting to OTHER. Unicode is not normalized
  or classified with isalpha. There is no Python copy of the baseline assignments.
- `next_token()` returns one token at a time; callers can apply known reading
  effects before requesting another. `next_event()` additionally exposes skipped
  source and state transitions. The methods share a cursor. No token list or log
  is retained automatically, and the reader opens no files.
- Immutable tokens carry source and occurrence identity plus half-open decoded
  character spans. They are not byte offsets; encoding correspondence belongs
  to the source owner. Events identify consumed comment/end-of-line suffixes,
  while token origins identify the characters that contributed the token.

The reader follows the TeX82 character algorithm over decoded text. It does not
claim a complete pdfTeX/XeTeX/LuaTeX input implementation: extended Unicode caret
notation and engine/format-specific category initialization are outside this
contract. Invalid-category characters raise a persistent explicit error.

This module does not execute catcode assignments, expand macros, recognize
literal environments or serialize cleaned source. Those are consumers of the
reader. A binding/profile dispatcher must establish literal modes; a later
execution layer supplies scoped meanings and input/token stacks.
Iterating a configured `TexReader` does not automatically interpret commands in
that source. Its category table and `endline_char` are required constructor inputs.
## Independent binding resolver

[catalog.py](../src/bindings/catalog.py) loads and compiles binding/profile knowledge.
[resolver.py](../src/bindings/resolver.py) resolves occurrences against that catalog
without filesystem I/O. Multiple document-local resolvers can share one catalog.
Active package declarations take precedence over engine defaults; repeated
activation preserves the original load order. Effective
profiles retain literal defaults, binding overrides, argument grammar, boundary
rules and separate lexical-category/policy-role classifications.

[mouth_profiles.py](../src/reading/mouth_profiles.py) loads only `resources/profiles/mouth/`;
removed profile files have no fallback path. The catalog loads
`resources/registries/reading_handlers.yaml` separately as capability metadata,
not a literal profile or a claim that its future handlers execute today. Regex
character classes compile once into immutable layers.
[character_rules.py](../src/reading/character_rules.py) provides full-span
membership and maximal-run coverage queries on a supplied
character view. The reader's table memoizes individual character classifications;
it does not expand regexes into an enumerated Unicode table.

Bootstrap with `resolver.new_context("latex_ascii")`, then pass its `catcodes`
and `endlinechar` to `TexReader`. Baseline and literal configuration share the
same regex-rule contract, described in [the mouth profile reference](../resources/profiles/mouth/README.md).
The context implementation lives in [context.py](../src/reading/context.py);
baseline and resolved-effect types live in [contracts.py](../src/reading/contracts.py).
Inheritance and later effects overlay earlier layers in execution order; explicit
assignments override regex rules within a layer. Unknown fields, invalid patterns,
duplicate keys/identities and invalid numeric assignments produce configuration
errors. ASCII rule conflicts are checked during loading; conflicts involving other
characters are reported when queried. Unfamiliar manuscript constructs remain a
separate dispatcher concern.

Coverage queries supply offsets into their input view. Attaching source/occurrence
and reading-context identities, mapping transformed characters back to source,
and constructing the structural span engine are still downstream work. A raw
profile's regex coverage alone does not establish effective runtime catcodes or
the structural meaning of a region.

`ReaderContext` applies immediate local reading effects, with scoped catcode and
`endlinechar` restoration and expl3 guard/snapshot handling. A live reader can share
its category table; the caller must synchronize `endline_char` before subsequent
physical lines load. Argument scanning, stored definitions and skipped branches
suppress execution of these effects.

Supported literal options yield category assignments or explicit interpolation
plans. Unclassified options and unsupported operations return unresolved results.
Bounded literal `\catcode` assignments, physical-line literal bodies and declared
environment factories now route through the source dispatcher. Computed assignments,
general package configuration and interpolation execution remain pending.
The resolver does not expand macros, scan environments, or perform rewrites. Its
source-capture metadata preserves reading evidence without committing to an XML
schema. Preparation consumes supported role actions from policy; the remaining
lexical-event, normalization and projection settings remain provisional.

## Known limits and next design work

The production path uses the shared reader and dispatcher. It is deliberately
bounded: ordinary unknown commands/active characters and stored macro invocations
are preserved without expansion. Dollar-delimited math and unbound environments
are captured under entry catcodes, not interpreted. Unbound command envelopes
protect adjacent balanced groups without claiming to know the command's arity.
The manifest states the assumption that unbound behavior does not change reading
outside those envelopes. This is not a proof about arbitrary author macros.
Literal `\newif` declarations and their local true/false setters now share scoped
command meanings with stored definitions; established boolean tests use the same
conditional router and skipped scanner as constant predicates. All source remains
available through spans, and preparation retains declaration/setter commands.
Unexecuted possible mutations invalidate boolean knowledge, including suspended
outer meanings that a global effect could change. A later use preserves unresolved
source rather than selecting a branch from stale state. This bounded guard does
not infer arbitrary macro effects or supply persisted per-unit context.
Computed/global assignments, other predicates and unsupported literal grammars still
produce reading boundaries. Hooks, definition wrappers and subfile preamble
stripping need additional handlers.
Literal/definition/argument scans that exhaust their physical input are boundaries;
continuation across input EOF is not implemented. Active groups and evaluated
conditionals can cross input boundaries.

Current source grammars cover common literal dependencies, not all LaTeX packages.
Opaque arguments retain their contents and located deferred-dependency requests;
their bodies are not executed during header scanning. Local styles are retained with resolved file references
rebased. Imports or assets executed inside retained local code still need additional
payload contracts.

Generated bibliography fields can contain TeX. Definitions, dependencies and
unsupported behavior in these fields requires later resolution and produces
diagnostics. Native formatting still emits those values and the canonical
enrichment resource. Unknown field expressions do not retract later source edits
or undo an enclosing input. Actual field dependencies/effects remain diagnosed
for another resolution pass; the audit does not execute them retroactively.
Existing BBLs are traversed at their original source position.
Biblatex and later bibliography sites remain located preparation work.

SVG conversion still needs qualification for PDF page selection and richer options.
There is no unconditional style cleanup, draft-command deletion, general lint repair
or AST. Explicit legacy cleanup options fail instead of running regex transforms.

Provenance v2 records emitted extents and source occurrence ranges. Identity segments
permit direct character interpolation; transformed segments relate whole ranges.
Mixed-source lines and repeated inputs retain all origins. This does not claim
byte offsets or per-character correspondence inside replacements. Historical
cleanup witnesses remain in the
[cleanup checkpoint](../../../../aipithicus-issues/LaTeXAI/reports/compiler-research/prototype-cleanup-20260929.md);
current multi-file tests cover the resolved input/context/closure cases.

The architectural direction is source assembly plus resolution of reading
behavior, followed by emission of a compact master that may retain unexpanded
macros. General expansion and XML interpretation remain downstream. The shared
binding interface owns package knowledge and dependency declarations/rules;
author styles and definitions are handled dynamically. The required knowledge
stores include core-operation contracts, a default catcode profile used to
initialize mutable document-local state, and reusable literal-reading profiles.
Their interfaces and pass interactions are investigated in the
[source-preparation survey](../../../../aipithicus-issues/LaTeXAI/briefs/source-preparation-survey/README.md).
That design work does not block the bounded cleanup above.

It also does not block foundational engineering: source spans, an incremental
N/M/S token reader, character/token input frames, scoped assignments, definition
and argument scanning, and the core control operations needed for reading effects
can be implemented and tested before the complete Python binding library exists.
Preparation evaluates only what is needed to establish reading effects and
apply their justified source rewrites; ordinary macro expansion and deep
interpretation remain downstream. Internal evaluation does not automatically
replace the corresponding call in the emitted master, and an effect must not
be unintentionally duplicated by both its replacement and a retained call.
A small in-process
binding protocol can expose concrete missing capabilities as the implementation
reaches them; fixture providers can exercise that boundary before YAML migration.
The cleanup checkpoint specifies this implementation sequence and its invariants.

Linting should first produce diagnostics. Repair should be a separate explicit
operation with a recognized precondition, recorded edit and postcondition check.
Compilation, lint, rendered output and source-map checks provide different
evidence; a clean lint run cannot establish semantic equivalence. General
automatic lint/repair is not implemented in this patch.

## Verification

The focused Python drivers are [test_preprocessing.py](../tests/test_preprocessing.py)
for preparation and bibliography and [test_tex_reader.py](../tests/test_tex_reader.py)
for lexical conformance. Run the suite from the PyTeXML project root with a Python
environment containing the dependencies in [requirements.txt](../requirements.txt):

```powershell
python -B -m unittest discover -s tests -p 'test_*.py' -v
```

The generate/emit/embed test rejects any attempted subprocess invocation. Other
tests cover native bibliography syntax and parent relationships, repeated
input/cycles, nested roots, output exclusion on reruns, bibliography failures,
strict decoding, valid Unicode preservation, dimension/conversion errors,
conditional routing and paragraph preservation.
[test_preparation_traversal.py](../tests/test_preparation_traversal.py) covers the
production multi-file path, cached reads, imports, local code, asset lookup,
failures and occurrence-aware provenance. Runtime files live under
the project's `temp/tests/`; temporary fixture directories are cleaned up.

Reader fixtures cover all 48 state/category combinations, boundary and EOF
cases, comments versus spaces, mutable categories, classic caret notation and
source spans. Expected lexical results are specified directly, independently of
the old normalizer. The reader tests use no files or compiler processes.
