# LaTeX Extractor: preparation contract

## Purpose

Preparation turns a source project into a compact extraction package. After a
successful preparation, `extracted/master.tex` is the authoritative manuscript
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

## Package

| File | Role |
| --- | --- |
| `master.tex` | Flattened manuscript, including the prepared bibliography |
| `bibliography.bbl` | Prepared classic `thebibliography`, also embedded in the master |
| `bibliography.bib` | One package-local database for optional metadata enrichment, when source databases are available |
| `*.svg` | Converted file-backed assets, preserving relative subdirectories |
| Local styles/code | Discovered local dependencies needed by the master |
| `manifest.json` | Discovery results, bibliography preparation fields, image dimensions/diagnostics, implicit graphics candidates |
| `master.provenance.json` | Current line-based diagnostic map; accuracy limitations below |
| `preparation.log` | `STARTED`, `SUCCESS`, or `FAILED`, with explicit errors/warnings |

Successful preparation uses SVG derivatives only. A missing active image, unsupported
conversion, or unavailable raster dimensions is an error, not permission to
fabricate dimensions, leave an unresolved image reference, or copy all originals.
The current converter supports raster wrapping and PDF/SVG conversion. EPS needs
a functioning converter; raw EPS bytes must not be mislabeled as PNG.

Preparation writes the master only after its preceding phases succeed. A failed
rerun leaves any previous master in place; `preparation.log` records the failed
attempt. Callers must check the exception/exit status. Atomic replacement of an
entire existing output package remains future work.

## Current stages

1. **Preflight:** discover a root, classify files, probe dimensions, identify
   bibliography declarations, and inventory implicit graphics candidates.
2. **Inline:** expand supported inclusion forms, preserving repeated occurrences
   and using the active recursion stack to detect cycles.
3. **Prune:** apply the existing bounded conditional/draft transformations.
4. **Prepare bibliography:** reuse or natively generate a BBL, check literal
   citation keys, emit it, and replace the bibliography command with its contents.
5. **Normalize:** apply the current whitespace/comment transformations.
6. **Convert:** create SVG assets and rewrite supported image references.
7. **Package:** emit the master, discovered dependencies, manifest and diagnostics.

Root paths remain project-relative, including roots below the project directory.
Discovery excludes `extracted/`, the caller's actual output directory, and the
existing `.git/`, `artifacts/`, and `build/` exclusions. An output directory cannot
equal or contain the source project.

Preparation and standalone preflight default to static traversal. The existing
compiler probe requires `execute_probe=True`; normal preparation has no compiler
dependency. Optional engine validation is a separate observation, not a fallback
for missing native bibliography support.

Source text is decoded as UTF-8 strictly. A decoding failure identifies the file
and every malformed byte span (original offset and hex bytes), aborts preparation,
and is recorded in `preparation.log`. Automatic encoding detection/transcoding is
not implemented. Generated text is written with explicit LF line endings.

Blanket Unicode normalization and invisible-character deletion were removed.
However, the inliner and string normalizer still convert additional Unicode
line separators to LF; full valid-Unicode preservation is not established.
This remaining unconditional conversion is a cleanup item. Decoding, TeX
interpretation, and projection policy are separate:
invisibility is not evidence of catcode 9 (ignored), and a layout-only effect may
be deliberately omitted by the canonical projection once interpreted. A valid
U+FFFD replacement character can also indicate earlier data loss, which cannot
be recovered by transcoding. Future lint should distinguish these cases. Any
repair needs context and a recorded edit, rather than blanket character deletion.

## Bibliography contract

The normal downstream interface is an inline `thebibliography` with its original
citation keys. Later extraction does not need to find raw `.bib` or `.bbl` paths.

- A supplied classic BBL is validated and reused. Its source databases are not
  required; if available, they provide optional enrichment data.
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
  Conflicting records fail when their key is selected for inline output; uncited
  conflicts remain in the enrichment database with warnings. Exactly identical
  duplicates produce one inline item. Undefined strings are diagnosed during
  parsing and block emission only when a selected field or preamble uses them.
  Missing referenced entries, malformed syntax, and cyclic parent references
  fail explicitly. No
  first/last-value policy silently chooses between conflicting records.
- `bibliography.bib` combines declared databases in declaration order without
  dropping fields that the formatted bibliography omits. It is a canonical
  package resource name, not a newly invented parsed bibliography schema. It can
  contain uncited entries; safe database subsetting is deferred.
