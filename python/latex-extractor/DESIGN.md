# LaTeX Extractor: Architecture & Design Specification

## 1. Overview & Objective

`latex-extractor` is a headless, deterministic preprocessing, normalization, and replication engine for LaTeX document trees. Its mission is to transform arbitrary multi-file LaTeX projects into self-contained, minimalist replication packages situated in an `extracted/` subdirectory relative to the source project.

The output package guarantees:
- A single canonical `master.tex` root, fully flattened and stripped of dead markup.
- All image assets converted to standard, web-renderable vector SVGs with rewritten `\includegraphics` paths.
- Local style dependencies (`.sty`, `.cls`, `.clo`, `.def`, `.bbx`, `.cbx`) cleaned of comments and excess whitespace.
- An upfront inventory of programmatic/implicit graphics (commutative diagrams, assetless floats, drawings) without compiling.
- A compact, run-length encoded (RLE) source provenance ledger (`master.provenance.json`) providing bidirectional $O(\log N)$ source-to-master tracing.

---

## 2. Design Invariants & Rationale

| Requirement | Traditional Flaw | Extractor Solution |
| :--- | :--- | :--- |
| **Preamble & Tree Flattening** | `latexpand` leaves unhandled conditional branches, duplicate packages, and fails on complex directory trees. | Top-down recursive inliner resolves relative path stacks, replaces `\input`/`\include`, strips redundant preambles, and splices `.bbl` bibliographies directly into `master.tex`. |
| **Executable Preservation** | Crude regex strippers break macros ending in `\foo%` by concatenating tokens into `\foobar`, or strip comments inside `\verb\|%\|`. | Knuth TeX Reader State Machine (TeXbook Ch. 8) emulates States N, M, and S. Trailing comments ending on control words (`\\[a-zA-Z@]+$`) preserve a trailing delimiter; verbatim lines are partitioned and untouched. |
| **Verbatim Safety** | AST-based parsers corrupt custom code environments; sentinel placeholders (`@@VERBATIM_1@@`) mutate line length and fail on nested blocks. | **Non-mutating Line Partitioning**: Document lines are segmented into protected blocks (`verbatim`, `lstlisting`, `minted`, `filecontents`) and complementary lines. Protected lines pass through with 100% byte fidelity. |
| **Asset Standardization** | Diverse formats (`.pdf`, `.png`, `.jpg`, `.eps`) require heterogeneous renderers downstream. | Dual vector/raster SVG conversion: Vector PDFs are parsed into native vector SVGs via PyMuPDF (`fitz`); raster images are converted into standalone base64 SVG wrappers preserving intrinsic `viewBox`. |
| **Implicit Graphics Discovery** | Programmatic drawings (`tikz-cd`, `amscd`, `xy`, assetless floats) are invisible to file-based asset scanners. | **Structural Invariant Probing**: Discovers assetless floats (figures lacking file inclusions), morphism grids (math-mode 2D tables containing arrows), and drawing canvases before compilation without hardcoding package checks. |
| **Source Provenance** | Flattening and stripping destroys line numbers, making it impossible to trace downstream parser errors back to original source files. | **Compact RLE Provenance Ledger**: String-pooled source filenames and integer-matrix contiguous run compression deliver 6x–8x space reduction while guaranteeing $O(\log N)$ bidirectional tracing. |

---

## 3. Pipeline Architecture

The extraction process executes across 9 sequential phases:

```
[Input Project Directory]
          │
          ├── Phase 1: Static Preflight & Asset Characterization (preflight.py)
          │     ├── Root document discovery & toolchain probe
          │     ├── Active/dormant image asset inventory
          │     └── Structural implicit graphics detection (floats, CD, canvas)
          │
          ├── Phase 2: Recursive Inlining & Provenance Seeding (inliner.py)
          │     ├── Path-stack tracking (\input, \include, \subimport)
          │     └── Bibliography splicing (.bbl -> thebibliography)
          │
          ├── Phase 3: Dead Code & Conditional Branch Pruning (pruner.py)
          │     ├── \iffalse ... \fi elimination
          │     ├── Draft macro dropping (\todo, \missingfigure)
          │     └── Tombstone registration
          │
          ├── Phase 4: Knuth Reader Normalization (normalizer.py)
          │     ├── Line partitioning (Protected vs. Complementary)
          │     ├── Universal LF, Unicode NFC, invisible gremlin scrubbing
          │     ├── Knuth State N leading space swallowing
          │     ├── Inline span protection (\verb, \url)
          │     ├── Macro boundary safety (\\[a-zA-Z@]+$ preservation)
          │     └── Paragraph break capping (max-blank-1: \n{2,} -> \n)
          │
          ├── Phase 5: Image Conversion & Path Rewriting (converter.py)
          │     ├── Vector PDF -> native SVG (PyMuPDF)
          │     ├── Raster PNG/JPG -> SVG wrapper
          │     └── Rewrite \includegraphics paths across SourceLine objects
          │
          ├── Phase 6: Compact Provenance Ledger Construction (provenance.py)
          │     ├── RLE integer-run compression
          │     └── master.provenance.json emission
          │
          ├── Phase 7: Local Dependency Sanitization (pipeline.py)
          │     ├── Copy active local .sty, .cls, .clo, .def, .bbx, .cbx
          │     └── Apply knuth_normalize to copies (strip comments & dead spacing)
          │
          ├── Phase 8: Standard master.tex Emission (pipeline.py)
          │     └── Write cleaned, flattened master.tex to extracted/
          │
          └── Phase 9: Metadata & Inventory Sidecar Emission (pipeline.py)
                └── Write manifest.json to extracted/
```

