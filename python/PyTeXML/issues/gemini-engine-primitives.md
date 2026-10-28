# im trying to figure out what are the essential primitives in the latex engine that would allow me to read and interpret source and packages. like all of the packages are comprehended by the engine and admit new capabilities. what is that underlying core. in pytexml i already have a knuthian reader but it stops short of expansion at the moment. also, i'm gathering some snippets of conersations regarding engine primitives here as a starting point[engine-primitives.md](file;file:///d%3A/aipithicus/LaTeXAI/python/PyTeXML/issues/engine-primitives.md) 

Viewed engine-primitives.md:1-118
Listed directory PyTeXML
Listed directory issues
Viewed opus-planning-interp-engine.md:1-210
Viewed opus-next-steps.md:1-49
Listed directory src
Listed directory reading
Viewed tex_reader.py:1-120

To understand what underlying engine core allows you to read, expand, and interpret LaTeX documents and packages, it helps to distinguish **what TeX does to compute layout** versus **what TeX does to compute meaning and syntax**.

In TeX82, the engine has three traditional processing stages:
1. **The Mouth** (Lexical Reader): reads characters, manages category codes (0–15), handles line-ends and state transitions ($N \to M \to S$), and outputs a stream of raw `Token`s. *(This is what [tex_reader.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/tex_reader.py) already implements.)*
2. **The Gullet** (Expansion Engine): takes tokens from the input stream, expands macros, resolves conditionals, processes `\csname`, and replaces tokens recursively until a non-expandable primitive or character reaches the stomach.
3. **The Stomach** (Execution & Typesetting): executes assignments (`\def`, `\let`, registers), maintains the scoped meaning table, and (ordinarily) builds boxes, calculates glue, breaks paragraphs into lines, and computes page breaks.

For a semantic engine like PyTeXML, **you need the Gullet and the state-management half of the Stomach, while completely discarding the typesetting half**.

Here is the essential breakdown of the primitives, subsystems, and architectural boundaries required to build that core.

---

### 1. The Gullet: Essential Expansion Primitives

The Gullet is a purely functional stream-rewriting engine. It receives tokens from an **input stack** (files, macro argument lists, and token lists) and pushes expanded tokens back onto the stack.

To run packages and author definitions, the Gullet requires around **12 foundational expansion primitives**:

| Primitive Category | TeX Primitives | Engine Responsibility |
| :--- | :--- | :--- |
| **Token Lookahead & Order** | `\expandafter`, `\noexpand` | Postpones the expansion of the next token while expanding the subsequent one once; suppresses expansion of the next token. Essential for all macro meta-programming. |
| **Name Construction** | `\csname`, `\endcsname` | Expands enclosed tokens until `\endcsname`, converts the string into a control sequence token, and looks up its current meaning in the symbol table (defaulting to `\relax` if undefined). |
| **Branching & Conditionals** | `\if`, `\ifcat`, `\ifx`, `\ifnum`, `\ifdim`, `\ifdefined`, `\ifcsname`, `\else`, `\fi`, `\or` | Evaluates conditions (token equivalence via `\ifx`, character catcodes, integer comparisons). Drops the non-taken branch by scanning and matching nested `\if ... \fi` pairs. |
| **Token Stringification & Reflection** | `\string`, `\the`, `\number`, `\detokenize`, `\unexpanded` | Converts a token or register value into a sequence of catcode 10/12 characters. `\the` extracts register values, counter values, or token lists. |
| **Macro Expansion Mechanics** | Macro body substitution with **delimited parameter matching** | TeX parameter parsing: matching not just standard brace groups (`#1`), but literal delimiters (`\def\split#1,#2;{...}`) and preserving grouping rules. |
| **Protection (e-TeX)** | `\protected` | Marks a macro so it is not expanded in expansion-only contexts (like `\edef` or `\write`). |

> **Why you need delimited arguments:** Packages do not use simple regexes or AST node unpackers; they parse complex syntax using TeX's native delimited argument matching (e.g. scanning until a comma, semicolon, space, or special delimiter token). Without delimited parameter parsing in your macro expander, even basic kernel and package utilities (`\@ifnextchar`, `\@for`, keyval parsers) immediately break.

---

### 2. The Upper Stomach: State, Meanings, and Scoping

The Gullet cannot operate in a vacuum because macro expansion depends on the **current meaning** of tokens, and that meaning changes over time. The upper stomach manages the dictionary and memory registers:

