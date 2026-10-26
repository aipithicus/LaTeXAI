Agreed. The survey backs that design: wherever source exists, notation packages are 83–84% declarator rows. The rest is mostly composites like `\neq` = `\not=`, which a curated table covers better than source would. Vendoring their source would mostly re-derive rows you already have.

A table holding just glyph data leaves three gaps worth deciding up front. All three are small extensions to the tables, not reasons to vendor:

- **Commands that take arguments need a signature.** extarrows' `\xlongequal[]{}` and extpfeil's arrows are table entries, but the reader has to know their argument grammar. That's an extra signature column in xparse style, empty for symbols with no arguments. `symbols.tsv` doesn't have one today.
- **Package options can change the vocabulary.** For packages whose options add or swap symbol sets, that's a package-level fact (option → which rows load). It doesn't belong in the per-symbol rows.
- **Load order decides redefinitions.** kpfonts, mathabx and txfonts redefine standard names with different shapes, and sometimes different meanings. If loading a table is treated as running its declarator rows in load order, "last declaration wins" works the way it does in TeX. That needs a convention for how per-package tables layer over `_kernel`. Since the IR keeps spellings, this mostly affects the glyph column used for reverse mapping, not the IR text.

I also added a note to the bindings memory: lib-symb tables are the whole binding for notation packages, so I won't suggest vendoring their source again. The note includes a summary of the survey results.

Yes. The options are discrete. For notation packages they come in three kinds, and only one of them needs rows at all:

- **Presentation-only options** change glyph shapes or weights but not which names exist or what they mean. Examples are txfonts' `varg`, kpfonts' style options, and fontawesome's solid/regular default. The IR keeps spellings (B01), so these have no IR effect. At most they touch the glyph column that renderers and reverse mapping use. Mark the option as presentation-only and add no rows.
- **Subset options** turn a group of rows on or off. If I remember right, wasysym's `integrals`/`nointegrals` decides whether it defines (and overrides) the integral signs. stmaryrd's `only` restricts loading to the symbols named in its option list.
- **Variant options** swap which glyph or meaning a name maps to. These are rarer, and are just alternative rows for the same name.

For the second and third kinds, I'd tag rows with a condition instead of adding a full row set per configuration. Rows per configuration grow exponentially when options combine freely: three independent flags give eight row sets. A `when` column grows linearly: each row carries a small predicate such as `integrals`, `!integrals`, or `only ⇒ name ∈ options`, and rows with no condition always load. Practically, either works for most packages, since few have more than one or two options that affect vocabulary. But conditions stay clean as packages add options.

The condition column also mirrors the source. In the `.sty`, these options are `\DeclareOption{integrals}{…declarator calls…}`, so a conditioned row is literally "this declarator runs when that option is set". The survey counted those statements separately as option-context statements.

It also folds into load order. A wasysym row tagged `integrals` that redefines `\int` is just a later declaration overriding the `_kernel` row, under the same "last declaration wins" rule.

So it's two small additions to the table format, not a new layer:
- a `when` column on rows
- a short per-package options list that labels each option as presentation-only, subset or 

Good name. "Switch" says what it is, a qualifier chosen by settings, without hinting at evaluation order the way "when" does. Matching on an exact composite key is also simpler than evaluating predicates. A few rules make the key unique and complete:

- **The key is (command, mode, switch).** The tables already promise one row per command and mode, so switch just extends that key. A lint can check that no two rows in a package share it.
- **An empty switch means the default.** Most rows have no switch. The lookup tries an exact switch match against the active options first, then falls back to the empty-switch row for that command and mode. A package with no vocabulary-changing options never fills the column.
- **Independent options that can be active together.** If A and C can both be set and both have a row for the same command, two keys match. There are two ways out:
  - Allow a combined value such as `A+C` for the rows that need it, so matching stays exact.
  - Or have the lint guarantee that such a command never has rows under both.

  TeX's own tiebreak is the package's declaration order (`\ProcessOptions` runs options in the order the package declares them, not the order the user typed them). You'd only need that order if you want to allow the overlap.
- **Absence needs a row.** If switch A means the package doesn't define a command, a row under A that marks it undefined lets the lookup return "not defined here" instead of falling back to the default row.

One case doesn't fit discrete values: stmaryrd's `only`. With `\usepackage[only,llbracket,rrbracket]{stmaryrd}`, each symbol's own name is the option. That's better as a single package-level flag than as row values: under `only`, a row is active only if its command name appears in the options.

Yes. The symbol family seems to use only a handful of these syntaxes, which is what keeps routing a lookup instead of logic. They come in two groups.

**How options select rows**
- **Discrete switches:** flags that pick rows, which is the switch column.
- **Name-list selection:** stmaryrd's `only`, where the option list names the symbols to load. That's a package flag plus a membership test.
- **Presentation options:** glyph shape, weight or font source. These are ignored for extraction.

