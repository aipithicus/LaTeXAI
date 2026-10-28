
**The hard part is author code that reaches into internals.** It comes in three forms:
1. **Kernel internals:** `\@ifnextchar`, `\@ifstar`, `\@namedef`, `\@nameuse`, `\@ifundefined`, `\g@addto@macro`, `\protected@edef`, `\@gobble`, `\z@` and so on. These need a kernel binding layer. Wherever the kernel's own definition is pure expansion over primitives, transcribe it from `latex.ltx` as a macro body and let the engine expand it; implement the rest natively. The set is finite and measurable: count which internals the corpus's author code actually uses.
2. **Internals of bound packages:** for example, redefining `\@maketitle` or natbib's `\NAT@…` commands. A binding is declarative and has no internals, so these patches have no target. Classify each one:
   - presentation-only patches are absorbed (the internal-absorber kind)
   - semantic patches become requirements
   - both are recorded as diagnostics, never silently dropped
3. **Typesetting primitives:** `\hbox`, `\kern`, font selection. These are sinks; content inside a box is kept, so `\mbox{x}` gives `x`.



| Meaning | Where it comes from | What the engine does with it |
| --- | --- | --- |
| Macro | author code, local styles, or a binding that supplies a macro body | Expands it: reads its arguments, substitutes them, and pushes the result back as input |
| Primitive | built into the engine | Executes it: assignments, grouping, conditionals, registers |
| Binding | the binding library | Dispatches its declared behavior: read arguments per its signature, then emit IR, absorb it as a sink, or change state |

The loop is TeX's own. Tokens come from the input stack, made of file levels and token-list levels. The gullet expands macros and expandable primitives. A non-expandable meaning reaches the stomach, where a primitive executes or a binding dispatches.

Expansion continues until it reaches a bound command, then stops. Take `\newcommand\R{\mathbb{R}}`:
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

"Evaluate after all inputs are known" holds for most units: a math region that uses `\R` and `\norm` has its full closure in the current context version. TeX can't guarantee it in general, though. Your §5 already says references in unexecuted bodies are only potential dependencies. I'd state the consequence as a rule: readiness and prefetch use the static closure, the evaluator is authoritative, and any lookup outside the closure becomes a request and a recorded miss. Recorded misses show where the analysis needs improving. The rules for computing the closure belong in the brief:
- Arguments contribute their own closure from the call site, in the invocation's context.
- Both branches of a conditional inside a body count.
- `\let` follows the meaning it copies.
- A name built with `\csname` marks the closure open, so the unit can be ready only with a request in hand.

**2. Make "depends on the fold position" an explicit dependency kind.** Your §7 makes a good point: an expression that reads a counter (`\thesection` in running text, `\ifnum\value{section}>2`) depends on where the fold has reached, so numbering everything once at the end isn't enough. I'd encode this as a dependency on the fold's state at a given position. Those units become ready once the fold passes them, and the order becomes: units that emit events, then the fold up to that point, then the units that read it. Because the fold is cheap and sequential, this costs little. It also keeps your claim that evaluation is atomic: a unit sees only its declared inputs, and fold state is one of them.

**3. Units that change context for later units need ordered publication.** Your §7 covers this ("context-producing work has ordered consumers"). It's worth one sentence in §5's worklist: a unit that redefines meanings mid-document must publish its context revision before any later consumer's closure is treated as final. Those are the `known` and `unknown` context effects in span brief §9.4.

**4. One stale item.** §3 lists "Bibliography or asset replacement" as a preparation operation. Under the canonical-bibliography brief, the bibliography no longer goes into `master.tex`: the site becomes a marker and the entries become records on the parallel track. Similarly, §3.9 of the ontology brief now says local styles that a binding replaces aren't carried in the payload, which fits your "necessary declarations remain" wording but is worth a cross-reference.


## Partial expansion, precisely

TeX does three kinds of work:
- **expansion:** macros, conditionals, `\csname`
- **assignment:** definitions, registers, catcodes, counters
- **typesetting:** boxes, glue, line breaking, pages

You need the first two and never the third.

Partial expansion is then exactly `\edef` with the lexicon treated as `\protected`. Everything expands except the stop-set tokens, which are emitted by their spellings.
- **Kernel precedent:** `\protected@write` to the `.aux` file expands fragile macros but keeps robust commands as their names.
- **LaTeXML has this as a parameter type:** `ExpandedPartially` in `Base_ParameterTypes.pool.ltxml`, commented "defers \protected… Similar to when \edef is used."

