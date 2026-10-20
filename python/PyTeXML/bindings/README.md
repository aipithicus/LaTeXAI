# Bindings Taxonomy & Organization

This directory holds declarative reading contracts for the Python binding resolver.
The preparation pipeline does not yet dispatch through these contracts. Downstream
interpretation and XML capture remain separate consumers under development.

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
* **Active status:** Dormant by default; the caller activates a known binding with
  `BindingResolver.load_package()`. Recognizing package declarations in source is
  the future dispatcher's responsibility. Later first-time activations take
  precedence; requesting an already active package does not reorder it.
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
* Whitespace and newline behavior (verbatim spaces, active line endings, and
  paragraph handling). Suppressing the first paragraph is not permission to
  delete a source newline during lexical reading.
* Delimiters, argument arities, and termination conditions.
* Declarative **span classification** tags:
  * `opaque_literal` (e.g. `verbatim`, `lstlisting`): immutable code listings where no TeX syntax applies.
  * `opaque_inline_literal` (e.g. `\verb`, `\lstinline`): single-line verbatim spans delimited by dynamic characters.
  * `editorial_comment_block` (e.g. `comment`): author/editorial notes blocks defined by packages or factories.
  * `semi_verbatim_block` (e.g. `alltt`): verbatim layout where commands and grouping remain active.
  * `transparent_block` (e.g. `\includecomment`): content whose outer environment boundary is non-semantic.
  * `external_verbatim_resource` (e.g. `\verbatiminput`): external file transclusions in literal mode.

Downstream XML IR projections for these bindings live under mirror paths in `capture/` (e.g. `capture/engine/verbatim.yaml`, `capture/packages/listings.yaml`).

## 4. Resolver contract

`binding_resolver.py` loads YAML once per resolver and resolves occurrences in
memory. [Mouth profiles](../profiles/mouth/README.md) contain the authoritative
regex character classes and baseline reading parameters. There is no legacy
profile-file fallback. Resolution composes inherited profile layers, the owning
binding's lexical settings, construct settings, and supported option effects, in
that order. It returns data containing immutable compiled catcode layers,
reader parameters, argument grammar, termination rules, source-capture mechanics,
and classification. Lexical categories such as `opaque_literal` are distinct from
policy roles such as `code_listing` and `external_verbatim`.

Supported `commandchars` and `commentchar` values produce concrete category
assignments. Listings escape options produce explicit delimiter plans; they are
not global category changes. Unknown options, unsupported code hooks, and combined
interpolation modes return `UnresolvedBindingResult`. Only options explicitly
classified by the owning binding can pass through as non-reading metadata.

Command lookup includes active package bindings. Dynamic `\catcode` needs scanned
arguments; configuration commands and definition factories need execution support.
These return explicit unresolved results rather than successful empty profiles.
There is no macro expansion or native-engine fallback here.

`resolver.new_context("latex_ascii")` constructs a context from the loaded YAML
baseline. `ReaderContext` applies immediate local effects and restores scoped catcodes,
`endlinechar`, and expl3 saved state. Repeated `\ExplSyntaxOn` reapplies its
assignments while preserving the saved baseline. The caller owns execution mode,
literal scope, argument/body scanning, and synchronization of a live reader's
`endline_char`. Interpolation plans require a literal dispatcher and cannot be
applied as ordinary context mutations. Terminator metadata is not a scanner.