- Preparation checks that every recognized literal citation key has a prepared
  `bibitem`. Missing entries and missing databases needed for generation are
  explicit errors. A bibliography that failed to prepare is never deleted.
- Biblatex metadata BBLs, multiple bibliography sites, and dynamically constructed
  citation keys require additional support and currently fail explicitly.
  Rich-format formatting and metadata adapters belong in a later expansion of
  this contract.

This is a bounded data reader and serializer, not the future Python binding
framework. The local `Pre/BibTeX.pm`, `Engine/BibTeX.pool.ltxml`, and
`Post/MakeBibliography.pm` illustrate separate parsing, field interpretation, and
formatting responsibilities. Harvesting/adapting those responsibilities must not
require executing the Perl engine or interpreting BST programs during normal
preparation. The eventual XML fields, rather than visual labels, own semantics.

## Implicit graphics

This stage discovers candidate drawings/diagrams that exist as latent source,
including assetless floats, recognized drawing environments and possible
morphism grids. It does not render them. These are heuristic observations, not a
claim of complete recognition or a reason to delete source.

The main extraction pipeline is expected to render them through an adaptation of
LaTeXML/LaTeXAI bindings, eventually represented in YAML or TOML. That rendering
contract is separate from the current file-backed asset conversion.

## Planned I/O, discovery and logging ownership

These are implementation targets, not descriptions of completed behavior:

- A run-scoped source repository owns one reusable output-aware file index and
  lazy immutable text buffers with original-byte correspondence. Reading passes
  share those buffers. Repeated inclusion keeps separate occurrence/state data;
  caching a file does not make one tokenization or execution valid everywhere.
- Discovery and inlining share reference records and a resolver. A cheap scan
  may identify candidates; the reader establishes their context, bindings supply
  package dependency rules, and author code is handled dynamically. Worklists
  revisit unresolved requests when relevant facts become available. Unknown
  activation must not be called dormant or complete closure.
- Asset requests are gathered early; conversion follows resolved demand,
  identity, page/options and collision-free destination allocation. Equivalent
  required conversions share a result. Metadata is obtained on demand and reused.
  Large binary inputs/derivatives use bounded buffers or controlled streaming.
- Analysis stages return content, edits, resource requests and diagnostics.
  Bibliography generation shares one in-memory BBL between inline emission and
  its requested sidecar. Intermediate sources and pass-state dumps are not
  default artifacts. Publication owns final writes and managed temporary files;
  preserving a previous complete output must not require copying the raw corpus.
- A small reusable Python logger receives caller-owned run/sink configuration
  and structured diagnostic events. A buffered append-only JSONL sink records
  start, phase, warning/error and final outcome events, with explicit flush and
  durability policy. Logging must not hide the original error. Provenance is a
  separately emitted mapping, not inferred from the log.

Currently, discovery enumerates/reopens files across several passes, native
bibliography generation rereads databases, stages write before final publication,
and preparation.log is overwritten rather than appended. Those shortcomings
remain open. The cleanup checkpoint specifies the shared-storage/logger-first
sequence, static discovery algorithm, asset planning and measurable I/O checks.

## Independent lexical reader

`tex_reader.py` supplies a dependency-free, in-memory character reader. It is a
new foundation, not yet the normalizer used by the preparation pipeline.

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
execution layer supplies scoped meanings and input/token stacks. Calling
Iterating a configured `TexReader` does not automatically interpret commands in
that source. Its category table and `endline_char` are required constructor inputs.
The existing `normalizer.py` remains the heuristic pipeline path until those
consumers and the source-preserving emitter are connected.

## Independent binding resolver

`binding_resolver.py` loads the YAML registries once, then resolves occurrences
without filesystem I/O. Active package declarations take precedence over engine
defaults; repeated activation preserves the original load order. Effective
profiles retain literal defaults, binding overrides, argument grammar, boundary
rules and separate lexical-category/policy-role classifications.

`mouth_profiles.py` loads only `profiles/mouth/`; removed profile files have no
fallback path. `operations.yaml` is retained as a separate provisional registry,
not a literal profile or a claim that its future handlers execute today. Regex
character classes compile once into immutable layers. `character_rules.py`
provides full-span membership and maximal-run coverage queries on a supplied
character view. The reader's table memoizes individual character classifications;
it does not expand regexes into an enumerated Unicode table.