**How a symbol is invoked**, which sets the shape of the lookup key
- **Named command:** `\leq`. The key is the command.
- **Addressed by argument:** pifont's `\ding{51}` and `\Pisymbol{pzd}{51}`, fontawesome5's `\faIcon{github}`. The key is the command plus the argument value, so the table needs rows keyed that way.
- **Style argument on a named symbol:** `\faIcon[regular]{star}`. The optional argument is presentation, so it drops out of the key.
- **Alphabet application:** `\mathbb{R}`. These are the `kind=alphabet` rows: the IR keeps `\mathbb{R}` as written, and the letter only matters for reverse mapping (ℝ → `\mathbb{R}`).
- **Composites:** `\neq` defined as `\not=`. A curated row maps the composite to its canonical spelling, and maps the decomposed source form back to it.

When you build the router, I'd sweep each table and tag every row with one of these invocation shapes. A row that fits none of them is the signal of a genuinely new syntax, as opposed to a new symbol.

That split works, and it fits how the tables are already built. A few design points follow from it.

**The morphology is a structured node, not a glyph.** `\mathbb{R}` breaks down into an alphabet style (double-struck) and a base (R). The IR text stays `\mathbb{R}` under B01, and a structured layer can carry the parts as attributes. The base isn't always a single letter:
- several letters: `\mathbb{RP}`, where the style applies to each letter
- digits: bbm's or dsfont's indicator `\mathbb{1}`, `\mathbf{0}`
- control sequences: `\boldsymbol{\alpha}`, `\mathcal{O}_X`

So model the base as a token sequence, not a character.

**Collapse spellings that differ only in rendering; keep styles an author can contrast.** `\mathbb{R}`, `\Bbb R`, `\mathbbm{R}`, `\mathds{R}`, a typed `ℝ`, and an author's `\R` (lowered) are all double-struck R, so they route to one row. The bbm, dsfont and amsfonts blackboards are different designs of the same notation.

`\mathcal` and `\mathscr` are different: papers use 𝒞 and 𝒮-script side by side with different meanings, so they stay distinct styles. A useful test is whether an author could use two of them in the same paper to mean different things. That gives an inventory of about ten styles:
- upright, italic, bold, bold italic
- blackboard, calligraphic, script, fraktur
- sans-serif, typewriter

Unicode only separates calligraphic from script with variation selectors, which is another reason spellings beat code points here.

**Reverse mapping has holes.** The Unicode block for math letter styles leaves gaps where letters were encoded earlier in Letterlike Symbols:
- blackboard: ℂ ℍ ℕ ℙ ℚ ℝ ℤ
- script: ℬ ℰ ℱ ℋ ℐ ℒ ℳ ℛ ℯ ℊ ℴ
- fraktur: ℭ ℌ ℑ ℜ ℨ

Mapping a typed `ℝ` back to (double-struck, R) needs both blocks plus an exceptions table. It's a small, fixed list, but easy to miss.

**Meaning stays out of the tables as authority.** I agree it belongs to the prose. `\mathbb{P}` is probability in one paper and projective space in the next, and `\mathcal{L}` is a loss, a Lagrangian or a Laplace transform. Even operators drift: `\sim` can mean "distributed as", "asymptotic to" or an equivalence relation.

The lib-symb tables do have a `meaning` column. I'd treat it as an optional conventional prior, useful for search or as a fallback hint, and never emit it into the IR as fact. Alphabet applications get no meaning from the tables at all.

**Prose gets its own relation.** Since meaning lives in the prose, the IR needs a way to connect a math mention to the sentence that establishes it, such as "Let 𝓛 denote the loss". That's a relation in the ontology brief's §6 graph, most naturally an inferred relation (§6.10) from a mention to the defining prose span. It needs the morphology to be explicit, because the match key is (style, base), not the source spelling. Then `\mathcal{L}`, an author's `\Loss`, and a typed `𝓛` all resolve to the same notation in one paper.

Right, and that's where lexical invariance pays off. The defining sentence holds a math mention, `Let $\mathcal{L}$ denote the loss`, and that mention goes through the same normalization as every later display. Linking a use to its definition becomes equality of normalized forms, with no glyph or Unicode matching. An author's `\Loss`, lowered to `\mathcal{L}` on both sides, matches automatically.

What's left is mostly deciding what counts as the same notation:

