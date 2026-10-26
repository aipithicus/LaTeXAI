Reading the briefs now — finished the staged pipeline brief; moving on to the binding ontology, which is the core of the bindings question.

Briefs read; now sampling the current YAML bindings and handler registry to see where the per-binding Python lives.

I read all four briefs, then checked them against the binding YAML, `catalog.py`, `resolver.py` and the places that dispatch on actions, so you can see where the code sits relative to the plans.

## Where the briefs agree

They agree more than it first looks:
- **Span brief and staged-pipeline brief:** bindings pick and configure registered Python capabilities, and no package code ever runs.
- **Ontology brief:** defines what an entry is.
- **Bibliography brief:** adds a requirement the others don't state: "a new branch is a binding change, not new control flow." So bindings must carry identification facts too: `.bbl` fingerprints, and which packages a class loads.

§3.9's template bindings need the same package-level facts (options → loads, write sets). So the library needs two levels:
- **Package level:** identity, version range and pins, options and their effects, loads, fingerprints, write sets.
- **Construct level:** one entry per command or environment.

Today's YAML only half has the package level.

## What the code shows about the "adapter" problem

It isn't literally one adapter per binding. The variation leaks through four overlapping string selectors:
- `family` (17 values)
- `action` (about 34)
- `grammar.handler` (about 50 in `reading_handlers.yaml`)
- `profile`

On top of that, a free-form `metadata` dict becomes `tex_mechanics`, and consumers read it by key.

**Where the strings get interpreted:** action strings are handled by `if action == …` checks in about ten modules. `session.py::_command` alone has about 25 such checks. `asset_reference` is handled separately in `session.py`, `prepare/assets.py`, `deferred.py` and `dependencies.py`. So every new behavior means a new string plus branches in several files. That's the mechanism behind the proliferation.

**The registry is only on paper:** `reading_handlers.yaml` lists a status and a description for each handler but doesn't connect it to an implementation. The catalog keeps raw dicts, checks them with about 225 lines of hand-written validation, and the resolver deep-copies them every time it resolves a command.

**Symptoms in `fancyvrb.yaml`:**
- `Verbatim`, `BVerbatim` and `LVerbatim` are three copies that differ only by name.
- Terminators are hand-written regexes with double escaping, including inside the factory recipe (`'\\end[ \t]*\{{{name}\}}'`).
- `\CustomVerbatimCommand` and `\RecustomVerbatimEnvironment` use a different shape (`syntax`, `registers`, `inherit_from_arg`), and I found nothing in the code that reads `inherit_from_arg`.

**The good news:** the dispatcher already has a reusable core: literal scanners, argument scanning, option processing, definition capture. The capabilities exist; they just can't be addressed as single things.

## Proposed framework

1. **The signature is the spine.** Give each construct one xparse-style signature in ltcmd's language (`s o o m`), with named arguments. Extend it for reading modes ltcmd lacks: literal bodies with terminator rules, semi-verbatim, filenames, keyval schema references. The same parser then handles an author's `\NewDocumentCommand`. For most CTAN commands, the signature plus "no reading effect" is the whole reading side. So covering a package for preparation is far cheaper than covering it for interpretation.

2. **One entry, with separate facets per stage:**
   - reading: argument modes, reading effects, write sets
   - preparation disposition: retain, inline, replace, sink when justified, or require
   - observation: which dependency, asset, citation or bibliography-site facts it produces
   - interpretation (later): kind, emission, state, fidelity

   Today `action` mixes all of these. `source_input` is a source effect, `citation` is an observation, and `opaque` (32 uses) is just the disposition "retain". Add the interpretation facets only when the witnesses need them.

3. **Capabilities are a closed set of types.** Each capability has a name, a typed parameter dataclass, and the stages it takes part in. Stage modules register their handlers (for example `@prepare.handles(SourceInput)`). Names resolve to types when bindings load, and a load-time check confirms that every capability has a handler for every stage it claims. With typed parameters, `tex_mechanics` goes away.

   Adapters exist because the only way to extend things is a new string plus scattered branches. If the capability is the only extension point, declared in one place, that stops. A binding that needs a capability that doesn't exist emits a capability request, which is the ontology's split between missing knowledge and missing engine capability.