Bootstrap with `resolver.new_context("latex_ascii")`, then pass its `catcodes`
and `endlinechar` to `TexReader`. Baseline and literal configuration share the
same regex-rule contract, described in [the mouth profile reference](profiles/mouth/README.md).
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
Dynamic `\catcode` arguments, package configuration commands, definition factories,
literal-body dispatch and interpolation execution still need the source dispatcher.
The resolver does not expand macros, scan environments, or perform rewrites. Its
source-capture metadata preserves reading evidence without committing to an XML
schema. Neither it nor the policy loader is wired into preparation yet.

## Known limits and next design work

The pipeline's TeX traversal still uses regular expressions and limited state
tracking. It does not yet use the independent reader or implement a TeX AST.
The separate BibTeX reader assembles nested data values, not arbitrary TeX execution.

The 2026-09-29 cleanup review reran all 38 focused tests successfully and
reproduced additional gaps outside that coverage: same-line inclusion loses
neighboring text or subsequent inputs; a commented end marker can truncate
content; missing inputs can become comments that disappear before a SUCCESS
result; stale recorder files can suppress static asset discovery; and distinct
assets with the same stem can overwrite one SVG destination. SUCCESS therefore
does not yet establish source/payload closure. These are actionable prototype
defects, not reasons to wait for bulk binding migration. The
[cleanup checkpoint](../../../aipithicus-issues/LaTeXAI/reports/compiler-research/prototype-cleanup-20260929.md)
records witnesses, immediate patch order and structural follow-up.

- Inlining still needs shared lexical context for comments, literal regions,
  command spans, definitions and conditionals. The repeated-input fix does not
  establish correctness for every inclusion form.
- Conditional deletion intervals are now merged before applying edits. Unknown
  conditional nesting and pruning inside literal/definition contexts remain
  unresolved. Default command-name-based pruning still needs redesign.
- A blank paragraph after a swallowed comment newline is preserved. This local
  repair does not qualify general whitespace normalization or style-file
  cleanup under arbitrary catcodes.
- Discovery remains heuristic. Local transitive dependencies, stale recorder
  files and dynamic paths need explicit resolution evidence.
- The provenance ledger counts tagged fragments as output lines even when edits
  join or split physical lines. Sequence alignment also guesses some origins.
  It must be replaced by emission-time span bookkeeping before exact diagnostic
  mapping can be claimed. RLE compression can follow that representation.
- Graphics options, search-path resolution, multiple PDF pages and naming
  collisions need further qualification.

The shared token reader precedes a larger AST. Its next consumers must establish
literal contexts and apply known reading effects through the supplied catcode
table. Unsupported effects must remain observable. AST structure can then be
built on those tokens for the constructs the extractor actually needs.

The architectural direction is source assembly plus resolution of reading
behavior, followed by emission of a compact master that may retain unexpanded
macros. General expansion and XML interpretation remain downstream. The shared
binding interface owns package knowledge and dependency declarations/rules;
author styles and definitions are handled dynamically. The required knowledge
stores include core-operation contracts, a default catcode profile used to
initialize mutable document-local state, and reusable literal-reading profiles.
Their interfaces and pass interactions are investigated in the
[source-preparation survey](../../../aipithicus-issues/LaTeXAI/briefs/source-preparation-survey/README.md).
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

The focused Python drivers are `t/latex-extractor/test_preprocessing.py` for the
existing pipeline and `t/latex-extractor/test_tex_reader.py` for lexical conformance:

```powershell
& python/.venv/Scripts/python.exe -B -m unittest discover -s t/latex-extractor -p 'test_*.py' -v
```

The generate/emit/embed test rejects any attempted subprocess invocation. Other
tests cover native bibliography syntax and parent relationships, repeated
input/cycles, nested roots, output exclusion on reruns, bibliography failures,
strict decoding, valid Unicode preservation, dimension/conversion errors,
overlapping deletions and paragraph preservation. Runtime files live under
`temp/t/latex-extractor/`; temporary fixture directories are cleaned up.

Reader fixtures cover all 48 state/category combinations, boundary and EOF
cases, comments versus spaces, mutable categories, classic caret notation and
source spans. Expected lexical results are specified directly, independently of
the old normalizer. The reader tests use no files or compiler processes.