1. **The Meaning Table (Dictionary):**
   - Every control sequence or active character points to a `Meaning` (Macro, Primitive, Register, Chardef, or Binding).
   - `\let\a=\b`: Copies the current meaning of `\b` to `\a`.
   - `\futurelet\cs\tok1\tok2`: Inspects lookahead; sets `\cs` to the meaning of the token immediately following `\tok2` without consuming it. (Almost every optional argument scanner `[...]` in LaTeX rests on `\futurelet`).
   - `\chardef`, `\mathchardef`: Binds a control sequence to a numeric character code or 15-bit math code.

2. **Scoping and the Stack:**
   - Grouping: `{ ... }` (catcode 1/2) and `\begingroup ... \endgroup`.
   - When exiting a group, all local assignments (meanings, catcode changes, register values) must revert to their previous values.
   - `\global`, `\gdef`, `\xdef`: Overrides the local scope to update the global baseline.
   - `\aftergroup\token`: Stashes a token to be injected into the stream immediately after the enclosing group ends.

3. **Registers and Arithmetic:**
   - Integer registers (`\count`, `\newcount`, `\advance`, `\multiply`, `\divide`, `\numexpr`).
   - Packages constantly use integer registers to track state, loop over lists, and evaluate boolean flags (`\newif`).

4. **Dynamic Catcode Changes:**
   - `\catcode\char=<n>`, `\endlinechar=<n>`.
   - Packages like `verbatim`, `listings`, `url`, `amsmath`, and `expl3` dynamically alter catcodes (e.g. making `_` or `@` a letter, or making backslash inactive) while ingesting content.
   - The token reader (mouth) must listen to catcode updates performed by the interpreter.

---

### 3. The Quantity Scanners (The Sink Requirement)

As noted in [engine-primitives.md](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/issues/engine-primitives.md), TeX documents are littered with low-level typesetting primitives: `\hskip 3pt plus 1fil`, `\kern -0.5em`, `\rule{1cm}{2pt}`, `\hbox to 20pt{...}`.

While you don't calculate pixels, boxes, or glyph metrics, **you cannot simply ignore or drop them with a regex**. You must implement **TeX's exact quantity grammar scanners**:
- **`<number>` scanner:** Handles decimal integers, octal (`'177`), hex (`"FF`), character codes (`\`A`), and register references.
- **`<dimen>` and `<glue>` scanner:** Scans a number followed by TeX units (`pt`, `mm`, `cm`, `in`, `em`, `ex`, `bp`, `dd`, `pc`, `sp`) and optional `plus <dimen>` / `minus <dimen>` stretch/shrink factors.
- **Keyword scanner:** Scans exact keyword tokens like `to`, `spread`, `plus`, `minus`, `width`, `height`, `depth`.

**Why this matters:** When the engine encounters a primitive sink like `\hskip`, it invokes the glue scanner. The scanner consumes the exact tokens defining the dimension, ensuring that subsequent text tokens are not erroneously swallowed or treated as stray document text.

---

### 4. The Critical Boundary: TeX Primitives vs. Declarators