- **Subterm matching.** The defined object usually appears inside larger expressions, such as `\mathcal{L}(\theta)` or `\nabla \mathcal{L}`. So the match is the defining mention's normal form against subtrees of later math, not whole-expression equality.
- **Decorations versus indices.** `\hat{\beta}` is a different notation from `\beta`, but `\beta_{j}` is usually an instance of `\beta`, while `\beta_{\text{OLS}}` is a name. That's the "name or product" ambiguity again, so I'd match at levels: exact subtree first, then base symbol with indices stripped. Record which level matched as evidence instead of guessing.
- **Direction and scope.** "Let X denote" points forward, but "…where X is the …" right after a display defines symbols in that display, looking backward. Notation also gets redefined section by section. The rule becomes: link to the nearest applicable definition in the right direction, using the cue phrase to set the direction.
- **Cue phrases are a small vocabulary:** let … denote, where … is, define … as, we write, `:=` or `\coloneqq` inside the math. They work like tables: a short curated list, not a model.

In the relation graph this is one relation type, notation-definition, from a math mention to the prose span holding the defining mention. Its evidence is the cue phrase, the matched normal form and the match level. It's cheap because the hard part, making the same notation spell the same everywhere, is already done by normalization.

# incidentally, while i'm all about rich relations in my IR, i dont think all relations are equally important to me. first order, I care about bibliography connecting to mentions in prose, about theorem mentions connecting to their declarations, pointers across different sections of the document, and pointers in the body to figures, figures to captions, etc. more structural stuff. linking every math symbol to every appearance in an equation is not the highest priority, and im willing to count on the reader to be able to make those connections. im trying to make that easy with my lexical invariance

That ordering makes sense, and it's almost exactly the first relation slice the ontology brief proposed in O7: `cites`, `refers-to`, `label-of`, `caption-of`, `note-of`, with everything else deferred. I'd treat the notation-definition relation from the last exchange as explicitly out of scope until something actually needs it.

The structural set is tractable because nearly all of it is marked up in the source: `\cite`, `\ref` and `\cref`, `\label`, `\caption`, and theorem environments. So it's binding-driven and exact, with no inference. The one wrinkle is a second tier of the same relations that's typed by hand:
- **Hand-typed theorem references**, like "by Theorem 3.2" or "see Lemma 2" with no `\ref`. Resolving them needs the emulated counters (B04), because the link is the printed number to the object that carries it. That's the main reason counters have to be right, not just present.
- **Hand-typed citations**, like "Smith et al. (2020)" with no `\cite`. The bibliography brief's citation signatures cover these.

Both are still structural links. They just go through numbers and signatures instead of markup, and their evidence is weaker, which the relation can record.

On math, the trade-off you're making means normalization quality now carries the load that symbol relations would otherwise carry. If `\Loss`, `\mathcal{L}` and a typed `𝓛` all come out as `\mathcal{L}`, the reader can make those links itself. Any inconsistency in normalization shows up directly as a link the reader misses. That's a good argument for testing normalization with cross-paper consistency checks, not just per-expression ones.

I added these priorities to the bindings memory so later suggestions follow them.

# if `\Loss` is known to render the same way as `\mathcal{L}` (both typesetting to 𝓛) then `\Loss` would be expected to have a `\def` somewhere in the source making that explicit, right

Yes. TeX can't typeset `\Loss` without a definition in effect, so for any paper that compiles, the definition is somewhere the reader reaches: the preamble, an input file like DeadSalmons' `math_commands.tex`, a local `.sty`, or a package. A few nuances:

- **It's often not a literal `\def`.** It may be `\newcommand`, `\DeclareMathOperator`, `\NewDocumentCommand` or `\let`. Generated definitions are common in ML papers' command files: a loop that defines `\cA` through `\cZ` as `\mathcal{A}` through `\mathcal{Z}`, or `\expandafter\def\csname…`. These are where the expansion core and the declarators matter, because there's no literal `\def\cL` to find.
- **You never need to know the two render the same.** That equality is a consequence of the definition, not something the system has to know beforehand. Lowering `\Loss` by expanding its definition in effect at the use site produces `\mathcal{L}` directly. If the author had written `\mathscr{L}`, you'd get that instead, correctly. So there are two sources of equivalence:
  - **Definitional, inside the paper:** mechanical. Expand the author's macro.
  - **Conventional, across packages:** `\mathbb{R}` vs `\mathds{R}`, or `\le` vs `\leq` when no definition links them in the paper. These are curated, which is what the tables are for.
- **Scope and redefinition.** Use the definition in effect at that point in master, not the first or last one in the file. That's the context-version bookkeeping the staged pipeline already plans for.
- **A missing definition is a request, not a guess.** If the `.sty` holding it wasn't shipped, the use stays a raw node plus a request.

One small thing to keep: the macro name itself is evidence of meaning. `\Loss` tells the reader what 𝓛 is before any prose does. Lowering it to `\mathcal{L}` in the IR text is right for invariance. The staged pipeline already plans for generated content to carry its origin (invocation and declaration), so the name stays recoverable without cluttering the IR. It's a cheap meaning hint that fits your "meaning comes from the paper" stance: here it comes from the author's own vocabulary.