4. **A template is a capability plus default parameters plus rules that derive the rest.** The literal-environment template takes a name and works out the terminator itself, so nobody writes a regex. `Verbatim`, `BVerbatim` and `LVerbatim` become one-line instances, and `\DefineVerbatimEnvironment` creates an instance of the same template at document time. A citation-command template covers natbib's eight commands.

   Span brief §4.3 already warns that the per-binding rules differ: alltt's `command_boundary`, comment's column-zero rule. Those become template parameters, not one shared regex.

5. **The authoring surface becomes just a front-end.** If one compiler emits the canonical records, YAML can stay as the first front-end, and the §3.8 bake-off turns into a cheap experiment instead of a blocker. Once signatures and derived terminators remove most of the escaping, YAML and Python may come out closer than they looked.

## Refactor sequence

Every step is a pure refactor with one gate: rerun the specimen batch and require byte-identical `master.tex`, provenance and manifest, plus the full test suite. You already have the infrastructure for this, and it's the cheapest strong check available.

- **R0 – consumption map.** Map every YAML key and every action, family or handler string to the code that reads it. Delete dead keys and make undeclared keys an error. It's mechanical, so it suits a chip.
- **R1 – canonical records.** Frozen `PackageBinding` and `ConstructEntry` records for the reading, preparation and observation facets, built by one compiler from YAML. Validation moves into the compiler, and the catalog and resolver serve records instead of copying dicts.
- **R2 – make the capability registry real.** Strings resolve to types when bindings load, stage modules register their handlers, and the string branches get deleted one module at a time. `family`, `action`, `handler` and `profile` collapse into signature, capability and disposition.
- **R3 – signature strings.** Port `natbib`, `source_traversal` and `core_latex` to signature strings, and add `\NewDocumentCommand` if it comes cheaply.
- **R4 – templates.** Literal environment with its factory, and citation command; port the verbatim family. This is where the escaping goes away.

Then stop refactoring and let the next consumers add fields. The package-level facets get designed once, for §3.9 local-style identification and for bibliography identification together, because they're the same facet. The interpretation facets get added at staged-pipeline increment 5.

## Order against the other tracks

1. **R0–R4,** limited to the reading side.
2. **lib-ctan vendoring, alongside it:** kernel `.dtx` files, natbib, fancyhdr, geometry, the ams bundle, unicode-math, and the specimens' `.bst` files. Everything after this needs them as pins.
3. **§3.9 identification plus bibliography steps 1–2.** §3.9 removes the remaining preparation boundaries: DeadSalmons' `natbib.sty` and `fancyhdr.sty`, and Fractal's `neurips_2024`.
4. **Staged-pipeline increments 2–3:** the prepared-payload read, contexts, and the obligation inventory.
5. **Run the ontology bake-off and staged-pipeline increment 5 as one pass.** Their witness sets nearly match: the fancyvrb family and substitution, `\newtheorem` as a factory, amssymb and lexemes, `\citep` and structured output. One pass then settles both the authoring surface and the executor interface.

## Binding all of CTAN

Most of the volume per package is sinks, lexemes, wrappers, configuration keys, and constructors built from a few templates. Those are rows, not programs. The parts that look like programs are the language-feature packages: ltcmd, etoolbox, the keyval family, the package mechanism, and eventually expl3. Those are engine capabilities, written once and reviewed.

One tool worth building early: run the existing definition scanner over each pinned `.sty`. It already captures definitions without executing them, so it gives agents a deterministic surface inventory, which is also the denominator for coverage.

## Pushback and open points

- **The 32 `opaque` entries hide the kind decision.** That's fine for preparation, but they shouldn't count as "bound" in coverage.
- **`.bst` style bindings are a kind the ontology doesn't list.** The bibliography brief needs them. Add a "producer profile" kind to §3.2 so that track doesn't invent its own record shape.
- **Capability granularity is the real risk.** Too coarse, and the parameters turn into a mini-language, which is today's YAML problem again. Too fine, and templates turn into programs. The witnesses are where you find the right size, which is another reason not to design interpretation capabilities ahead of them.

Go ahead. To help you aim, here are the claims I'm least sure of, roughly from most to least load-bearing:

- **Facets on one entry vs. separate stage libraries.** I assumed one construct entry should carry its reading, preparation, observation and later interpretation knowledge, keyed by one signature. The alternative is separate per-stage libraries joined by name. That would keep preparation completely isolated from interpretation churn, at the cost of keeping the signatures in sync.
- **Capabilities as the only extension point.** This holds only if a reasonably small set of capabilities covers most of CTAN. If the right grain turns out to be fine, templates become programs and the authoring-surface question matters again.
- **Signature strings carrying reading modes.** Extending ltcmd's language for literal bodies, terminators and semi-verbatim might stretch it into something worse than a structured form.
- **Byte-identical specimens as the refactor gate.** It may be too strict if R2's collapse of the selectors is meant to fix known misbehavior, not just preserve it.
- **The ordering.** It puts the refactor before §3.9 identification, the bibliography track and the prepared-payload read. You might want a consumer first, so the records get designed against real demand instead of today's YAML.