The stop set is a policy, not a fact about TeX. It's the lexicon's keep and map rows, the structural constructors and the alphabets. `lower` means expand, and `drop` means sink.

## The engine core, listed out

| Layer | Members | Why it's needed |
|---|---|---|
| Reading | catcodes, tokenization, literal modes | Already exists in PyTeXML |
| Expansion | the `\def` family with delimited parameter matching, `\let`/`\futurelet`, `\csname`, `\expandafter`/`\noexpand`, conditionals, `\the`/`\number`/`\string`, `\protected`/`\unexpanded`; LaTeX's optional-argument and star conventions | Lowering author and package macros |
| State | registers and arithmetic, grouping, `\global`, `\aftergroup`, meaning tables (`\mathcode`, `\chardef`, `\mathchardef`) | Meanings and counters change what later tokens mean |
| Quantity scanners | number, dimen, glue, muglue, keywords, box and rule specs | Consuming typesetting primitives exactly (`\hskip 3pt plus 1fil`) without computing any layout |
| Declarators | the table above | Writing tables |

The rest of TeX's typesetting is removed by signature. Most of it becomes a sink. A primitive that carries content becomes a transparent wrapper (`\hbox{…}`, `\raisebox`).

LaTeXML's 19 `TeX_*` pools show the proportions:
- **Carry meaning:** Macro, Logic, Registers, Character, Math, Tables, and the input half of FileIO.
- **Almost entirely typesetting:** Box, Glue, Kern, Penalties, Page, Paragraph, Hyphenation, Inserts, Marks, Fonts, Job and Debugging.

What they're worth to PyTeXML is their argument grammars. `Base_ParameterTypes` (`Number Dimension Glue MuGlue Keyword Semiverbatim Until XUntil Variable TeXFileName CommaList OptionalKeyVals …`) is effectively the extended signature vocabulary I suggested inventing on top of xparse. Reuse it instead.

## "Font", untangled

| Sense | Example | Treatment |
|---|---|---|
| Glyph design | Times vs kpfonts vs Computer Modern | Sink |
| Encoding and slot | OMS slot `0x14`, T1, AMSa | Rendering infrastructure, but needed in reverse |
| Math alphabet | `\mathbb`, `\mathcal`, `\mathscr`, `\mathfrak`, `\mathbf`, `\boldsymbol` | Notation: a Variant node that keeps its spelling |
| Text style | `\textbf`, `\itshape`, `\emph` | Sink, or an inline role (`\emph`) |
| Old math switches | `{\bf x}`, `{\rm X}`, `{\cal A}` | Map to the alphabet spelling, using the group's extent |
| Vocabulary fonts | bbding, fontawesome5, tipa, MnSymbol | Lexicon rows |

- **Encoding and slot run backwards.** Sources contain `\mathchar"3214`, `\symbol{…}`, `\char` and raw `≤`, and all of them must normalize to `\leq`. LaTeXML's font maps are exactly the (encoding, slot) → Unicode tables you need, and they carry over as plain data:
  - OML, OMS, OMX and OT1 live in `TeX_Fonts.pool.ltxml`.
  - AMSa, AMSb, T1, TS1, LGR and others live under `Package/`.

  They're also what turns a declarator's `{symbols}{"14}` into U+2264 during extraction.
- **Font packages do two things at once.** kpfonts redesigns glyphs, which is a sink, and adds 555 symbols, which are lexicon rows. Your table captures the second, which is the right call.
- **Unicode loses alphabet distinctions, which strengthens B01.** `\mathcal{A}` and `\mathscr{A}` differ in Unicode only by variation selectors. `\mathbf{x}` (bold upright) and `\bm{x}` (bold italic) are different notations. Spellings keep distinctions that code points lose.
- **One thing in the kpfonts table:** `\mathrm` and `\mathit` both have `font=serif`. If `font` is meant to identify the notation, that loses upright vs italic. If it's only the family axis, consider adding a style column keyed to Unicode's math styles.

## Lexical invariance as a normal form

Two sources that denote the same notation must give the same IR string. The equivalences come from six places:
- `\let` aliases, i.e. shared meaning
- the same notation across packages, joined by code point plus class (what `lsymb --check-cross` already checks)
- slot references, through the font maps
- Unicode typed in the source
- old font switches
- primitive structures: `a \over b` → `\frac{a}{b}`, `\choose` → `\binom`

The canonical spelling is a chosen representative of each equivalence class. Equivalence must come from meaning, never from names that look alike, as `\bm` vs `\mathbf` shows.