The notes in [engine-primitives.md](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/issues/engine-primitives.md#L107-L135) make a vital observation:

$$\text{TeX Primitives} \neq \text{Semantic Primitives}$$

If you lower a package down to raw TeX82 primitives, **you destroy meaning**:
- `\leq` becomes `\mathchardef\leq="3214` (Font Family 2, Slot `0x14`).
- `\mathbb{R}` becomes a font family switch to `msb` and a glyph output.
- `\newtheorem{lemma}{Lemma}` decomposes into counter allocations, box measurements, and paragraph macros.

Instead, LaTeX packages actually extend the system through a high-level layer of **Declarators**:

```
                       ┌──────────────────────────────────────────────┐
                       │          LaTeX Packages / Documents          │
                       └──────────────────────┬───────────────────────┘
                                              │
                    ┌─────────────────────────┴────────────────────────┐
                    ▼                                                  ▼
      ┌───────────────────────────┐                      ┌───────────────────────────┐
      │  Turing / Glue Primitives  │                      │    Semantic Declarators   │
      │  (Control Flow & State)   │                      │  (Registered Capabilities)│
      ├───────────────────────────┤                      ├───────────────────────────┤
      │ • \def, \edef, \let       │                      │ • \DeclareMathSymbol      │
      │ • \expandafter, \csname   │                      │ • \DeclareMathOperator    │
      │ • \ifx, \ifnum, \fi       │                      │ • \DeclareMathAlphabet    │
      │ • \advance, \count        │                      │ • \newtheorem, \newcounter│
      │ • Grouping & \global      │                      │ • \NewDocumentCommand     │
      └─────────────┬─────────────┘                      └─────────────┬─────────────┘
                    │                                                  │
                    ▼                                                  ▼
      ┌───────────────────────────┐                      ┌───────────────────────────┐
      │     Expands / Evaluates   │                      │ Writes to Structured IR / │
      │      Control Logic        │                      │    Symbol Table / Schema  │
      └───────────────────────────┘                      └───────────────────────────┘
```

When ingesting packages:
1. **Intercept Declarators as Builtins/Bindings:** Treat commands like `\DeclareMathSymbol`, `\DeclareMathOperator`, `\newtheorem`, or `\NewDocumentCommand` as semantic registration hooks that populate structured data tables (your `lib-symb` tables and environment registries).
2. **Execute Turing Primitives:** Let TeX's macro expansion and conditional logic resolve the package options, argument parsing, and internal plumbing.
3. **Sink Layout Primitives:** Turn layout primitives (`\hbox`, `\vbox`, `\kern`) into transparent content wrappers or silent consumers via typed signatures.

---

### 5. Kernel Internals: The Bridge Layer

When author or package code runs, it constantly calls into LaTeX kernel macros rather than raw TeX primitives. As noted in your file, these fall into a measurable, finite set:

- **Lookahead & Argument Sniffing:** `\@ifnextchar`, `\@ifstar`, `\@testopt`.
- **Dynamic Definition:** `\@namedef`, `\@nameuse`, `\@ifundefined`.
- **List & Token Accumulation:** `\g@addto@macro`, `\@cons`, `\@for`.
- **Protected Expansion:** `\protected@edef`, `\protected@write`.
- **Standard Sinks & Discards:** `\@gobble`, `\@gobbletwo`, `\@firstoftwo`, `\@secondoftwo`, `\@empty`.

You have two choices for this layer:
- **Transcribe directly from `latex.ltx`:** Because these macros are written purely in terms of TeX expansion primitives (`\def`, `\ifx`, `\expandafter`, `\csname`), a working Gullet can evaluate them unmodified.
- **Implement as Native Host Bindings:** Implement high-frequency routines (like `\@ifnextchar` or `\@ifstar`) natively in Python to speed up parsing and avoid deep recursive token expansions.

---

### 6. The Execution Blueprint: "Partial Expansion"

To move PyTeXML from a Knuthian reader to a semantic interpreter:

1. **Token Input Stack:** Connect [tex_reader.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/tex_reader.py) to a stack that can push/pop tokens (supporting nested macro expansions alongside file buffers).
2. **The Evaluator Loop:**
   ```python
   def next_semantic_token():
       while True:
           token = input_stack.pop()
           meaning = symbol_table.get(token)
           
           if meaning.is_expandable and token not in STOP_SET:
               # Gullet: Expand \def, \csname, \expandafter, \if, etc.
               # Push expanded tokens back onto input_stack
               expand(meaning, input_stack)
           elif meaning.is_assignment:
               # Upper Stomach: execute \def, \let, \count, \catcode
               execute_assignment(meaning, input_stack)
           elif meaning.is_declarator:
               # Semantic Hook: register symbol, counter, or environment
               dispatch_declarator(meaning, input_stack)
           elif meaning.is_layout_sink:
               # Consume arguments using quantity scanners and discard/unwrap
               sink_layout(meaning, input_stack)
           else:
               # Protected construct, character, or bound IR node: emit to AST
               return token
   ```
3. **The Stop Set:** Define the policy set of tokens that must *never* expand (e.g. `\mathbb`, `\frac`, `\section`, math operators, and lexicon symbols). Expansion continues right up until it encounters a member of the stop set, preserving high-level mathematical and document structure.

This architecture avoids the trap of building a full DVI/typesetting engine while providing the exact computational power that LaTeX packages require to define syntax, parse options, and register symbols.

# yea but i have also in mind some ideas about doing these things differently. i still need to be able to emulate behavior, but for example instead of doing the state machine literally, like what latexML did in perl, I'm trying to break down the questions and for example resolve and strip down complexity layer by layer. like reading through the whole document and iteratively resolving dependencies, determining closures over executable environments so i can isolate them to be evaluated. instead of doing the dynamic state machine directly. im trying to articulate hard to describe ideas

Searched for "closure"
Viewed opus-mechanical-bindings.md:1-78

What you are reaching for is the difference between an **imperative simulation** (which is what TeX82 and LaTeXML in Perl are) and a **modern optimizing compiler / static analysis pipeline**. 

In LaTeXML (and TeX itself), processing is a single, monolithic, stateful temporal stream: from character 0 to character 1,000,000, every token can mutate catcodes, rebind macros, allocate registers, and alter the universe for every token that follows. If anything goes wrong at token 400, the simulation is poisoned for the rest of the document.

Breaking this down layer-by-layer—extracting **units**, computing **static closures**, taking **context snapshots**, and evaluating **hermetic environments in isolation**—is a vastly superior architecture for semantic extraction.

Here is how to articulate and formalize that model.

---

### 1. The Core Paradigm: Hermetic Evaluation of Units

Instead of viewing a LaTeX document as a single infinite instruction tape executed by a Turing machine, view it as:
> **An ordered collection of discrete, self-contained semantic Units (paragraphs, math equations, sections, figures), each evaluated against an immutable Context Snapshot within a bounded Dependency Closure.**

```
Traditional TeX / LaTeXML (Stateful Simulation):
Token_0 ──> [Global Mutable State] ──> Token_1 ──> [Mutated State] ──> ... ──> Token_N

Your Staged Architecture (Decomposed Compiler):
Document Source
   │
   ├── [Pass 1: Structural Slicing] ──> Spans, Literal Islands, Structural Units
   │
   ├── [Pass 2: Context Threading]  ──> Versioned Context Snapshots (Git-like timeline)
   │
   ├── [Pass 3: Closure Analysis]   ──> Unit Dependencies (Symbols, Macros, Counters)
   │
   └── [Pass 4: Hermetic Eval]      ──> evaluate(Unit, Closure) ──> Pure IR / AST
```

---

### 2. The Layers of Decomposition (Peeling the Onion)

#### Layer 0: The Lexical & Coordinate Anchor (Spans & Literal Boundaries)
Before you evaluate a single macro or touch the stomach, you establish the immutable coordinate system:
- **Zero-evaluation partitioning:** Scan for lexical structures that *cannot* be altered by dynamic macros: comment boundaries (`%`), literal verbatim blocks (`\begin{verbatim}`, `\verb|...|`), and top-level structural units.
- **Source spans:** Every byte/codepoint gets a permanent origin tag `(source_id, start..end)`. No rewrite, expansion, or sanitization ever destroys this anchor.

#### Layer 1: Context Versioning (Replacing Global Mutable State)
In TeX, the meaning table changes as you walk down the document. But in 99% of academic LaTeX:
- 95% of definitions happen in the preamble (`\usepackage`, `\newcommand`, `\newtheorem`).
- Mid-document mutations are localized (e.g. `\begingroup ... \endgroup`, environment scopes, or occasional counter increments).

Instead of one global mutable dictionary:
- Treat the dictionary like an **immutable persistent tree (or Git timeline)**: $C_0 \to C_1 \to C_2 \dots$
- The preamble produces the root baseline context $C_{\text{preamble}}$.
- A definition inside the document does not mutate the world; it publishes a new revision: $C_{\text{next}} = \text{fork}(C_{\text{prev}}, \text{patch})$.
- Every Unit in the document points to its specific parent `ContextId`.

#### Layer 2: The Binding Floor as the Closure Boundary
How do you determine if an environment (like `\begin{equation} ... \end{equation}`) is isolated enough to evaluate?
- **The Binding Floor:** You don't scan all the way down to font slots and DVI boxes. Your bindings for LaTeX packages, AMS symbols, and math constructors are the **floor**. They are opaque terminal symbols with known signatures.
- **Transitive Closure Scanning:** 
  For any unit $U$:
  1. Scan all control sequences in $U$: $\{ \text{token}_1, \dots, \text{token}_k \}$.
  2. If a token is in the **Stop-Set / Binding Floor** (e.g. `\mathbb`, `\frac`, `\sum`), its dependency ends there.
  3. If a token is an **author macro** (e.g. `\R`), look up its expansion in the unit's context snapshot $C_U$ and recursively scan its body.
  4. Collect the set of all required definitions $\mathcal{D}_U$.
- If all $\mathcal{D}_U \subseteq C_U$ are pure expansions with no side-effects, **$U$ is a closed pure expression**.

#### Layer 3: Decoupling the "Fold" (Temporal State & Counters)
The classic reason TeX insists on running sequentially is stateful numbering: `\thesection`, `\ref{sec:intro}`, `\label{thm:main}`, and theorem counters.
- **The insight:** Counters are *events*, not arbitrary Turing states.
- You separate **the Fold** from **the Unit**:
  - The document has a sequential event spine: `[SectionStep("intro"), TheoremStep("main"), FigureStep("arch")]`.
  - The fold rolls forward linearly, computing monotonic state: at character offset $X$, the counter state is $\{ \text{section}: 1, \text{theorem}: 2 \}$.
  - A unit that reads a counter does not dynamically run TeX counter arithmetic; it simply declares a dependency on `FoldState@Offset(X)`.

#### Layer 4: Hermetic Execution (The Pure Evaluator)
Once a unit $U$ has:
1. Its token stream
2. Its closed context snapshot $C_U$ (macro bodies down to the binding floor)
3. Its fold state (if it reads numbering)

The evaluator is not an engine running a continuous loop; it is a **pure function**:
$$\text{AST}_U = \text{evaluate}(U, \text{Closure}_U)$$

- **Parallelizable:** 500 equations in a paper can be evaluated across all CPU cores simultaneously because neither their inputs nor their outputs share mutable state.
- **Fail-Safe / Bounded:** If an equation contains a macro that cannot be resolved (or an open `\csname`), the unit fails in isolation. It emits an AST node with an explicit `UnresolvedDependencyRequest`, rather than crashing or stalling the entire document parser.

---

### 3. How to Handle TeX's "Dirty" Realities Under This Model

TeX is not naturally purely functional; authors do strange things. Here is how static closures gracefully absorb TeX's edge cases:

| TeX Pathology | How It Breaks LaTeXML / TeX82 | How Your Isolated Closure Model Handles It |
| :--- | :--- | :--- |
| **Dynamic `\csname`** (`\csname foo\the\count0\endcsname`) | Evaluated blindly on the fly; crashes downstream state if unhandled. | Marks the unit's closure as **Open**. The unit cannot be evaluated ahead-of-time; it is flagged with a recorded dependency request and queued until the fold publishes the referenced counter. |
| **Mid-document `\renewcommand`** | Mutates global dictionary; changes meaning of subsequent unrelated blocks unpredictably. | Emits a **Context Revision Event**. Units downstream re-anchor their parent `ContextId` to the revised snapshot. Earlier units remain completely untouched. |
| **Package Patches & `\@internal` hacks** | Intercepts internal package macros; crashes if the package isn't loaded or internal variables differ. | Classified statically during closure resolution: either absorbed by the binding layer as a presentation sink, or elevated as an explicit semantic requirement. |
| **Unbalanced Grouping (`\def\be{\begin{equation}}`)** | Must be expanded before syntax trees can even be parsed. | Lowered in the expansion phase *before* unit boundary validation. Because it's in the author macro dictionary, macro inlining normalizes the syntax stream before unit isolation. |

---

### 4. Summary: The Mental Model to Commit To

You are turning LaTeX interpretation from:
> **"Simulate a 1982 batch printer line by line until page eject"**

into:
> **"A phased compiler pipeline: Slicing $\to$ Context Threading $\to$ Static Dependency Closure $\to$ Hermetic Island Evaluation $\to$ Relational Assembly."**

In this architecture, your Knuthian reader is not the mouth of a running simulator. It is the **low-level tokenizer** feeding a static analyzer that isolates units and builds closures. When you evaluate an equation, a paragraph, or a theorem, you are evaluating an **atomic sandbox** with explicit inputs and outputs.


These notes in [opus-reader-notes.md](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/issues/opus-reader-notes.md) are the **direct technical bridge** between the theoretical ideas in your notes and the formal brief in [pytexml-semantic-engine.md](file:///d:/aipithicus/aipithicus-issues/LaTeXAI/briefs/pytexml-semantic-engine.md).

In fact, **`opus-reader-notes.md` is the codebase audit that was synthesized into Section 13 of the semantic engine brief.**

Here is an analysis of how they relate, why these notes are critical, and the specific insights they contribute.

---

### 1. How They Relate: Theory vs. Ground Truth Code

| Document | Primary Role | Perspective |
| :--- | :--- | :--- |
| **`engine-primitives.md` & `gemini-engine-primitives.md`** | **The Architectural Ideal:** The vision of static dependency closures, the binding floor, the fold, and hermetic unit evaluation. | Concept & Compiler Design |
| **`opus-reader-notes.md`** | **The Codebase Audit:** Inspects the actual 280 KB of Python code in `src/reading/` to check what already exists vs. what is missing. | Reverse Engineering & Refactoring |
| **`pytexml-semantic-engine.md`** | **The Formal Specification:** Synthesizes the vision and the audit into a gated 7-step engineering brief for the repository. | Project Brief & Milestones |

---

### 2. The Four Major Insights in `opus-reader-notes.md`

#### Insight 1: "The Reader is Already Half an Engine"
The audit reveals that you **do not need to rewrite PyTeXML from scratch**. The infrastructure for a full semantic engine is already partially built in `src/reading/`:
- **The Mouth** exists (`TexReader` + `CatcodeTable`).
- **The Scoped Meaning Journal** exists (`ReaderContext`).
- **The Recovery and Unknown tracking** exists (`UncertainMeaning`, `ConditionalRegion`, `DeferredRegion`).
- **The Group/Conditional stacks** exist (`_groups`, `_conditionals`).

What is missing is essentially the **Gullet** (macro expansion with delimited parameters, `\expandafter`, `\csname`) and **quantity scanners** for layout sinks.

#### Insight 2: The "One Core, Two Drivers" Model
This is perhaps the clearest operational idea in the notes:
```
                       ┌────────────────────────────────────────┐
                       │           Shared Engine Core           │
                       │   (Mouth, Input Stack, Meaning Table,  │
                       │     Expansion, Primitive Registry)     │
                       └───────────────────┬────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                             ▼
     ┌─────────────────────────────┐               ┌─────────────────────────────┐
     │    Driver 1: Sequential     │               │   Driver 2: Unit Evaluator  │
     │  (Structural Dispatcher)    │               │    (Isolated Evaluator)     │
     ├─────────────────────────────┤               ├─────────────────────────────┤
     │ • Walks document linearly   │               │ • Runs in a hermetic sandbox│
     │ • Establishes context/state │               │ • Reads explicit Context    │
     │ • Probes & commits          │               │   snapshots + Fold state    │
     │ • Emits clean master.tex    │               │ • Emits semantic AST / IR   │
     └─────────────────────────────┘               └─────────────────────────────┘
```
In the formal brief (§13.4), this division was left slightly more open, but `opus-reader-notes.md` makes the strong, correct argument that **these are two drivers of the same core**. Driver 1 builds the document skeleton and context snapshots; Driver 2 evaluates the content islands.

#### Insight 3: The "Probe and Commit" Pattern for Preparation
A recurring question in PyTeXML has been: *How can preparation use macro expansion without accidentally guessing or corrupting `master.tex`?*

`opus-reader-notes.md` gives the exact recipe:
1. Save a reader checkpoint (`reader.checkpoint()`, `context.copy()`).
2. Run expansion on the candidate construct.
3. If every lookup was established, commit the expansion result.
4. If an unknown/uncertain meaning was encountered, **roll back** to the checkpoint and emit a deferred region (retaining today's estimated effects).

This preserves PyTeXML's foundational invariant: **never guess or invent a truth value**.

#### Insight 4: Catching the `TokenCursor` Span Limitation
`opus-reader-notes.md` catches a subtle bug waiting to happen in `src/reading/token_cursor.py`:
- Today, `TokenCursor` assumes all tokens lie in a **single contiguous source span**.
- But when macro expansion occurs, the expanded token stream mixes **body tokens** (written at the macro definition site in the preamble or package) with **argument tokens** (written at the call site in the body).
- The note correctly identifies that the token-list input level must track both the token's origin span and the call site span.

---

### 3. Comparing the Notes with Section 13 of the Brief

Notice that **Section 13 of the brief adopted almost everything from `opus-reader-notes.md` word-for-word**:
1. The 7-step sequence (from `Separate language from knowledge` to `Evaluating a bounded segment`).
2. The exact test gates (byte-identical specimen regression, Fractal's `lineno` flag, DeadSalmons' `\ProcessOptions`).
3. The table comparing what exists vs. what is missing.

### Summary Assessment

`opus-reader-notes.md` is **completely aligned, accurate, and essential**. It proves that the ambitious compiler ideas in `gemini-engine-primitives.md` and `engine-primitives.md` are not pie-in-the-sky—they map directly onto specific Python classes (`StructuralDispatcher`, `ReaderContext`, `StoredDefinition`) that you already have.

It provides the practical answer to *how* to start implementing: 
**Start with Step 1 (replace the 360-line if-chain in `StructuralDispatcher._next_item` with a primitive registry)** and hold to the byte-identical specimen output gate.