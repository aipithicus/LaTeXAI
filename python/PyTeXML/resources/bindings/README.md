# Bindings Taxonomy & Organization

This directory holds declarative reading contracts for the Python binding resolver.
The preparation pipeline dispatches through supported reading contracts. Downstream
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
    ├── natbib.yaml               # Citation-key argument grammar; no rendering or option execution
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
  the preparation source owner's responsibility, using dispatcher command records. Later first-time activations take
  precedence; requesting an already active package does not reorder it.
  `source_command_syntax()` can also expose a unique provider's argument shape
  without activation. Such a header stays a `DeferredRegion`, with an optional
  observed command and binding ID. Preparation can use its literal citation keys
  provisionally; this does not authorize effects or dependency execution.
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

The [reading-control audit](reading-controls.md) records the current consumers,
composition order, descriptive invariants, and retained `deferred_phase2`
knowledge. It also documents catalog indexing and occurrence ownership.

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
binding's lexical settings, construct settings, enabled option profile layers,
and concrete supported option effects, in
that order. It returns data containing immutable compiled catcode layers,
reader parameters, argument grammar, termination rules, source-capture mechanics,
and classification. Lexical categories such as `opaque_literal` are distinct from
policy roles such as `code_listing` and `external_verbatim`.

Supported `commandchars` and `commentchar` values produce concrete category
assignments. Listings escape options produce explicit delimiter plans; they are
not global category changes. Unknown options, unsupported code hooks, and combined
interpolation modes return `UnresolvedBindingResult`. Only options explicitly
classified by the owning binding can pass through as non-reading metadata.

Command lookup includes active package bindings. Bounded `\catcode` arguments and
declared environment factories route to scanners. Unimplemented configuration
commands and factories return explicit unresolved results rather than successful empty profiles.
There is no macro expansion or native-engine fallback here.

Conditional entries separate nesting `role`, predicate `evaluation`, and optional
`capture_operands` (currently zero or two source tokens). The latter admits a
preparation-only envelope when evaluation is deferred; it does not evaluate or
expand the operands. The dispatcher owns that routing. The generic conditional
scanner checks protected-active versus skipped-token marker agreement before
resuming, while the resulting region retains an entry-state assumption. Missing
capture recipes remain explicit boundaries. Command spellings and operand counts
belong in YAML, not scanner switches.

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
not package-specific Python implementations. The preparation pipeline calls them through its ordered source traversal.

