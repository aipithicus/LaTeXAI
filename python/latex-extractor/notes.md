normalization/lexical rewrites of literal glyphs, bindings capture lexical spelling naturally already but sometimes there are literal glyphs in source files

deduping in various respects, including bibliographic entries. also, canonical ordinals with 1-indexing e.g. bibliographies are collected and counted and main body pointers are rewritten to standard 1,2,3 etc to remove author idiosynchracies. correspondences should be 1-to-1 mappings between source references/citations and canonical entries

bindings, lib-ctan etc

LaTeX’s UTF-8 definitions map U+FEFF to \ifhmode\nobreak\fi, for example. That has a layout effect without printing a glyph. Your canonical projection can discard that effect after interpretation, while an optional presentation sidecar could retain it.

Full TeX interpretation, BibLaTeX adaptation, and contextual repair remain future work.

1. Context-aware inlining and pruning across comments, verbatim, definitions, and conditionals.
2. Correct emitted-span provenance. Merely correcting the ledger’s total line count would leave its mappings wrong.
3. Dependency closure and reliable active/dormant classification.
4. General whitespace and package normalization.
5. Asset resolution involving search paths, multiple PDF pages, and filename collisions.

a shared TeX token reader with N/M/S states and explicit catcode handling, then AST structure and lint/repair. General parser correctness and precise provenance remain deferred.

What remains is the broader correctness work: shared lexical context for comments, literals and definitions; the complete reader-state whitespace algorithm; more reliable inclusion/dependency handling; accurate emitted-source provenance; BibLaTeX support; and lint/repair. Those include known bugs, so this is completion of the selected batch, not a claim that the extractor is generally robust.
The next parser work should enable more normalization with better-established boundaries.
