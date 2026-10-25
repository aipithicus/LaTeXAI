# Preparation policy

This directory holds the `prepare` preset for assembling `master.tex`.
The loader validates this configuration. Preparation consumes role actions for
recognized literals, external literal files and transparent comment wrappers,
plus the mouth-emission and provenance settings documented below.
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

2. **Lexical classifications** derived from reader events:
   - `comment_line`: A comment encountered in N state, before a token on that line.
   - `comment_inline`: A comment encountered in M or S state.
   - `line_continuation`: The suppression of the endline by a comment, independent of comment-payload retention.
   - `magic_directive`: A full-line comment containing `!TeX key = value`; this action takes precedence over `comment_line`.

The policy provides a clean, minimal mapping from these inputs to **Pipeline Actions** (`eliminate`, `preserve`, `route_to_sidecar`, `unwrap`, `inline`, `coalesce`).

Lexical categories (`opaque_literal`, `semi_verbatim_block`, etc.) describe how a
span is read. Policy lookup uses its separate `semantic_role`. The reader currently
emits token/skip events and the exact comment-marker span. `MouthEmitter` derives
the classifications and returns an emission decision; the source owner records
mapped pieces, synthetic boundaries, removed extents and metadata. There is no
filesystem I/O in the emitter and no second raw-text comment search.
Supported roles can eliminate/preserve recognized literal regions, inline/preserve
external literal resources, and unwrap/preserve transparent containers. Unimplemented
role actions are reported without silently deleting content. Selecting an experimental
policy does not implement its proposed lossless/prose projection.

An action expresses intent, not proof that a rewrite is valid. The emitter
must preserve established reading behavior, including comment-suppressed newlines,
token boundaries and paragraph tokens. In particular, `coalesce` and `strip` do
not authorize unconditional blank-line or whitespace removal. Literal content,
stored definitions and unresolved effects require their own context checks.

## Executable emission contract

| Field | Supported values | Behavior |
| --- | --- | --- |
| `lexical_events.comment_line` | `eliminate`, `preserve` | Remove payload or keep the comment spelling and its physical terminator. |
| `lexical_events.comment_inline` | `strip_payload`, `preserve` | Remove payload or keep the comment spelling and its physical terminator. |
| `lexical_events.line_continuation` | `preserve` | Preserve the suppression of endline tokens; this does not require preserving every `%` glyph. |
| `lexical_events.magic_directive` | `extract_metadata`, `preserve`, `eliminate` | Capture inert metadata, retain the comment, or remove its payload. |
| `structural_normalization.paragraph_breaks` | `preserve` | Serialize every observed paragraph token as `\par `; repeated tokens are not discarded. |
| `structural_normalization.trailing_whitespace` | `strip` | Drop input_ln tails and ignored whitespace where established by reader events. Required spaces remain. |
| `provenance.emit_ledger` | `true`, `false` | Default for optional ledger output. An explicit `emit_provenance` API argument overrides this value. |
| `provenance.rle_compression` | `true`, `false` | Merge adjacent identity segments, or retain individual emission segments. Text, unit locations, and source accounting are unaffected. |
| `linting.mode` | `off`, `report`, `repair` | Disable lint, report findings (default), or permit explicitly selected checked repairs. |
| `linting.repairs` | List containing `drop_invalid_character`, or empty | Allow-list; empty by default. Each repair still requires its applicability and token/state checks. |

The emitter is applied only to admitted reader events in the master stream.
Captured command headers/bodies, definitions, literals, deferred regions and
separately retained local code keep their existing preservation contracts. This
is not a whole-file lossless mode or permission to normalize protected text.

Removing a comment also removes its swallowed physical endline, rather than
turning it into whitespace: `foo%...` and `foo %...` remain distinct. An explicit
comment marker at file EOF is retained when necessary to suppress a newly exposed
implicit endline. Kept comments without a terminator receive a separately mapped
synthetic newline so an inlined file cannot comment out its caller. Removed payloads
still receive occurrence-aware tombstones; retained marker spans remain copies.

`source_metadata` records `kind`, normalized `key`, untouched trimmed `value`,
`unit_id` and final location status. The linked unit holds the original source and
occurrence. A removed directive normally has an omitted location, not a fabricated
master span. Unknown keys are preserved as data and never select a compiler, run
commands or change output paths. Root discovery independently uses the same parser
for its existing validated `!TeX root` hint; removing a hint from the master does
not disable source-root selection.

The syntax loader still accepts experimental values for inspection, but preparation
rejects `comment_line: route_to_sidecar`, `line_continuation: eliminate`,
`paragraph_breaks: coalesce`, and `trailing_whitespace: preserve` before source reads.
These need additional contracts: a comment sidecar, an explicitly different
interpretation of endlines, proof about paragraph semantics, or physical-line
emission respectively. Errors name both the policy file and setting. The default
paragraph setting is now `preserve`; the former `coalesce` setting was never
implemented and could not safely discard observable `\par` invocations.

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
  paragraph_breaks: <action>          # 'preserve'; 'coalesce' is experimental only
  trailing_whitespace: <action>       # 'strip'; 'preserve' is experimental only

provenance:
  emit_ledger: bool                   # Whether to emit master.provenance.json
  rle_compression: bool               # Whether to merge adjacent identity segments

linting:
  mode: report                       # 'off' | 'report' | 'repair'
  repairs: []                         # Supported: drop_invalid_character
```

See the [bounded lint contract](../../recipes/preparation-lint.md) for repair
eligibility, evidence, output locations and package diagnostics.

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
