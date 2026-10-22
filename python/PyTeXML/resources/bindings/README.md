# Bindings Taxonomy & Organization

This directory holds declarative reading contracts for the Python binding resolver.
The preparation pipeline does not yet dispatch through these contracts. Downstream
interpretation and XML capture remain separate consumers under development.

## 1. Architectural Taxonomy

Bindings are strictly partitioned into two tiers to prevent engine primitives and CTAN packages from mixing concerns:

```
python/PyTeXML/resources/bindings/
├── README.md
├── engine/                       # Core LaTeX 2e / TeX primitives (always active)
│   ├── core_latex.yaml           # Definitions, environment opener, inclusions, grouping, catcodes, conditionals
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
* **No operational policies** (whether comments or draft blocks should be stripped, kept, or routed to sidecars is governed by [preparation policy](../policies/README.md)).
* **No downstream projection configurations** (the existing LaTeXML-shaped examples are [experimental projections](../experimental/projections/latexml/README.md)).

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

Experimental projections reference binding-relative IDs such as `engine/verbatim`
and `packages/listings`. Local identities match filename stems; the containing
tier supplies the namespace. `requires_engine: engine/verbatim` references the
engine binding whose local name is `verbatim`. The projections are not the final
PyTeXML XML schema.

## 4. Resolver contract

[catalog.py](../../src/bindings/catalog.py) loads YAML and compiles reading knowledge
once. A catalog can be supplied to multiple `BindingResolver(catalog)` instances;
each resolver owns its document's package activation order and resolves occurrences
in memory. `BindingResolver()` creates its own catalog when none is supplied.
The catalog rejects missing/mismatched filename identities, duplicate
identities/construct names, malformed consumed sections, and missing profile/engine
references. Engine and package bindings follow the same filename rule. Engine
dependencies use qualified `engine/<name>` IDs; bare names and aliases are rejected.
`catcode_mutators.action`, `grouping.action`, `inclusions.behavior` and optional
`grammar.handler` reference
the [handler vocabulary](../registries/reading_handlers.yaml). That vocabulary
contains no duplicated command declarations and imports no executable code.
Reading state lives in [context.py](../../src/reading/context.py), and result types
live in [contracts.py](../../src/reading/contracts.py).
[Mouth profiles](../profiles/mouth/README.md) contain the authoritative
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
`endlinechar`, expl3 saved state, and stored local definitions. Repeated `\ExplSyntaxOn` reapplies its
assignments while preserving the saved baseline. `StructuralDispatcher` owns active
execution routing, source group and conditional pairing, the supported environment header scan,
and synchronization of a live reader's `endline_char`. Literal profile entry/exit
and body scanning are delegated to `LiteralScanner`. Interpolation plans require
further literal handling and cannot be
applied as ordinary context mutations. Terminator metadata is not a scanner.

## 5. Initial literal grammar consumers

[StructuralDispatcher](../../src/reading/dispatcher.py) consumes a narrow portion of
these contracts without importing the catalog implementation. `environment_name`
reads a non-expanding braced name and resolves its environment; `inline_character`
handles a dynamic character delimiter; `token_delimited` scans an exact sequence
of character tokens. The latter two handlers live in the delegated
[LiteralScanner](../../src/reading/literal_scanner.py). These are reusable Python algorithms selected by YAML,
not package-specific Python implementations. The preparation pipeline does not
call them yet.

The kernel entries specify the optional star, the starred binding identity,
delimiter-prefix spaces and local delimiter category. Space skipping follows
`@sverb` in the [LaTeX kernel](https://github.com/latex3/latex2e/blob/develop/base/ltmiscen.dtx)
since 2020/10/01. Tab delimiters remain outside this initial supported grammar.
Kernel block terminators explicitly use `matching_domain: mouth_tokens` and
`boundary_mode: token_sequence`; their definition-time categories come from the
declared `terminator_baseline` plus the literal profile. The initial handler
requires `regex_pattern` to equal the escaped `exact_string`. It does not ignore
a different regex rule or claim that these two fields are interchangeable.

Package line-based terminators, options, interpolation and factories remain
explicitly unsupported by this dispatcher. Activating an overriding package
cannot silently select the kernel scanner. A resolved reading profile describes
knowledge; it does not, by itself, prove that a runtime handler supports it.

## 6. Grouping and immediate effects

The structural dispatcher routes `assign_catcode`, `expl3_lexical_enter`,
`expl3_lexical_exit`, `push_lexical_scope` and `pop_lexical_scope`. It uses resolved
data without hardcoded command spellings. These are local effects applied before
the next token is read; already converted lookahead and the current line's
captured `endlinechar` remain intact. Dynamic assignments, global prefixes and
unsupported combinations establish a diagnostic boundary.

Each grouping declaration supplies `state_management.group_kind`: `simple` for
brace-category groups, `semi_simple` for the core `\begingroup`/`\endgroup` pair.
Aliases can select a declared group kind independently of command spelling.
The catalog validates this field; the resolver preserves it in
`StateManagementRule`. The structural dispatcher checks pairing and owns the
source group stack. `ReaderContext` owns lexical snapshots and exposes their
depth; it does not infer group kinds from source. Caller-created scopes cannot
be popped by the source dispatcher. Environment-name braces are scanned as
arguments, and literal bodies never route their apparent effects or group tokens.

Reading result records and the narrow `ReadingKnowledge` protocol live in
[contracts.py](../../src/reading/contracts.py). This remains a preparation-oriented
execution surface, not the future expansion or asynchronous binding contract.

## 7. Stored primitive definitions

Commands in the `stored_definition` family declare `scope: local|global` and
`grammar: {handler: primitive_definition, expansion: none|full}`. The catalog
validates these fields; the resolver preserves them without applying the
declaration. `StructuralDispatcher` delegates the local, non-expanding form to
[DefinitionScanner](../../src/reading/definition_scanner.py). Global or expanding
forms are rejected before scanning arguments. This vocabulary describes the
current primitive forms, not a schema for arbitrary definition factories.

The scanner implements the parameter/body collection rules from TeX82's
`get_r_token` and non-expanding `scan_toks` in
[tex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web).
It accepts a control sequence or active-character target, consecutive parameters
1–9, delimited parameter text, balanced category-driven body groups, doubled
parameter markers, and the special parameter-ending `#{` form. Group and parameter
characters follow their current categories; parameter numbers require OTHER-category
ASCII digits. It reports malformed input without TeX's token-insertion repairs.

