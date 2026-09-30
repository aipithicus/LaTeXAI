# Pipeline Policy Architecture

This directory defines the operational policies that govern how LaTeX source code, tokens, spans, and comments are transformed during extraction, preprocessing, and downstream emission.

---

## 1. Principles: Role-Based & Event-Driven Policy

A policy does not maintain hardcoded lists of command names (`\todo`, `\note`, `\comment`) or reimplement TeX execution rules. Instead, it operates strictly over two typed inputs:

1. **Semantic Roles** emitted by the bindings and syntax layer:
   - `author_notes`: Environment blocks intended as notes (`comment.sty`, `\excludecomment`).
   - `editorial_annotation`: Authorial draft annotations (`\todo`, `\note`, `\fxnote`).
   - `dead_conditional`: Inactive conditional branches (`\iftrue` / `\iffalse`).
   - `opaque_literal`: Verbatim code listings (`verbatim`, `lstlisting`).
   - `code_inline`: Inline code snippets (`\verb`, `\lstinline`).
   - `semi_verbatim`: Semi-verbatim blocks (`alltt`).
   - `transparent_container`: Non-semantic environment wrappers (`\includecomment`).
   - `formatting_container`: Font and styling wrappers (`\textbf`, `\emph`).
   - `external_verbatim`: External verbatim file transclusions (`\verbatiminput`).

2. **Lexical Events** emitted by the reader (`tex_reader.py`):
   - `comment_line`: Lines containing only `CatCode.COMMENT` (14) and optional leading whitespace.
   - `comment_inline`: Code or prose followed by `%` on the same physical line.
   - `line_continuation`: A trailing `%` suppressing the physical newline whitespace.
   - `magic_directive`: Editor/compiler hints (`% !TeX root = ...`).

The policy provides a clean, minimal mapping from these inputs to **Pipeline Actions** (`eliminate`, `preserve`, `route_to_sidecar`, `unwrap`, `inline`, `coalesce`).

---

## 2. Policy Schema Reference

```yaml
identity:
  name: str                           # Policy identifier (e.g. 'preflight', 'lossless')
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

## 3. Standard Policy Profiles

| Policy File | Intended Role | Author Notes & Annotations | Lexical Comments | Paragraph Breaks | Formatting Containers |
| ----------- | ------------- | -------------------------- | ---------------- | ---------------- | --------------------- |
| `preflight.yaml` | Primary extraction (compiles `master.tex`) | `eliminate` | `comment_line: eliminate`<br>`comment_inline: strip_payload` | `coalesce` (max 1 `\par`) | `preserve` |
| `lossless.yaml` | Archival, fidelity checking, roundtripping | `route_to_sidecar` | `preserve` | `preserve` (exact) | `preserve` |
| `prose_extraction.yaml` | NLP, RAG, semantic text indexing | `eliminate` | `eliminate` | `coalesce` | `unwrap` (reveals raw prose) |