The kernel entries specify the optional star, the starred binding identity,
delimiter-prefix spaces and local delimiter category. Space skipping follows
`@sverb` in the [LaTeX kernel](https://github.com/latex3/latex2e/blob/develop/base/ltmiscen.dtx)
since 2020/10/01. Tab delimiters remain outside this initial supported grammar.
Kernel block terminators explicitly use `matching_domain: mouth_tokens` and
`boundary_mode: token_sequence`; their definition-time categories come from the
declared `terminator_baseline` plus the literal profile. The initial handler
requires `regex_pattern` to equal the escaped `exact_string`. It does not ignore
a different regex rule or claim that these two fields are interchangeable.

The `physical_line_literal` handler matches `regex_pattern` against each physical
line, honoring column-zero, trailing-content and discarded-suffix rules. The regex
takes precedence over `exact_string` for this handler. `body_start:
next_physical_line` discards a package-declared opening-line suffix. Non-reading
options pass through; interpolation, code hooks and incompatible live catcodes
remain pending. Activating an overriding package cannot silently select the kernel scanner.
A resolved reading profile describes
knowledge; it does not, by itself, prove that a runtime handler supports it.

## 6. Grouping and immediate effects

### Ordered literal configuration

A binding may declare `reading.configuration` alongside `option_resolution`.
It names the state namespace, style-reference key, name normalization, separate
definition/assignment scopes, mutually exclusive reading keys, and bare-key
defaults. The existing `reading_affecting_keys` and `non_reading_options` classify
values. A configuration command selects `define_configuration` or
`apply_configuration`, a `source_arguments` grammar and temporary header catcodes.
No Python command names or package imports are encoded in this mechanism.

`ConfigurationState` keeps immutable ordered token recipes, scoped effective
values, and scope journals. Application expands only named configuration recipes,
with cycle/missing-name diagnostics; it never expands TeX macros. Styles resolve
at use, assignments apply in source order, and literal-local options do not mutate
document defaults. Definitions and assignments return their original source span.
For listings, definitions are global and settings are local, as specified by the
vendored package; escapeinside and escapechar replace the same effect.

Preparation can capture one TeX interpolation mode in physical-line literals.
`LiteralRegion.interpolations` contains deferred child units, not executed TeX.
Those children have unknown structural coverage and final artifact locations.
Entry-state capture does not establish arbitrary macro effects inside escapes.
Strict execution, math/combined modes, dialect/aspect loading and inline listing
grammar remain explicit limits. Formatting values and language selection are
retained as tokens; this does not implement the language driver or typography.

The structural dispatcher routes `assign_catcode`, `expl3_lexical_enter`,
`expl3_lexical_exit`, `push_lexical_scope` and `pop_lexical_scope`. It uses resolved
data without hardcoded command spellings. These are local effects applied before
the next token is read; already converted lookahead and the current line's
captured `endlinechar` remain intact. The `integer_catcode_assignment` bridge
routes to the engine's shared integer scanner: signs, decimal/octal/hexadecimal
and backtick constants, internal category values and scoped `\chardef` values.
An unconsumed terminator keeps its captured category; `\relax` is returned to
execution. Macro expansion, other internal quantities and global prefixes still
establish a diagnostic boundary. The existing Unicode category-table domain is
preserved; `\chardef` accepts the TeX82/e-TeX range 0..255.

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
Knowledge providers expose `source_command_syntax()` explicitly and return `None`
when no unique source-command grammar is available; inspection never activates
the provider. Shared capture operations are `ArgumentScanner.next_nonspace()`
(consume SPACE-category tokens), `DefinitionScanner.read_body()` (capture after
an opening group), and `StructuralDispatcher.identify()` (assign unit identities
to already captured items). These operations do not expand or execute bodies;
execution routing remains in the structural dispatcher.

### Scoped environment recipes

An `environment_factory` declares `action: define_environment`, a
`source_arguments` grammar, and a bounded recipe in `metadata`. The recipe names
the environment-name argument, a fixed base or base argument, optional bound
options, the required base binding identity, variants, and terminator templates.
`{name}` in the regex template receives a regex-escaped name; it is never executable
code. The catalog validates these consumed fields.

The dispatcher installs declarations in `ReaderContext`; scope journals restore
previous meanings. `environment_registry.py` resolves them using the existing
base handler. Initial recipes cover `\DefineVerbatimEnvironment` (including the
starred variant), `\excludecomment`, and `\includecomment`. They do not implement
arbitrary author environment definitions or general macro expansion.

Included comments use the package's raw-line capture followed by body input,
without implicit grouping, as specified in the
[comment 3.8 manual](https://mirrors.ctan.org/macros/latex/contrib/comment/comment.pdf).
The dispatcher replays a bounded window over the same buffer and source basis,
without temporary files. This separates boundary capture from body execution.

## 7. Stored definitions

Commands in the `stored_definition` family declare `scope: local|global` and
`grammar: {handler: primitive_definition, expansion: none|full}`. The catalog
validates these fields; the resolver preserves them without applying the
declaration. `StructuralDispatcher` delegates local forms to
[DefinitionScanner](../../src/reading/definition_scanner.py). The definition
operation supplies the shared expansion cursor for `\edef` replacements;
the scanner alone does not expand. Global forms are rejected before scanning
arguments. This vocabulary describes the
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
body. Invocation compiles supported parameter references directly into frozen
token frames. `expanded_tokens` separately holds an `\edef` replacement;
`replacement_tokens` selects the operational sequence without changing the
authored capture. Token occurrence spans and categories remain valid after later
lexical changes.

The scanner reads in `STORED_DEFINITION` mode and returns a capture without
executing body commands or publishing a definition. Expanded definitions resolve
body meanings through the supplied expansion consumer. Only the definition
operation installs a successful capture. Context scope journals restore prior
meanings without copying every stored definition at each group. Active characters
and same-spelled control symbols have separate keys. Failed captures leave prior
meanings intact and preserve the declaration's source as boundary residue.

Lookup checks stored meanings before selecting binding handlers, including implicit
paragraph tokens and the entry/exit commands of a directly dispatched environment.
A stored invocation stops at an explicit boundary in strict execution mode.
Preparation first probes for a complete package-load request using shared
expansion. Supported requests have literal token arguments and publish through
the existing loader; failed probes restore the cursor without publishing effects.
Otherwise preparation captures the invocation and records the need for later
interpretation. It does not establish that the invocation is reading-neutral.
This is lexical capture and scoped
shadowing, not complete TeX meaning validation: prefix/outer/protected semantics,
other declaration factories, global assignments and broader expansion remain future work.

The temporary `expansion_control` family currently selects only
`grammar: {handler: noexpand}`. Its Python operation reads one raw token and
suppresses expansion for that return only; it has no standalone execution role.
Aliases and shadows follow the same mutable meaning lookup as other operations.

The `command_definition` handler captures the bounded LaTeX command forms from
[ltdefns.dtx](https://github.com/latex3/latex2e/blob/main/base/ltdefns.dtx):

```yaml
- name: "\\newcommand"
  family: stored_definition
  scope: local
  grammar:
    handler: command_definition
    expansion: none
    target_requirement: absent
    forbidden_names: [relax]
    forbidden_prefixes: [end]
```

The renewal recipe uses `target_requirement: present` and empty forbidden lists.
Only local, non-expanding recipes are valid. The grammar accepts an optional star,
a single literal control sequence (braced or unbraced), an optional literal digit
0–9, an optional default when the count is positive, and one raw token or balanced
group as the replacement. This follows the long argument capture in the kernel's
`\@argdef` and `\@xargdef`; the replacement is never expanded or executed here.
Computed targets/counts and other factories need separate resolution.

`CommandDefinition` extends `StoredDefinition` with the declaration identity,
star flag, target/count/default arguments, `body_braced` and target-check status. It records the
logical authored signature, not the kernel's generated helper definitions.
`parameter_tokens` is empty; `parameter_text` spans the authored header after the
target. Bodies and defaults retain definition-time tokens. Body parameter checks
reuse primitive parameter validation within the captured argument; default parameter markers must be doubled because the
kernel stores the default in a parameterless helper. The star is metadata for
later invocation argument scanning, not an instruction to execute the body now.

The scanner returns `target_check: unchecked`. Active dispatch checks available
local meanings and bindings, rejects a known new-command collision, then marks the
capture `known_present` or `unverified` before registration. These are knowledge
states, not a complete implementation of LaTeX's definedness tests. No binding is
not proof of no command. Preparation emits an interpretation requirement for each
unverified precondition, including selected option-body declarations, without
blocking the master. Deferred-environment scanning captures syntax only and never
performs this active registration. Invocation expansion remains out of scope.

### Collecting-environment declarations

[environ.yaml](packages/environ.yaml) is grounded in the package's v0.3 TeX source,
with source URL and SHA-256 recorded in its identity. It uses the generic
`collected_environment_definition` family and handler, `scope: local`, and the
same expansion/target/reserved-name fields as command declarations. Its metadata
selects `balanced_environment_tokens`, names the begin/end control sequences,
and supplies scoped setting keys plus initial body-name and final-code defaults.
There are no package-specific Python implementations or executed YAML templates.

`EnvironmentDefinition` keeps the authored count/default, processing-body tokens,
final-code tokens, body-command name, source spans, target-check status and unit ID.
Its opening/body/closing partition includes an authored optional final-code suffix
in closing. An inherited final-code setting retains that setting's source span;
binding defaults are named commands, not fabricated source tokens. These captures
are not compiled helper macros. `capture_setting` is a generic action over one
literal control sequence or a braced token list; the context journals it locally.

`StructuralDispatcher` installs declarations and owns all scope and routing
decisions. `EnvironmentScanner` only scans. At an established invocation it
collects under entry catcodes, respecting brace depth and counting ungrouped
begin/end tokens. Only the outer closing name is checked at collection time,
as in the package's collector; nested environment validation is later work.
Closing names must be braced and the outer name must be literal. Arguments remain
inside the frozen body until interpretation, and no literal/conditional handler
runs while collecting. A `CollectedEnvironment` remains a deferred region, linked
to its declaration; preparation exposes `definition_unit_id` on its requirement.
Its source is not trimmed or substituted. The package's trimspaces dependency is
relevant to future interpretation, not a native fallback during preparation.

Unknown execution still carries the existing entry-state assumptions. These
bounded handlers do not establish arbitrary macro effects, compile replacement
lists, execute processing/final code, or support the low-level collector APIs.

## 8. Bounded conditionals and skipped text

`reading.conditionals` describes command meanings with a small validated schema:

```yaml
conditionals:
  - {name: "\\iftrue", role: opener, evaluation: always_true, capture_operands: 0}
  - {name: "\\iffalse", role: opener, evaluation: always_false, capture_operands: 0}
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
extents without authorizing deletion. Production preparation consumes these
dispatcher and scanner records through its cached source session.

## Source traversal grammar

Core declarations live in engine/source_traversal.yaml; graphicx and import
each own one package binding. These are reading contracts, not the future
expansion/XML schema. Command spelling and ordered argument shapes are declarative;
ArgumentScanner implements the shared algorithms.

A source_command declares an action and a source_arguments grammar. Each argument
has a unique name and a kind: braced, optional, star, filename, or control_sequence. The scanner retains
spans and unexpanded tokens. Resource names require literal characters.
An optional `role` is `unknown` (the default), `data`, `diagnostic`, `stored`, or
`branch`. Roles describe the captured argument's use; they are not permission to
execute it. In particular diagnostic expansion is deferred even though dependency
spellings in a message are not dispatched as document commands. Active authored
redefinitions take precedence over the original binding's argument roles.

An optional `literal_categories` list selects the character-token categories
admitted by that argument's literal-value operation. It does not mutate catcodes,
expand control sequences, admit active characters, or change other arguments.
Legacy option lists and names admit alignment-category `&` this way; filename
rules retain their existing bounded contract. Invalid/duplicate categories,
unknown roles and unsupported fields are configuration errors.

`branch_test` is a bounded source-command action with metadata
`{predicate: loaded, kind: package|class}` and exactly three braced arguments:
`name` with role `data`, and `then`/`else` with role `branch`. The dispatcher asks
the ordered source-load store, never the binding catalog, for its decision. It
routes the selected frozen tokens and links both branches to the decision unit;
unknown answers preserve the complete command. The initial recipes follow
[latex2e ltclass.dtx](https://github.com/latex3/latex2e/blob/develop/base/ltclass.dtx);
diagnostic argument recipes follow
[lterror.dtx](https://github.com/latex3/latex2e/blob/develop/base/lterror.dtx).
This is a reading contract, not a general expansion or XML construction schema.
A structural_environment declares the same header grammar and optional metadata.
The dispatcher owns environment grouping; the source owner handles resource requests.
Bounded opaque arguments retain unexpanded source. Their expressions become
located requirements; dependencies inside those arguments require their owning
context before they can be resolved. A computed resource argument defers that
command while traversal continues beyond it.

Bindings activate at the declaration, never retroactively. Local styles/classes
are scanned from cached source under declared package catcodes and emitted separately;
they are not replaced by same-named external bindings. Missing external bindings
become requirements and do not prevent later inputs from being assembled.
`source_command_syntax` can inspect a unique inactive package's argument grammar
to capture a pending source command; this never activates or executes the binding.
Inactive literal/effect handlers do not use that observational route.

The dispatcher owns both strict execution routing and its explicit preparation
capture mode. Deferred regions retain entry-catcode assumptions and remain unknown
to structural coverage. Actual unsupported reading operations still produce
boundaries; full package semantics and general macro expansion remain downstream.