Push on whichever of these matter, or on something I didn't list.

Looked at lib-symb's table schema and the Engine pool layout. Checking two more things before answering: LaTeXML's font maps (slot → Unicode tables) and its parameter-type vocabulary.

The primitives you're reaching for aren't TeX's primitives. That difference is the key to the whole problem.

## Why TeX primitives are the wrong layer

At the primitive level, notation has already become glyph addresses. In plain TeX, `\leq` is `\mathchardef\leq="3214`: class 3 (relation), math family 2, slot `0x14` in whatever font sits in that family. In amsfonts, `\mathbb{R}` ends in a family switch to font `msb` plus a slot. So expanding everything down to primitives *is* rendering, just without the drawing. Packages use TeX primitives to typeset. They use a different layer to say what things are.

## The layer you want: declarators

Packages state facts through a small set of declaration commands:

| Table | Declarators that write it |
|---|---|
| Math lexicon | `\DeclareMathSymbol`, `\DeclareMathDelimiter`, `\DeclareMathAccent`, `\DeclareMathRadical`, `\mathchardef`, `\DeclareMathOperator`, `\let` aliases |
| Math alphabets | `\DeclareMathAlphabet`, `\DeclareSymbolFontAlphabet`, `\DeclareSymbolFont`, `\SetSymbolFont` |
| Text symbols | `\DeclareTextSymbol`, `\DeclareTextCommand`, `\DeclareTextAccent`, `\DeclareTextComposite`, `\DeclareUnicodeCharacter`, `\chardef` |
| Counters | `\newcounter`, `\@addtoreset` and `\counterwithin`, `\renewcommand\the…` |
| Structure | `\newtheorem`, `\@startsection`, `\newenvironment`, `\newfloat`, `\DeclareCaptionType` |
| Commands | `\newcommand`, `\DeclareRobustCommand`, `\NewDocumentCommand`, `\DeclarePairedDelimiter`, `\newif` |
| Package mechanism | `\ProvidesPackage`, `\DeclareOption`, `\RequirePackage`, `\PassOptionsToPackage` |

**A table row is a declarator call with its arguments as columns.** Your lib-symb tables already work this way: the kpfonts rows' `note` column reads `re@DeclareMathSymbol mathrel`, so your extractor was already parsing at this layer. amssymb.sty is almost entirely `\DeclareMathSymbol` calls.

One declarator emulator then serves two purposes:
- **When authoring bindings:** run it over the pinned lib-ctan sources to extract tables. Each row cites the source line of its declarator call, so the evidence pins come for free, and agents review rows rather than write them.
- **At runtime:** an author's own declarations go through the same declarators into the same tables, e.g. `\DeclareMathOperator{\tr}{tr}`, `\newtheorem{lemma}[theorem]{Lemma}` or `\newcommand{\R}{\mathbb{R}}`.

The runtime loads tables and never a `.sty`, so this doesn't bring back the fallback. It extends the ontology brief's "templates shared with factories": declarators are the factories, tables hold what they produce, and templates interpret the rows.

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

## What this does to the bindings problem

A package binding becomes rows in declarator tables plus a residue: everything that isn't a declarator call, such as loops over lists, computed `\csname`s, option-dependent code and hooks. Templates, capabilities and requests all live in the residue.

You can measure this before designing anything. Run the definition scanner over lib-ctan and sort each package's top-level statements into declarator calls and program code. I'd expect symbol, font and theorem packages to be almost all rows, and tikz/pgf almost all residue. The actual split tells you how big the residue layer has to be, which is the real question behind the authoring-surface debate.

In terms of the earlier refactor plan, declarators are the first capabilities in the registry, and R1's canonical records are declarator tables. The expansion core belongs to interpretation, since preparation gets by with bounded effects. So it lands with the staged pipeline's resolver and executor increments, not before.

I couldn't tell from git which Engine pools or primitives are your additions, because the history shows every pool as added in your initial import. If any of your engine bindings are declarator-like or font maps, those are the most directly reusable pieces.

