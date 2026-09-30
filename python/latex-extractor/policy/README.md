# Pipeline Policy Architecture

This directory defines the operational policies that govern how LaTeX source code, tokens, spans, and comments are transformed during extraction, preprocessing, and downstream emission.

---

## 1. Separation of Concerns: The Four-Layer Stack

The extraction architecture maintains a strict unidirectional separation between lexical reading, declarative knowledge, operational policy, and emission:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Lexical Reader (`tex_reader.py`)                                    │
│    - TeX82 state transitions (N, M, S) and catcode evaluation          │
│    - Emits tokens, source spans, and lexical event streams             │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
┌────────────────────────────────────▼───────────────────────────────────┐
│ 2. Bound Knowledge (`bindings/**`)                                     │
│    - Authoritative syntax, arities, delimiters, and catcode overrides  │
│    - Categorizes constructs into declarative `span_classification`     │
│    - Pure comprehension: NO pipeline actions or pruning flags          │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
┌────────────────────────────────────▼───────────────────────────────────┐
│ 3. Pipeline Policy (`policy/**`)                                       │
│    - Operational rules: what to prune, keep, unwrap, inline, or route  │
│    - Maps declarative span categories to concrete pipeline actions     │
│    - Decides whitespace compaction, macro pruning, and comment rules   │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
┌────────────────────────────────────▼───────────────────────────────────┐
│ 4. Execution & Emission (`pipeline.py`, `normalizer.py`, emitter)       │
│    - Applies the selected policy to the classified token/span stream   │
│    - Emits transformed master LaTeX, sidecar ledgers, and provenance   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Policy Schema Reference

A policy file is a declarative YAML specification containing the following sections:

### `identity`
Metadata identifying the policy and its designated pipeline target.
* `name`: Identifier of the policy (e.g. `compact`, `lossless`, `arxiv_submission`).
* `version`: Schema version string.
* `target_pipeline`: Intended pipeline role (`compact_preflight`, `archival_preservation`, `publication_package`, `nlp_extraction`).
* `description`: Terse factual description of the policy's objective.

### `span_actions`
Maps declarative `span_classification.category` tags emitted by bindings and literal profiles to operational actions:
* `opaque_literal` (e.g. `verbatim`, `lstlisting`):
  * `preserve_immutable`: Retain raw source characters verbatim without token rewriting or whitespace normalization.
* `opaque_inline_literal` (e.g. `\verb`, `\lstinline`):
  * `preserve_immutable`: Retain verbatim inline content unchanged.
* `editorial_comment_block` (e.g. `\begin{comment}...\end{comment}`):
  * `delete_span`: Strip the environment delimiters and body entirely. Emits a tombstone.
  * `route_to_sidecar`: Extract comment text and source offsets into a metadata sidecar (`editorial_notes.jsonl`).
  * `preserve_span`: Keep the environment intact.
* `transparent_block` (e.g. `\includecomment` targets):
  * `unwrap_delimiters`: Retain inner content, removing opening and closing commands.
  * `preserve_span`: Keep delimiters.
* `wrapped_block` (e.g. `\specialcomment` targets):
  * `execute_boundary_hooks`: Expand or insert configured before/after hook code.
* `semi_verbatim_block` (e.g. `alltt`):
  * `preserve_whitespace_allow_macro_expansion`: Obey lines and spaces, but expand active commands and process grouping.
* `external_verbatim_resource` (e.g. `\verbatiminput`, `\lstinputlisting`):
  * `inline_literal_file`: Read external file content and inline it as an immutable verbatim block.
  * `preserve_reference`: Leave file inclusion command unchanged.

### `lexical_comments`
Directives for handling `CatCode.COMMENT` (14) / `EventKind.COMMENT` across different lexical contexts:
* `full_line_comment` (lines containing only a `%` comment and optional leading whitespace):
  * `drop_line`: Discard the line completely. Emits a tombstone.
  * `preserve_line`: Retain the comment line intact.
  * `route_to_sidecar`: Save comment text and line provenance to sidecar.
* `inline_comment` (prose or code followed by `%` on the same physical line):
  * `strip_payload_preserve_boundary`: Remove `%` and trailing comment characters, ensuring adjacent tokens across subsequent lines do not accidentally fuse.
  * `preserve_comment`: Retain `%` and trailing text.
* `line_continuation` (a `%` immediately trailing non-whitespace code, used to prevent TeX from inserting an inter-word space at the newline):
  * `preserve_continuation_marker`: Keep the `%` character at end of line to maintain exact lexical token separation.
  * `drop`: Discard `%` (caution: may insert unwanted spaces during TeX tokenization).
* `magic_comments` (tool directives such as `% !TeX root = ...` or `% !TEX TS-program = ...`):
  * `parse_metadata_then_drop`: Extract root/compiler metadata into pipeline manifest, then drop from output.
  * `preserve_line`: Retain in source.

### `whitespace_rules`
Controls line endings, spacing, and paragraph normalization:
* `max_consecutive_blank_lines`: Maximum allowable consecutive empty lines outside verbatim environments. (e.g., `1` collapses multiple blank lines to a single empty line representing one `\par`). Set to `null` to disable collapsing.
* `strip_trailing_spaces`: Whether to strip ASCII space and tab characters preceding physical newlines on normal lines. (Always disabled inside `opaque_literal`).
* `swallow_first_verbatim_newline`: Whether to discard the initial newline immediately following `\begin{verbatim}` in accordance with LaTeX kernel rules.

### `macro_pruning`
Rules for eliminating author draft macros and annotations:
* `drop_commands`: List of macro names to delete along with their mandatory and optional arguments (`todo`, `todonotes`, `note`, `comment`, `draft`).
* `unwrap_commands`: List of macros whose wrapper is stripped while preserving inner mandatory content (`textbf`, `textit`, `emph`, `textcolor`).

### `conditional_evaluation`
Rules for static conditional trees:
* `simplify_static_branches`: Evaluate `\iftrue` / `\iffalse` conditionals and prune dead branches.
* `unknown_conditionals`: Handling of non-static conditionals (`\ifx`, `\ifdim`). Default: `preserve`.

### `provenance`
* `emit_ledger`: Boolean indicating whether to write `master.provenance.json`.
* `tombstone_categories`: Mapping of pruning/stripping operations to tombstone reason tags (`PRUNED_SEMANTIC`, `STRIPPED_COMMENT`, `NORMALIZED_WHITESPACE`).

---

## 3. Standard Policy Profiles

| Policy File | Intended Use Case | Editorial Comments | Lexical Comments | Blank Lines | Conditionals |
| ----------- | ----------------- | ------------------ | ---------------- | ----------- | ------------ |
| `preflight.yaml` | Primary preflight & extraction policy (produces `master.tex`) | `delete_span` | Strip payload / drop full-line | Max 1 (`\par`) | Simplify static |
| `lossless.yaml` | Archival, fidelity checking, roundtripping | `route_to_sidecar` | Preserve exact | Unbounded (`null`) | Preserve all |
| `prose_extraction.yaml` | Semantic text search, embedding, NLP | `delete_span` | Discard all | Max 1 | Simplify static |
