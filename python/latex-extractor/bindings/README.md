# Bindings Taxonomy & Organization

This directory provides the authoritative declarative specifications for LaTeX constructs, environments, and packages consumed by the preprocessor and downstream IR generators.

## 1. Architectural Taxonomy

Bindings are strictly partitioned into two tiers to prevent engine primitives and CTAN packages from mixing concerns:

```
python/latex-extractor/bindings/
├── README.md
├── engine/                       # Core LaTeX 2e / TeX primitives (always active)
│   ├── core_latex.yaml           # Inclusions, grouping, catcode mutators, conditionals
│   └── verbatim.yaml             # Authoritative kernel verbatim & \verb specification
└── packages/                     # Activated dynamically via \usepackage / \RequirePackage
    ├── alltt.yaml                # Semi-verbatim environment (\ and { } retained)
    ├── comment.yaml              # Victor Eijkhout's selective exclusion/inclusion engine
    ├── fancyvrb.yaml             # Configurable verbatim & \DefineVerbatimEnvironment
    ├── listings.yaml             # Syntax-highlighted code blocks & \lstinline
    └── verbatim.yaml             # Rainer Schöpf's \verbatiminput extension
```

---

## 2. Tier Details

### `engine/` (Format Primitives)
Constructs defined by the base TeX engine (`tex.web`) or the LaTeX 2e format (`latex.ltx`).
* **Active status:** Always active; loaded automatically at document initialization.
* **Examples:** `\verb`, `verbatim`, `verbatim*`, `\makeatletter`, `\begingroup`, `\input`, `\iftrue`.

### `packages/` (CTAN Extensions)
Constructs contributed by specific `.sty` packages or `.cls` document classes.
* **Active status:** Dormant by default; registered dynamically when `\usepackage{<name>}` or `\RequirePackage{<name>}` is traversed.
* **Separation of concerns:** 
  * `comment.sty` owns `\begin{comment}` and `\excludecomment`.
  * `verbatim.sty` extends the engine with `\verbatiminput`.
  * `fancyvrb.sty` introduces definition factories like `\DefineVerbatimEnvironment`.

---

## 3. Schema Contract: Separation of Concerns

Bindings represent **pure declarative comprehension**—they answer *what is this construct syntactically, what are its lexical rules, and what kind of span does it produce?*

Bindings intentionally contain:
* **No operational policies** (whether comments or draft blocks should be stripped, kept, or routed to sidecars is governed by `policy/`).
* **No downstream projection configurations** (how constructs are mapped into XML elements, AST nodes, or attributes is governed by the mirror layer in `capture/`).

Every binding file defines:
* How characters are converted into tokens (catcodes and reader state transitions).
* Lexical overrides (e.g. `%` as `CatCode.OTHER` vs `CatCode.COMMENT`).
* Whitespace and newline behavior (verbatim spaces, `obey_lines`, `swallow_first_newline`).
* Delimiters, argument arities, and termination conditions.
* Declarative **span classification** tags:
  * `opaque_literal` (e.g. `verbatim`, `lstlisting`): immutable code listings where no TeX syntax applies.
  * `opaque_inline_literal` (e.g. `\verb`, `\lstinline`): single-line verbatim spans delimited by dynamic characters.
  * `editorial_comment_block` (e.g. `comment`): author/editorial notes blocks defined by packages or factories.
  * `semi_verbatim_block` (e.g. `alltt`): verbatim layout where commands and grouping remain active.
  * `transparent_block` (e.g. `\includecomment`): content whose outer environment boundary is non-semantic.
  * `external_verbatim_resource` (e.g. `\verbatiminput`): external file transclusions in literal mode.

Downstream XML IR projections for these bindings live under mirror paths in `capture/` (e.g. `capture/engine/verbatim.yaml`, `capture/packages/listings.yaml`).