---

## 4. Component Details

### 4.1. `preflight.py` — Static Preflight & Structural Probing
- **Root Document Discovery**: Scores candidacy via `\documentclass` and `\begin{document}` occurrences; breaks ties via reverse correlation probing across disk files.
- **Implicit Graphics Detection**: Employs structural invariants rather than package whitelists:
  - *Assetless Floats*: `figure` environments lacking `\includegraphics` or input directives. Ignores `\newenvironment` definition templates.
  - *Morphism Grids*: Math environments containing 2D alignment matrices (`&`, `\\`) paired with directional morphism arrows (`\to`, `\rightarrow`, `\dar`, `\arrow`).
  - *Specialized Canvases*: Recognized drawing environments (`tikzpicture`, `picture`, `pgfpicture`, `circuitikz`, `forest`, `bytefield`).

### 4.2. `inliner.py` — AST-Free Recursive Inliner
- Maintains a working directory stack to resolve nested `\input`, `\include`, `\import`, and `\subimport` paths.
- Strips redundant nested preambles (`\documentclass`, `\begin{document}`, `\end{document}`).
- Slices and splices precompiled `.bbl` files directly in place of `\bibliography{...}`, converting external bibliography lookups into self-contained `\begin{thebibliography}` blocks.
- Emits each line as a `SourceLine` containing `(text, src_file, src_line, op)`.

### 4.3. `pruner.py` — Dead Code Pruning
- Evaluates static conditional branches (dropping `\iffalse ... \fi` blocks while preserving `\iftrue`).
- Drops configurable draft/annotation commands (`\todo`, `\annot`, `\missingfigure`).
- Records every dropped line in a `Tombstone` record tracking original file, line number, operation, and reason.

### 4.4. `normalizer.py` — Knuth Reader State Machine
- **Protected Line Partitioning**: Identifies boundary lines for verbatim/code environments (`verbatim`, `lstlisting`, `minted`, `alltt`, `filecontents`). These lines bypass normalization completely.
- **Complementary Line Normalization**:
  - Normalizes line endings to LF (`\r\n|\r|\x0B|\x0C|\x85|\u2028|\u2029 -> \n`).
  - Cleans zero-width spaces, BOM, and word-joiners (`[\ufeff\u200b\u2060]`).
  - Emulates Knuth State N: following a comment-only line or stripped trailing comment, leading indentation on subsequent lines is swallowed.
  - Inline span preservation: Protected regex patterns (`\verb|...|`, `\url{...}`) prevent comment parsing or space compaction on inline verbs.
  - Trailing comment removal: Inspects preceding characters for odd counts of `\`. If the preceding token is a control sequence ending in letters or `@` (`r"\\[a-zA-Z@]+$"`), a space is preserved to prevent token collision.
  - **`max-blank-1` Paragraph Capping**: Enforces reposnapshot semantics (`consecutive_blanks <= 1`), collapsing multi-line blank gaps to a single `\n\n` paragraph break outside protected blocks.

### 4.5. `converter.py` — Vector & Raster SVG Normalization
- Standardizes all active graphics assets into standalone `.svg` files inside `extracted/`:
  - Vector PDFs: Extracted via PyMuPDF (`page.get_svg_image()`).
  - Raster Images (PNG, JPG, TIFF, WebP): Wrapped inside a standalone SVG document using `<image href="data:image/...;base64,..."/>` with an exact pixel `viewBox`.
- Rewrites `\includegraphics[...]{filename}` targets in `SourceLine` objects to reference the newly generated `.svg` assets.

### 4.6. `provenance.py` — Compact RLE Provenance Ledger
Serializes document provenance to `master.provenance.json`.

- **Schema**:
  ```json
  {
    "sources": ["main.tex", "sections/intro.tex", "refs.bbl"],
    "runs": [
      [1, 0, 1, 15, 0],
      [16, 1, 1, 42, 1]
    ],
    "tombstones": [
      {"src_file": "main.tex", "start_line": 16, "end_line": 20, "op": "PRUNE_IF_FALSE", "reason": "Dead conditional"}
    ]
  }
  ```
- **Run Tuple**: `[master_start, file_id, src_start, length, op_id]`
  - Encodes continuous blocks of unmodified or transformed lines as a single integer vector.
  - Reduces provenance metadata size by 6x to 8x compared to raw line arrays.
- **Lookup Performance**:
  - `resolve_master_line(master_line)`: $O(\log N)$ binary search over runs returning exact source file and original line.
  - `resolve_source_line(file, line)`: Forward lookup returning target `master_line` or the corresponding `Tombstone` reason explaining why the line was pruned.

---

## 5. Output Replication Package Layout

```
<project_dir>/extracted/
├── master.tex                 # Self-contained, Knuth-normalized LaTeX entrypoint
├── master.provenance.json     # Bidirectional RLE source provenance map
├── manifest.json              # Preflight discovery manifest & implicit graphics inventory
├── neurips_2024.sty           # Cleaned local style dependency (comments & excess blanks stripped)
├── fig1.svg                   # Converted vector/raster image assets
└── fig2.svg
```

---

## 6. Verification & Invariants

1. **Compilation Preservation**: Validated against reference oracles (Tectonic / PDF engine). Layout, page count, and font geometries remain invariant under normalization.
2. **Replication Self-Sufficiency**: The `extracted/` directory contains all active styles, images, and bibliography items required to compile independently of external parent directories.
3. **Cleaned Local Packages**: Local style files (`.sty`, `.cls`) have author comments, license blocks, and blank line runs stripped while retaining 100% of macro signatures and catcode conventions.
