# Preparation policy

This directory holds the `prepare` preset for assembling `master.tex`.
The loader validates this configuration. Preparation consumes role actions for
recognized literals, external literal files and transparent comment wrappers.
Alternative policies live under [experimental/](../experimental/README.md).

---

## 1. Principles: Role-Based & Event-Driven Policy

A policy does not maintain hardcoded lists of command names (`\todo`, `\note`, `\comment`) or reimplement TeX execution rules. Instead, it operates strictly over two typed inputs:

1. **Semantic Roles** emitted by the bindings and syntax layer:
   - `author_notes`: Environment blocks intended as notes (`comment.sty`, `\excludecomment`).
   - `editorial_annotation`: Authorial draft annotations (`\todo`, `\note`, `\fxnote`).
   - `dead_conditional`: Inactive conditional branches (`\iftrue` / `\iffalse`).
   - `code_listing`: Verbatim code listings (`verbatim`, `lstlisting`).
   - `code_inline`: Inline code snippets (`\verb`, `\lstinline`).
   - `formatted_code_listing`: Semi-verbatim blocks (`alltt`).
   - `transparent_container`: Non-semantic environment wrappers (`\includecomment`).
   - `wrapped_container`: Environments with boundary hooks (`\specialcomment`);
     preserve until those hooks have been handled.
   - `formatting_container`: Font and styling wrappers (`\textbf`, `\emph`).
   - `external_verbatim`: External verbatim file transclusions (`\verbatiminput`).

2. **Lexical classifications** to be derived from reader events and source context:
   - `comment_line`: Lines containing only `CatCode.COMMENT` (14) and optional leading whitespace.
   - `comment_inline`: Code or prose followed by `%` on the same physical line.
   - `line_continuation`: A trailing `%` suppressing the physical newline whitespace.
   - `magic_directive`: Editor/compiler hints (`% !TeX root = ...`).

The policy provides a clean, minimal mapping from these inputs to **Pipeline Actions** (`eliminate`, `preserve`, `route_to_sidecar`, `unwrap`, `inline`, `coalesce`).

Lexical categories (`opaque_literal`, `semi_verbatim_block`, etc.) describe how a
span is read. Policy lookup uses its separate `semantic_role`. The reader currently
emits token/skip events; it does not directly emit the four classifications above.
The policy loader selects actions; the preparation source owner performs edits.
Supported roles can eliminate/preserve recognized literal regions, inline/preserve
external literal resources, and unwrap/preserve transparent containers. Unimplemented
role actions are reported without silently deleting content. Lexical-event,
normalization and provenance settings remain provisional; the established mouth
emitter and pipeline arguments still own those behaviors. Selecting an experimental
policy does not implement its proposed lossless/prose projection.

An action expresses intent, not proof that a rewrite is valid. The emitter
must preserve established reading behavior, including comment-suppressed newlines,
token boundaries and paragraph tokens. In particular, `coalesce` and `strip` do
not authorize unconditional blank-line or whitespace removal. Literal content,
stored definitions and unresolved effects require their own context checks.

---

## 2. Policy Schema Reference

```yaml
identity:
  name: str                           # Policy identifier (e.g. 'prepare')
  target: str                         # Designation of primary output target
  description: str                    # Concise factual summary

role_actions:
  <semantic_role>: <action>           # 'eliminate' | 'preserve' | 'route_to_sidecar' | 'unwrap' | 'inline' | 'convert_to_markdown'

lexical_events:
  comment_line: <action>              # 'eliminate' | 'preserve' | 'route_to_sidecar'
  comment_inline: <action>            # 'strip_payload' | 'preserve'
  line_continuation: <action>         # 'preserve' | 'eliminate'
  magic_directive: <action>           # 'extract_metadata' | 'preserve' | 'eliminate'

structural_normalization:
  paragraph_breaks: <action>          # 'coalesce' (collapse multiple empty lines to single \par) | 'preserve'
  trailing_whitespace: <action>       # 'strip' (outside verbatim) | 'preserve'

provenance:
  emit_ledger: bool                   # Whether to emit master.provenance.json
  rle_compression: bool               # Whether to use interval RLE compression
```

---

## 3. Loading and validation

Use `load_policy("prepare")` or an explicit policy file path. The previous
`preflight` and `compact` names are removed. Experimental policies cannot be
selected by a short name and are never loaded by default.

The shared YAML loader rejects duplicate keys and non-mapping roots. The policy
loader rejects unknown sections/fields, malformed mappings, invalid actions and
non-boolean provenance flags (including strings such as `"false"`). Omitted fields
other than `identity.name` retain the typed configuration's defaults.
`identity.name` is required and must exactly equal the filename stem, including for
explicit custom or experimental files. New semantic role names are allowed; an
unconfigured role still defaults to `preserve`.
