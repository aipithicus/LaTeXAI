### Formatting Highlights
- **Frontmatter**: Standard `Structural` metadata block with `exchanges: 9`, `sessions: [b509e318]`, and `models: [gemini-3.8-flash]`.
- **Heading Hierarchy**:
  - Each of the 9 user prompts starts with a top-level `# <prompt>` heading.
  - All headings inside the assistant replies have been demoted down (`#` $\to$ `##`, `##` $\to$ `###`, etc.) so that only prompts occupy `#`.
- **Untruncated Content**: Sourced directly from `transcript_full.jsonl` to ensure all detailed code references, file paths, and tables were captured without truncation (48 KB total).
- **Separators**: Standard `---` horizontal rules between conversation turns.


### The Fundamental Separation Criterion

The dividing line between **Initial (Preprocessing / `master.tex`)** and **Deferred (Deep Expansion / Realization)** is governed by a strict operational law:

> **The Preprocessing Phase is a Lexical and Structural Preparation Stage, NOT an Evaluator.**
> * It **MUST** know anything that changes **how characters are read** (CatCodes, line-endings, verbatim boundaries) or **what files/blocks exist in the stream** (inclusions, comment exclusions, conditional compilation).
> * It **MUST NOT** expand ordinary semantic macros or math notation (e.g., `\alpha`, `\KK`, `\xrightarrow`), because expanding them prematurely loses authorial intent, inflates token counts, and destroys downstream math register canonicalization.

---

### The 6 Kinds of Bindings

```
                              TeX Source Stream
                                      │
        ┌─────────────────────────────┴─────────────────────────────┐
        ▼                                                           ▼
 [PHASE 1: INITIAL / PREPROCESSING]                  [PHASE 2: DEFERRED / REALIZATION]
 Handled in PyTeXML to emit clean master.tex         Handled downstream to emit XML / AST / Markdown

 Kind 1: Mouth & Lexical Mutators                    Kind 4: Structural Alignments & Grids
 (catcodes, verb, fancyvrb, listings)                (tikz-cd, amsmath align, nicematrix)

 Kind 2: Boundary & Exclusion Blocks                 Kind 5: Notation Operators & Atoms
 (comment.sty, \input, \include, \if)                (extarrows, stackrel, scalerel, \mathbb)

 Kind 3a: Lexical Definition Factories               Kind 6: Typesetting Furniture
 (\excludecomment, \DefineVerbatimEnvironment)       (\,, \!, \vspace, \Big, \displaystyle)
```

---

### 1. Kind 1: Mouth & Lexical Mutators *(INITIAL — "Hard")*

