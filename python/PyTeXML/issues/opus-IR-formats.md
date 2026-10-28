XML is doing three jobs at once in LaTeXML, and it's worth separating them before choosing a format:

1. **The logical model:** what the IR is.
2. **The in-memory representation:** what the engine builds and queries while running.
3. **Storage and interchange:** what goes on disk, into receipts, and to consumers.

Most of what feels bulky about XML comes from making one format serve all three. Once they're separate, XML can become one projection among several rather than the IR itself.

## 1. The logical model: an annotation graph over the master text

From your briefs, the IR has to hold:

- a primary document tree with ordered children and mixed content (text runs with inline objects)
- notation trees with per-component morphology
- spans and provenance on every node, sometimes per component, with spelled and expanded locations kept separate
- evidence attributes, typed residue and the basis of each claim
- relations as hyperedges, kept outside the tree
- context records stored as parent plus delta
- several views of the structure that don't all nest: your span brief says outright that diagnostics, resource links and candidate interpretations can cross, and that a laminar family is only one view

A single XML tree can only hold one hierarchy, so crossing structure gets forced into it or pushed out into side records. The model that fits is standoff annotation, from corpus linguistics (TEI standoff, LAF/GrAF). The base text stays immutable, which for you is `master.tex` (your D7). Everything else is typed annotation layers over its spans, plus records for generated content. One layer is the primary document tree; the others can overlap it freely. Your span engine already works this way.

## 2. In memory: red-green trees

Roslyn (C#'s compiler) and rust-analyzer (via the rowan library) use a design that fits your engine:

- **Green nodes** are immutable. They store kind, children and *width*, not absolute offsets. They're hash-consed: identical subtrees are one object.
- **Red nodes** are thin wrappers created on demand, which compute absolute positions and parent pointers as you walk the tree.

For you, that means every expansion of `\R` or of a common author macro yields the same green subtree, stored once. What differs per occurrence, such as the invocation site and the spelled locations, lives in the red layer or in provenance records. That's the same token-interning argument from earlier, applied to IR nodes. Because green nodes are content-addressed, hashing a subtree also gives you deduplication and the identities L3's reuse needs.

## 3. Storage and interchange options

| Format | Fits | Doesn't fit |
| :--- | :--- | :--- |
| XML | Native mixed content, RelaxNG validation, XPath, your Perl-era tooling | Verbose; attributes are only strings; one hierarchy; slow to parse in Python at scale |
| JSON / JSONL | Universal; your jidx tooling; easy to diff | Keys repeat on every record (zstd recovers much of that); mixed content needs arrays of text and nodes; JSON Schema is weaker than RelaxNG |
| CBOR / MessagePack | Compact binary JSON. CBOR has a standard deterministic encoding (RFC 8949), so hashes are stable for receipts | Not human-readable; still record-oriented |
| Protobuf / FlatBuffers / Cap'n Proto | Typed schemas with defined evolution rules; FlatBuffers and Cap'n Proto read without parsing (zero-copy) | Schema compiler in the toolchain; awkward for open-ended evidence attributes |
| Arrow / Parquet | Columnar: span integers and node kinds compress very well; queries across a whole corpus with DuckDB or Polars | Poor for reading or editing one document; mixed content has to be flattened into tables |
| SQLite | One file per paper; random access; R*Tree interval queries; your master index already plans to migrate there | Binary, so goldens need a text dump; concurrent writes need care |
| Custom binary | As compact as you like | You own the tooling, the validation and the evolution forever |

## Recommendation: invent a container schema, not a byte format

- **Per paper:** a bundle containing a manifest (JSON) plus the IR as tables in SQLite. The tables would be:
  - nodes
  - children, with order
  - text runs
  - spans
  - morphology
  - evidence
  - relations
  - contexts

  SQLite's own authors recommend it as an application file format, and it gives you point lookup, interval queries and atomic writes for free. Your G1 bundle work, and the existing manifest and asset conventions, carry over unchanged.
- **Canonical text dump:** a deterministic, sorted JSONL export of the same tables. That's what gets hashed for receipts and diffed in goldens, so the binary is never the thing you compare.
- **Across the corpus:** export the same tables to Parquet for collection-level queries, for example every paper that defines `\mathcal{C}_{++}^{n}`, or every leak event by package, using DuckDB.
- **Projections:** XML, a LaTeXML-compatible view, markdown, and Unicode are all generated from the tables on demand.

One projection target worth adding early is Pandoc's JSON AST. It's a typed JSON document tree with a large ecosystem behind it. Its math elements are TeX strings, which matches your canonical LaTeX projection. Project to it, and Pandoc's writers give you DOCX, HTML, EPUB, Typst and others without extra work.

The custom part is the schema: which tables, which identities, which evidence vocabulary, and how versions evolve. That's where your design work is. The bytes can come from formats that already have tooling.

The doc already draws that line: the index is a published artifact, while scheduling, worker results and retries go in a separate journal keyed by analysis revision and unit IDs. To keep the in-memory pipeline from growing a swamp of intermediate files, I'd add three things.

**1. Make "no ad hoc file I/O" an enforced rule.** Your span brief already says matching, dispatch and span operations never open files for reading; the source store owns reads. Do the same for writes with an artifact store as the only writer. Anything a stage writes must be one of:

- a declared artifact type with a schema version
- written by the stage that owns it
- hashed and listed in a manifest
- reproducible from its inputs, which makes it a cache rather than state

Everything else stays in memory. Then enforce it in tests: a fixture that fails if any stage opens a file for writing outside the store. Without that, intermediate files reappear the first time someone debugs something.

**2. One logical model, with serializers as pure functions.** The index's collections (nodes, coverage, units, contexts, effects, events, label observations, lines) can exist in memory as columnar arrays or dataclasses. Writing them out is then a pure function from those structures to JSONL now, or to SQLite once a consumer needs queries. The doc's order (JSONL first, SQLite when real queries justify it) is right for the index. I'd apply the same rule to the deliverable bundle rather than starting with SQLite as I suggested last time: the consumer decides when the format changes. Canonical JSONL dumps stay the thing that gets hashed and diffed either way.

**3. Fold the engine profile into the revision identities.** Your `analysis_revision` already includes binding and profile digests and entry assumptions. Make the engine profile and TeX Live year explicit fields in it. Master's bytes differ across profiles whenever a profile-dependent branch was pruned, so `document_revision` usually separates them on its own. But a paper with no `\ifpdf` branch can produce byte-identical masters while identity probes still change its reading. Only `analysis_revision` catches that case.

Two smaller observations:

- **Contexts already work like hash-consing.** "Repeated no-change observations reuse the same context ID" is the same idea as the green-tree design. Internally you could key contexts by a content hash of (parent, delta) for deduplication and caching, while exporting the deterministic sequential IDs the doc specifies. External addresses stay simple, and internal reuse gets cheap.
- **Keeping everything in memory sets a per-process ceiling.** Your Perl worst case reached 8.6 GiB on one paper. Running one paper per worker process, as G1 does, frees memory between papers. Within a paper, spilling to disk should happen only at the declared checkpoints, never as an improvised escape hatch when memory runs short.