`StoredDefinition` holds original opening/body/closing and parameter-text spans,
the target token, raw parameter/body token tuples, parameter count and optional
`hash_brace` token. The tuples preserve lexical input: `##` is not collapsed,
references are not substituted, and the hash brace is not synthesized into the
body. They are not yet an expansion-ready replacement list. Token occurrence
spans and categories remain valid after later lexical changes.

The scanner reads in `STORED_DEFINITION` mode and returns a capture without
resolving or executing body commands or publishing a definition. Only the
dispatcher installs a successful capture. Context scope journals restore prior
meanings without copying every stored definition at each group. Active characters
and same-spelled control symbols have separate keys. Failed captures leave prior
meanings intact and preserve the declaration's source as boundary residue.

Lookup checks stored meanings before selecting binding handlers, including implicit
paragraph tokens and the entry/exit commands of a directly dispatched environment.
A stored invocation currently stops at an explicit boundary; deciding whether it
is reading-neutral requires later analysis. This is lexical capture and scoped
shadowing, not complete TeX meaning validation: prefix/outer/protected semantics,
LaTeX declaration wrappers, global assignments and expansion remain future work.

## 8. Bounded conditionals and skipped text

`reading.conditionals` describes command meanings with a small validated schema:

```yaml
conditionals:
  - {name: "\\iftrue", role: opener, evaluation: always_true}
  - {name: "\\iffalse", role: opener, evaluation: always_false}
  - {name: "\\ifnum", role: opener, evaluation: deferred}
  - {name: "\\else", role: alternative}
  - {name: "\\or", role: case_alternative}
  - {name: "\\fi", role: terminator}
```

Openers require `evaluation: always_true|always_false|deferred`; other roles have
no evaluation field. Legacy action fields and combined grammar/effect declarations
are rejected here. The kernel inventory enumerates all TeX82 conditional tests;
extension primitives need explicit additional declarations. `\newif` is a
deferred command factory, not a nesting opener. Command spelling is not an
algorithmic test: a binding can declare another name with one of these meanings.

`resolve_command` returns the rule in an `EffectiveReadingProfile` for active
routing. `resolve_conditional` supplies only the nesting rule for skipped scanning,
without resolving unrelated arguments or effects. Both use the same winning
declaration across active packages and engine bindings; a nonconditional package
override suppresses the old conditional meaning. `None` means no conditional
meaning in this established knowledge context, not a guess about an undiscovered
package. The runtime checks stored author meanings first. Dynamic aliases and
new conditional factories require later support, and do not execute today.

`StructuralDispatcher` owns conditional state and evaluates only constant rules.
It declines deferred predicates before scanning arguments. Its stack is independent
of groups: conditionals create no lexical scopes. A successful skipped scan returns
source coverage and the consumed delimiter for the dispatcher to route; it does
not change conditional state itself. No source text is copied or rewritten.

[SkippedBranchScanner](../../src/reading/skipped_scanner.py) follows the nesting
principle of `pass_text` in [TeX82's tex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web):
read mouth tokens without expansion, increment for conditional opener meanings,
decrement for nested terminators, and return at an eligible outer delimiter.
Other tokens do not execute, even apparent definitions and verbatim openers.
False then-branches stop at `else`, `or` or `fi`; an outer `or` is a diagnostic for
these boolean conditionals. A discarded else-branch continues to `fi`, ignoring
intervening outer `else`/`or` tokens as TeX does. An extra `else` in an executing
alternative is a diagnostic. Comments, `^^` conversion and current catcodes still
apply; outer-macro checks and engine error recovery are not implemented.

`SkippedRegion` retains an exact extent, its owning conditional opener span and
`then|else` branch identity. Executed delimiters are separate events. Unfinished
skips retain unknown coverage from their start; completed empty branches still
retain a record. `ReadingCoverage.query("skipped")` exposes established inactive
extents without authorizing deletion. Production preparation does not use this
dispatcher or scanner yet.