* **Operational Definition**: Any construct that modifies the **Mouth's reading state**—changing how raw input bytes are converted into tokens (character categories, line endings, escape characters, or whitespace rules).
* **Why it cannot be deferred**: If the reader does not apply these rules immediately, it will tokenize `%` as a comment inside code listings, misparse `\`, or crash on `^^` hex sequences.
* **Examples**:
  - `\makeatletter` / `\makeatother` (`@` transitions between Letter and Other).
  - `expl3` / `\ExplSyntaxOn` (whitespace ignored, `_` and `:` become letters).
  - `verbatim` / `verbatim*` (all special characters become `CatCode.OTHER`, spaces literal).
  - `alltt` (`\`, `{`, `}` remain active; all other punctuation becomes `CatCode.OTHER`).
  - `fancyvrb` (custom `commandchars=\\\{\}`, `commentchar=\%`).
  - `listings` (verbatim with custom inline escape delimiters `escapeinside={(*@}{@*)}`).
* **YAML Schema Requirements**:
  ```yaml
  kind: mouth_mutator
  lexical_state:
    catcode_overrides:
      "@": letter
      "%": other
    whitespace_mode: verbatim # normal | verbatim | ignored
    endline_mode: active       # normal | active | ignored
    escape_delimiters:         # for escapeinside / commandchars
      open: "(*@"
      close: "@*)"
  ```

---

### 2. Kind 2: Structural Inclusions & Exclusion Blocks *(INITIAL — "Hard")*

* **Operational Definition**: Constructs that dictate **stream composition**—splicing external file bytes into the document or dropping bulk spans of source text entirely.
* **Why it cannot be deferred**: Inlining cannot resolve the inclusion DAG if it evaluates phantom `\input{...}` inside dead comments or fails to inline real subfiles.
* **Examples**:
  - Inclusions: `\input{file}`, `\include{file}`, `\subfile{file}`, `\import{dir}{file}`.
  - Exclusions: `\begin{comment} ... \end{comment}` (`comment.sty`), `\begin{versionA} ... \end{versionA}`.
  - Document Boundaries: `\begin{document}`, `\end{document}`.
  - Conditionals: `\iftrue`, `\iffalse`, `\newif`, `\iftoggle`.
* **YAML Schema Requirements**:
  ```yaml
  kind: structural_boundary
  classification: editorial_comment_block # inclusion | editorial_comment_block | transparent_block
  boundary_matcher:
    type: physical_line_exact # physical_line_exact | balanced_delimiter | dynamic_char
    terminator: "\\end{comment}"
    requires_column_zero: true # Victor Eijkhout comment.sty rule
    consume_trailing_newline: true
  action: strip # inline | strip | passthrough | route_sidecar
  ```

---

### 3. Kind 3: Definition & Environment Factories *(HYBRID — "Hard" to "Medium")*

* **Operational Definition**: Meta-commands that **dynamically define new commands or environments** at runtime.
* **The Operational Split**:
  - **Kind 3a (INITIAL / Lexical Factories)**: Commands that register new *Kind 1* or *Kind 2* constructs.
    - *Example*: `\excludecomment{draft}` tells the engine that `\begin{draft}...\end{draft}` is now a comment block.
    - *Example*: `\DefineVerbatimEnvironment{MyCode}{Verbatim}{...}` creates a new verbatim environment.
    - *Action*: **Must be executed during Phase 1** so the reader registers the new boundary matcher.
  - **Kind 3b (DEFERRED / Semantic Factories)**: Standard macro and theorem definitions.
    - *Example*: `\newcommand{\myvec}[1]{\mathbf{#1}}`, `\newtheorem{theorem}{Theorem}`.
    - *Action*: **Deferred**. Keep the definition in `master.tex` and index it in the provenance manifest.
* **YAML Schema Requirements (Kind 3a)**:
  ```yaml
  kind: factory
  factory_target: structural_boundary # or mouth_mutator
  target_kind: editorial_comment_block
  argument_signature:
    name_param: 1
    default_action: strip
  ```

---

### 4. Kind 4: Structural Alignments & 2-D Grids *(DEFERRED — "Medium")*

* **Operational Definition**: Environments that organize standard math or prose into **rows, columns, and graph morphisms**.
* **Why it can be deferred**: Inside `master.tex`, they behave as ordinary balanced TeX blocks (`\begin{...} ... \end{end}`). They do not mutate catcodes (except standard table `&` and `\\`), and do not hide inclusions.
* **Examples**:
  - `tikz-cd` (`\begin{tikzcd} A \arrow[r, "f"] & B \end{tikzcd}`).
  - `nicematrix` (`\begin{pNiceMatrix} ... \end{pNiceMatrix}`).
  - `amsmath` (`align`, `gather`, `bmatrix`, `cases`).
* **Downstream Realization (Phase 2)**:
  - Parses matrix cells and arrow options (`direction`, `labels`, `style`).
  - Emits `<XMArray datameaning="commutative-diagram">` or AST grid nodes.

---

### 5. Kind 5: Notation Operators & Semantic Atoms *(DEFERRED — "Easy")*

* **Operational Definition**: Macros that expand to mathematical symbols, extensible relations, operators, or semantic accents.
* **Why it can be deferred**: Zero impact on reading state or document structure. Keeping them verbatim in `master.tex` allows the downstream P1 quotient to canonicalize them uniformly.
* **Examples**:
  - Extensible arrows: `\xlongequal[under]{over}`, `\xrightarrow{f}` (`extarrows`, `extpfeil`).
  - Stacking: `\stackrel[under]{over}{base}`, `\stackbin`.
  - Sizing/Stretching: `\scalerel*{A}{B}`, `\scalebox`.
  - Font alphabets: `\mathbb{R}`, `\mathcal{F}`, `\boldsymbol{x}`.
* **YAML Schema Requirements (Phase 2)**:
  ```yaml
  kind: math_operator
  role: ARROW # ARROW | RELOP | ADDOP | OPERATOR | ALPHABET
  arguments: "[under]{over}"
  canonical_form: "\\xrightarrow"
  ```

---

### 6. Kind 6: Typesetting Furniture & Layout Hacks *(DEFERRED — "Easy / Trivial")*

* **Operational Definition**: Non-semantic spacing, manual sizing, and visual formatting intended solely for the DVI/PDF printer.
* **Why it can be deferred**: They are pruned or normalized away during the math quotient pass.
* **Examples**:
  - Spacing/Kerning: `\,`, `\!`, `\quad`, `\qquad`, `\hspace{...}`, `\vspace{...}`.
  - Manual sizing: `\big`, `\Big`, `\bigg`, `\Bigg`.
  - Layout: `\displaystyle`, `\centering`, `\clearpage`, `\noindent`.
* **YAML Schema Requirements (Phase 2)**:
  ```yaml
  kind: furniture
  category: spacing # spacing | sizing | display_mode
  action: prune     # prune | normalize | preserve_if_ambiguous
  ```

---

### Summary Checklist for Schema Design

| Kind | Name | Phase | What the YAML Schema Must Declare |
| :---: | :--- | :---: | :--- |
| **1** | **Mouth / Lexical Mutator** | **INITIAL** | `catcode_overrides`, `whitespace_mode`, `escape_delimiters`, `endline_mode` |
| **2** | **Boundary / Exclusion** | **INITIAL** | `boundary_matcher` (line-anchored vs stream), `terminator`, `action` (`strip`/`inline`) |
| **3a** | **Lexical Factory** | **INITIAL** | `factory_target`, argument index where the new environment name is passed |
| **3b** | **Semantic Factory** | **DEFERRED** | Parameter arity, default argument values |
| **4** | **Structural Grid** | **DEFERRED** | Column delimiters (`&`), row delimiters (`\\`), cell parse schema |
| **5** | **Notation Operator** | **DEFERRED** | Mathematical `role`, argument signature, canonical replacement string |
| **6** | **Typesetting Furniture**| **DEFERRED** | Visual category, quotient rule (`prune` vs `keep`) |

This clean split ensures **PyTeXML's initial pass stays lean, fast, and robust**—handling only Kinds 1, 2, and 3a to produce an infallible `master.tex` without getting bogged down in math parsing or semantic expansion.

Viewed DESIGN.md:1-80
Viewed source-span-engine.md:1-80

You have hit on the exact core architectural distinction that separates **clean source preparation** from a **broken regex flattener**:

> **In the early phase, TeX is not evaluated; only the *reading context* is tracked.**
> 
> You only process constructs that **alter the rules of character-to-token translation on the fly**, while **deferring all ordinary macro expansion** until the actual document compilation/realization stage.

---

### 1. The Core Distinction: Reading State vs. Macro Expansion

To see why this distinction is so powerful, compare what happens at the two levels:

| Operation | TeX Mechanism | Action in Early Phase (`master.tex`) | Why? |
| :--- | :--- | :---: | :--- |
| **Reading State Mutation** | **Mouth** (CatCodes, line buffers, token scanner) | **PROCESSED IMMEDIATELY** | If you don't track this on the fly, you cannot even tokenize the next character correctly. `%` might not be a comment; `\` might not be an escape. |
| **Complex Macro Expansion** | **Gullet & Stomach** (Macro replacement, boxes, glue) | **DEFERRED TO REALIZATION** | Expanding `\newcommand{\myop}{\operatorname{Hom}}` or `\alpha` adds zero value to `master.tex`. Leaving them intact preserves authorial intent and allows downstream canonicalization. |

---

### 2. How Environmental Contexts Change Reading "On the Fly"

TeX does not have a single fixed grammar. As the source stream progresses, environments and packages dynamically throw the Mouth into completely different **Reading Regimes**:

```
                       Source Byte Stream
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
 [Zone 1: Standard]      [Zone 2: Opaque]       [Zone 3: Hybrid]
 - Normal CatCodes       - All chars CatCode 12 - Verbatim baseline
 - % is comment          - % is literal text    - Escape windows
 - \input is inclusion   - \input is literal    - (\ still active)
 - \alpha is preserved   - Scanner hunts for    - (listings, alltt)
                           \end{verbatim}
```

#### Zone 1: Standard Reading Context (Prose & Math)
* Standard catcodes: `\` is escape, `{}` are groups, `$` is math, `%` is comment.
* **Early phase rules**:
  - Strip `%` comments up to the newline.
  - Detect and splice inclusions (`\input{file}`, `\include{file}`).
  - **Leave all macros alone**: `\myvec{x}`, `\begin{theorem}`, and `\alpha` are written directly into `master.tex` unchanged.

#### Zone 2: Opaque Literal Context (`verbatim`, `lstlisting`, `minted`)
* Entered via environments that flip almost all characters to `CatCode.OTHER` (12).
* **The "On the Fly" Interaction**:
  - `%` is **NOT** a comment. If a naive preprocessor stripped comments here, it would destroy code samples.
  - `\` is **NOT** an escape character. If the source contains `\input{fake_file.tex}` inside a Python listing, it is **NOT** an inclusion. A naive flattener that looks for `\input` will try to load `fake_file.tex` and crash.
  - Spaces and newlines are **frozen** and literal; whitespace compaction must be suspended.
* **Early phase rules**:
  - The Mouth suspends all macro parsing and comment stripping.
  - It engages a single dedicated **Boundary Matcher** that hunts purely for the terminating string (e.g., `\end{verbatim}`).
  - Emits the entire span into `master.tex` untouched.

#### Zone 3: Escaped & Semi-Verbatim Contexts (`alltt`, `fancyvrb`, `listings`)
* The most nuanced regime: verbatim layout where specific escape portals are punched open.
  - `alltt`: Verbatim spacing and punctuation, but `\`, `{`, and `}` remain active.
  - `fancyvrb`: Verbatim, but `commandchars=\\\{\}` lets `\textit{comment}` run inside the verbatim box.
  - `listings`: Verbatim, but `escapeinside={(*@}{@*)}` allows TeX code inside `(*@ ... @*)`.
* **Early phase rules**:
  - The reader knows that inside the escape delimiter, `\input` or a comment *could* become active again, but outside it, everything is literal.

#### Zone 4: Exclusion Contexts (`comment.sty`, `\excludecomment{draft}`)
* The reader knows this entire block is an editorial discard.
* **Early phase rules**:
  - Discard the entire byte span from `master.tex`.
  - Crucially: **ignore any `\input` directives inside it**, preventing dead files from breaking discovery.

---

### 3. Why This Prevents the Classic "Regex Swamp"

Tools like `latexpand` or naive preprocessors fail because they treat LaTeX as a static string and run regular expressions globally across the file. 

By having your **early phase** focus strictly on:
1. **Tracking Lexical Context** (Mouth state, active profile, boundary matchers), and
2. **Splicing Inclusions** (`\input`, `\include`, `\subfile`),

while **explicitly refusing** to expand ordinary macros, you achieve three things:
1. **Immunity to False Positives**: You never accidentally strip a `%` in code, and never chase a dead `\input` inside a comment or verbatim block.
2. **Lossless Preservation**: `master.tex` retains the exact authorial notation (`\KK`, `\xrightarrow`, `\begin{align}`) ready for the downstream compiler/realization pass.
3. **Parsimonious State**: The preprocessor only needs a lightweight lexical state machine (CatCodes + Boundary Matchers), not a massive macro evaluation engine.