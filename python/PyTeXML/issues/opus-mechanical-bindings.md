This is the core question for the interpretation engine. Here's how I'd make the mechanics concrete. It's roughly the shape LaTeXML uses, minus the raw-package fallback.

## How bindings work mechanically

**A binding is a meaning.** The engine keeps one table that maps each control sequence to a meaning, and there are only three kinds:

| Meaning | Where it comes from | What the engine does with it |
| --- | --- | --- |
| Macro | author code, local styles, or a binding that supplies a macro body | Expands it: reads its arguments, substitutes them, and pushes the result back as input |
| Primitive | built into the engine | Executes it: assignments, grouping, conditionals, registers |
| Binding | the binding library | Dispatches its declared behavior: read arguments per its signature, then emit IR, absorb it as a sink, or change state |

The loop is TeX's own. Tokens come from the input stack, made of file levels and token-list levels. The gullet expands macros and expandable primitives. A non-expandable meaning reaches the stomach, where a primitive executes or a binding dispatches.

**That's what makes "expand enough" well defined: bindings are the floor of expansion.** Expansion continues until it reaches a bound command, then stops. Take `\newcommand\R{\mathbb{R}}`:
1. `\R` is a macro, so it expands to `\mathbb{R}`.
2. `\mathbb` is bound as a variant, so the engine builds a math node with the double-struck variant.
3. Nothing ever expands `\mathbb` into LaTeX's font machinery.

Two more cases work the same way:
- `\newcommand\norm[1]{\left\| #1 \right\|}` expands, and its pieces are handled by the math normalization rules.
- `\def\be{\begin{equation}}` works naturally, because the expanded tokens simply feed back into the stream.

**Arguments are typed in the signature.** That decides how much of each argument gets interpreted:

| Argument type | Treatment | Example |
| --- | --- | --- |
| Content | Interpreted recursively into child IR nodes | the body of `\section{…}` |
| Text | Expanded to a plain string | label keys, file names |
| Verbatim | Read through the mouth with literal catcodes | `\url`, `\verb` |
| Keyval | Parsed against the package's schema | `\includegraphics[…]` options |
| Number or dimension | Evaluated | `\setcounter{…}{3}` |
| Opaque | Kept raw | anything bound as an opaque island |

Unknown control sequences, with no meaning at all, stay as raw nodes with a request, as before.

## Handling author styles and modified copies

**A custom `.sty` is author code, handled exactly like the preamble.** The package mechanism reads it with `@` as a letter and processes its options. Its definitions enter the meaning table as macros. When the manuscript invokes them, they expand down to the binding floor. This is where "emulation" really lives: in the engine's primitive core and the gullet, not in special handling for `.sty` files.

**The hard part is author code that reaches into internals.** It comes in three forms:
1. **Kernel internals:** `\@ifnextchar`, `\@ifstar`, `\@namedef`, `\@nameuse`, `\@ifundefined`, `\g@addto@macro`, `\protected@edef`, `\@gobble`, `\z@` and so on. These need a kernel binding layer. Wherever the kernel's own definition is pure expansion over primitives, transcribe it from `latex.ltx` as a macro body and let the engine expand it; implement the rest natively. The set is finite and measurable: count which internals the corpus's author code actually uses.
2. **Internals of bound packages:** for example, redefining `\@maketitle` or natbib's `\NAT@…` commands. A binding is declarative and has no internals, so these patches have no target. Classify each one:
   - presentation-only patches are absorbed (the internal-absorber kind)
   - semantic patches become requirements
   - both are recorded as diagnostics, never silently dropped
3. **Typesetting primitives:** `\hbox`, `\kern`, font selection. These are sinks; content inside a box is kept, so `\mbox{x}` gives `x`.

Redefining a bound user-level command works by itself. `\let\oldcite\cite` copies the binding's meaning, because a binding is a meaning, and an author's `\renewcommand\cite{…\oldcite…}` then expands into that binding.

**A modified copy is the pinned binding plus an author patch layer.** Diff the local file against its pinned release. The changed or added definitions load as author redefinitions on top of the binding, and everything unchanged comes from the binding. That's more precise than the choice I put in O10 (binding versus author style).

## What the engine core needs

- **Definitions:** `\def`, `\gdef`, `\edef`, `\xdef`, `\let`, `\futurelet`; e-TeX's `\protected`, `\unexpanded`, `\detokenize`.
- **Expansion control:** `\expandafter`, `\noexpand`, `\csname`…`\endcsname`, `\string`, `\number`, `\the`.
- **Conditionals:** `\if`, `\ifx`, `\ifnum`, `\ifdim`, `\ifcat`, `\ifodd`, `\ifcase`, plus `\ifdefined`, `\ifcsname` and `\unless`.
- **State:** grouping and `\global`, registers with `\advance`, catcode assignment, `\aftergroup`.
- **Safety:** a step budget, so a runaway recursive macro becomes a diagnostic rather than a hang.
- **Provenance:** every token-list level records where its tokens were spelled and where they were expanded.

**How it fits the handoff.** The sequential read of `master.tex` builds the meaning-table snapshots, the context references from span brief §9.4. Each worker then runs this same loop over its unit, starting from that unit's snapshot.

I read it through. The decomposition is sound, and it's the right home for the mechanics I sketched last time. That mechanics is what the "Binding-driven evaluation" box needs: one meaning table, with bindings as the floor where expansion stops. One property makes your static step tractable: **the binding floor bounds the dependency closure as well as expansion.** To compute a unit's closure, you scan stored bodies transitively, following macros and stopping at bound commands and primitives. Bindings declare their own requirements, so there's nothing to scan inside them.

Three refinements I'd make, plus one stale item:

**1. Make the closure an over-approximation and the evaluator the authority.** "Evaluate after all inputs are known" holds for most units: a math region that uses `\R` and `\norm` has its full closure in the current context version. TeX can't guarantee it in general, though. Your §5 already says references in unexecuted bodies are only potential dependencies. I'd state the consequence as a rule: readiness and prefetch use the static closure, the evaluator is authoritative, and any lookup outside the closure becomes a request and a recorded miss. Recorded misses show where the analysis needs improving. The rules for computing the closure belong in the brief:
- Arguments contribute their own closure from the call site, in the invocation's context.
- Both branches of a conditional inside a body count.
- `\let` follows the meaning it copies.
- A name built with `\csname` marks the closure open, so the unit can be ready only with a request in hand.

**2. Make "depends on the fold position" an explicit dependency kind.** Your §7 makes a good point: an expression that reads a counter (`\thesection` in running text, `\ifnum\value{section}>2`) depends on where the fold has reached, so numbering everything once at the end isn't enough. I'd encode this as a dependency on the fold's state at a given position. Those units become ready once the fold passes them, and the order becomes: units that emit events, then the fold up to that point, then the units that read it. Because the fold is cheap and sequential, this costs little. It also keeps your claim that evaluation is atomic: a unit sees only its declared inputs, and fold state is one of them.

**3. Units that change context for later units need ordered publication.** Your §7 covers this ("context-producing work has ordered consumers"). It's worth one sentence in §5's worklist: a unit that redefines meanings mid-document must publish its context revision before any later consumer's closure is treated as final. Those are the `known` and `unknown` context effects in span brief §9.4.

**4. One stale item.** §3 lists "Bibliography or asset replacement" as a preparation operation. Under the canonical-bibliography brief, the bibliography no longer goes into `master.tex`: the site becomes a marker and the entries become records on the parallel track. Similarly, §3.9 of the ontology brief now says local styles that a binding replaces aren't carried in the payload, which fits your "necessary declarations remain" wording but is worth a cross-reference.