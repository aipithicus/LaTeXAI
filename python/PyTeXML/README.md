# PyTeXML

Native Python preparation and reading machinery for a future manuscript compiler.
Preparation builds `master.tex` and its required resources; general macro
expansion and XML interpretation belong to later development.

## Current source organization

| Location | Responsibility |
| --- | --- |
| [`src/reading/`](src/reading) | Reusable N/M/S reader and cursor, structural dispatcher, literal/definition scanners, source intervals and coverage queries, regex catcode rules, mouth profiles, and scoped document state |
| [`src/bindings/`](src/bindings) | Reusable binding catalog and document-local resolution/package activation |
| [`src/prepare/`](src/prepare) | Cached source traversal, dependency resolution, emission, bibliography, assets, provenance, and publication |
| [`src/validation/`](src/validation) | Optional paired rendering and relocation qualification in disposable workspaces; independent of preparation |
| [`src/source_io.py`](src/source_io.py) | Run-scoped source cache, strict decoding and malformed-byte diagnostics |
| [`src/event_log.py`](src/event_log.py) | Reusable structured events, bound context, explicit locations and buffered JSONL sinks |
| [`src/bibtex.py`](src/bibtex.py) | Reusable BibTeX parser and data model |
| [`src/assets.py`](src/assets.py) | Image inspection and individual asset conversion |
| [`src/yaml_io.py`](src/yaml_io.py) | Strict YAML mapping loading, with schema validation left to each consumer |

Within preparation, [session.py](src/prepare/session.py) owns one ordered
multi-file traversal through the structural dispatcher. [Discovery](src/prepare/discovery.py)
selects the root from cached buffers; [inventory](src/prepare/inventory.py) exposes
the same traversal's manifest. A [project survey](src/prepare/survey.py) also reads
every indexed TeX/code/BBL source from the shared cache, retaining candidate work
in unvisited files, stored bodies and beyond reading boundaries. Survey candidates
do not become active dependency edges. Each inclusion has its own reader occurrence;
physical source files are read once per session, including local code and bibliography
resources. Package bindings activate at their declarations. Active local styles
are scanned and retained separately, with resolved file references rebased.

[Emission](src/prepare/emission.py) retains exact literal/definition slices and
serializes established mouth events. Bibliography and image edits use captured
command arguments. [Provenance](src/prepare/provenance.py) records emitted
character intervals and occurrence identity, including mixed-source lines.
[Final locations](src/prepare/locations.py) attach prepared-artifact addresses
directly to units and requirements; using them does not require the provenance sidecar.
[Manifest records](src/prepare/records.py) share typed JSON shapes and derive their
source references from reader units. The [manifest](src/prepare/manifest.py) owns
requirement IDs, location finalization and reset, and publication-failure state.
Its unit-linked traversal includes dependencies, resources, metadata, lint findings
and related evidence. Lint separately verifies emitted repairs and pins deletion
cursors. Finalizing or clearing locations preserves source evidence and activity;
materializing an asset does not resolve its deferred interpretation.
The old regex discovery, inliner, pruner, normalizer and implicit-graphics scanner
have been removed.

[Bounded preparation lint](recipes/preparation-lint.md) projects established
reader and source-load diagnostics into `manifest.lint` and the structured log.
The default policy reports findings. An explicit repair policy can discard an
isolated catcode-15 character only after a local token/state check; structural
repairs and package declaration reordering remain review work.

[Publication](src/prepare/publication.py) builds the complete payload in a sibling
staging directory before replacing the output. Failed preparation leaves the last
good master, manifest and assets intact, with the attempted run appended to the log.
New events go to `preparation.jsonl`; existing text logs remain historical evidence.
The [structured logging contract](recipes/structured-logging.md) describes the
shared primitives and how later stages can log against finalized `master.tex`.
Successful replacement removes stale payload files. Existing-directory replacement
uses backup/publish renames with rollback on error: on Windows there can be a brief
interval where the destination directory is absent, but it never contains a mixed
generation. A process crash during that interval may leave the backup in the named
staging directory; this is exception-safe publication, not a crash-atomic directory
exchange. EOF cursors travel as zero-width emission pieces, so their final addresses
remain correct after trailing discards, inlining and asset/bibliography edits.

Import components through their owning modules, for example:

```python
from src.reading.tex_reader import TexReader
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
```

To reuse loaded and compiled knowledge across documents:

```python
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver

catalog = BindingCatalog()
first_document = BindingResolver(catalog)
second_document = BindingResolver(catalog)
```

Each resolver owns its active-package order; each reading context owns its
catcodes and scope state. Resolution treats the shared catalog as read-only.
`BindingCatalog` accepts explicit binding/profile directories when needed.
Reading contexts and result types live under `src.reading`, independent of the
catalog loader and the preparation workflow.

Package initializers do not import the pipeline or image libraries. Internal
imports use package-relative paths. Bare-module imports and direct execution of
individual source files are no longer supported; use module execution below.

## Configuration and integration status

All YAML libraries live under [resources/](resources/README.md), organized by owner
and intended consumer:

| Location within `resources/` | Responsibility |
| --- | --- |
| [bindings/](resources/bindings/README.md) | Core/package reading knowledge; reusable across preparation and later interpretation |
| [profiles/mouth/](resources/profiles/mouth/README.md) | Baseline catcodes and reusable local reading configurations |
| [registries/reading_handlers.yaml](resources/registries/reading_handlers.yaml) | Reading-action vocabulary and implementation status; no command rules or executable imports |
| [policies/prepare.yaml](resources/policies/prepare.yaml) | Preparation role/event actions |
| [experimental/](resources/experimental/README.md) | Lossless/prose policy sketches and provisional LaTeXML projections |

Use `load_policy("prepare")` for the preparation preset. Experimental policies
require an explicit file path. The old `preflight`/`compact` names and old resource
directories have no compatibility fallback. Resource identities match filename
stems, with directories supplying namespaces; see the
[naming convention](resources/README.md#naming-and-references). Regex reading rules
are unchanged.

The preparation entry point uses the reader, dispatcher, binding resolver and
source coverage. Original manuscript sources are never edited. Its dispatcher
uses `preparation=True`: ordinary unbound commands, stored invocations and math
are preserved for interpretation while later literal inputs continue to assemble.
Missing external package bindings become located requirements. A computed filename
defers that command, not the rest of the manuscript. The strict dispatcher API
still stops when it cannot establish execution behavior.

The manifest separates `requirements` (with a stage), actual preparation
`unresolved` diagnostics, source-visible dependency resolution
(`source_dependency_closure`), and full `dependency_closure`. A preparation can
finish with downstream interpretation/binding requirements. That is not proof
of expanded dependency closure or compilation. `reading_assumptions` records the
entry-catcode assumptions used for unbound behavior; `source_survey` records
independent per-file observations, not execution. Deferred spans remain unknown
in structural coverage even though their text has been captured.

After a reading barrier, the independent survey uses the reusable
[source observer](src/reading/observer.py) to retain structured headers under its
declared entry-profile assumption. It captures option/definition headers and known
literals without running them. These candidates have unresolved activity; they
never become active dependency edges merely because their syntax was recognized.
`\InputIfFileExists` captures the filename and both branches. Present local files
with empty branches use the ordinary cached input path. Other cases remain located
requirements: absence from the source inventory does not establish absence from
TeX's external search path, and a nonempty found branch must run before the input.

`uncertainty_causes` records witnessed invalidations of tracked reading state.
Requirements and diagnostics link through `cause_ids`; each cause has its own
unit reference and finalized payload locations, including retained code artifacts.
Repeated source occurrences remain distinct. No raw-source sidecar is needed to
follow these links downstream, and publication failure clears their artifact
locations along with all other unit-linked records. The journal emits the same
ids and cause records. Ordinary deferred expressions do not grow this table when
there is no tracked state to invalidate.

Activity, binding availability and payload delivery are independent. Reader units
and their requirements carry `activity`: `reached` identifies an encountered
declaration/invocation (not execution of its stored body), `skipped` identifies a
discarded branch, `stored` identifies captured replacement code, `data` identifies
declared data/diagnostic arguments, and `unresolved` identifies unknown activity.
`activity_evidence` records the reason and links to the owning unit and controlling
decision, where applicable. Argument roles come from YAML rather than containment
alone. These unit links resolve to finalized artifact locations in the manifest.
Package requests record `binding_available` and `binding_activated`, including for
local package copies; these do not determine whether their declaration was reached.
Local source still gets scanned and retained when its reading binding activates.
Requirements carry `dependency` (`none`, `possible`, `required`) and `next_step`.
`materialization` is `pending`, `prepared`, `not_required`, or `undetermined` for
a dependency whose owning context has not established a resource request.
`materialization_status` summarizes known payload requests, not expanded dependency
closure. Missing citation-provider knowledge belongs to the binding stage; an
established unprepared image/input still has pending materialization. A dependency
mention inside unknown code needs argument/branch resolution first; one inside a
stored definition waits for macro invocation. Diagnostic arguments are retained
as data, with any diagnostic expansion deferred, without treating message text as
file-load commands. `remaining_work` counts requirement and diagnostic records by
their next step; a diagnostic and its linked requirement remain separate records.
Converted observed images retain unknown activity and an interpretation requirement without keeping
preparation partial merely because their enclosing environment is uninterpreted.

Each retained-code input owns a recovery checkpoint. An unsupported nested style
returns to its immediate caller, allowing subsequent source-visible declarations
to be discovered under the recorded entry-state assumptions. Recovery preserves
the child and reports its missing effects; it does not execute its unread suffix.

YAML conditional rules may select `character_equal` or `category_equal` predicates
with two source operands. The reusable predicate reader admits literal characters
and captured, argument-free, single-token definition chains. Categories come from
definition time; scopes and redefinitions come from the current reader context.
Cycles, arguments, empty/multi-token replacements and unknown meanings defer the
test without consuming operands. The dispatcher alone selects/skips branches.
Definitions and test headers remain source-preserved; no substituted macro body
is written to the master. `conditional_decisions` links each result to its unit
and supporting definition units. These are source-visible decisions under the
manifest's reading assumptions, not proof about hidden effects of arbitrary code.
The kernel `if@twoside` rule supplies nesting without guessing its class-dependent
truth. Bounded `\let` copies current local meanings without expanding the donor:
stored definitions, booleans/setters and resolved reading handlers can be aliased.
Unknown donors and character meanings are captured explicitly; their invocation
requires further interpretation. Assignment prefixes (including `globaldefs`)
stop before a potentially mis-scoped assignment. Numeric predicates and hook
execution remain deferred.

The integer-assignment scanner admits literal signed decimal `widowpenalty` and
`clubpenalty` values. YAML summaries for `flushbottom` and `sloppy` preserve bounded
reading state and leave layout computation downstream; `flushbottom` also installs
its real scoped meaning copies. Shadowed prerequisites invalidate a summary.
Geometry's binding currently records unresolved load effects and the optional
`geometry.cfg` lookup. Its presence is explicitly **not** evidence of load purity:
configuration, key expansion and begin-document work still need implementation.

The YAML `branch_test` recipe also supports literal class/package-loaded queries.
The reader uses ordered source-visible load facts, independently of binding
availability; it never looks ahead to activate a later package. Observed possible
loads and unread retained-code suffixes make negative answers unknown. Positive
facts remain usable. Decisions record their load evidence, uncertainty links and
source-visible assumption. The dispatcher routes the selected captured token
branch, preserving capture-time categories, while preparation emits the original
wrapper with skipped content omitted and admitted inputs inlined. General expansion
and character-mode literal parsing inside captured argument tokens remain deferred.

Unbound environments also retain `DeferredRegion.observations`: direct command
headers scanned using existing YAML argument grammars. Preparation can resolve
literal image filenames from these observations and emit their SVG derivatives
without expanding the environment or executing its body. Captured filenames and page
selections are rewritten; the surrounding environment source stays exact. The manifest keeps
these in `candidate_dependencies` and `candidate_images`, separately from established
active dependencies. A candidate shared with an active image is converted once.
Prepared candidates record their payload paths and retain the unresolved reading
context; they do not establish full dependency closure.

Captured command arguments and stored bodies can also supply literal asset
headers, without executing their enclosing code. The same asset plan rewrites
inlined source and retained local files. Comments, known literal regions and
diagnostic/data arguments do not supply dependencies. A raw literal encountered
inside already captured tokens stops that argument's observational scan; its
reading behavior remains deferred. Missing/computed filenames, ambiguous matches
and nonliteral/invalid page options remain located requirements. An unexecuted graphics search-path
or extension declaration prevents later candidates from using stale search settings.
Reading effects and conditional flow inside an unbound environment still require
resolution. This discovery uses the existing dispatcher cursor and source cache;
it adds no package-specific Python, YAML exception for an author's environment,
or compiler dependency.

Each image use has its own PDF page selection. Explicit `page=N` uses a
`figure_pN.svg` derivative; repeated uses of the same file/page share one conversion.
An extracted page is rebased to `page=1` in the retained graphics options, while
width, clipping and other authored options remain intact. Invalid PDF page indices
fail conversion rather than falling back to page one. Destination collisions are
disambiguated by source extension where possible, otherwise reported.

Multiple declared BibTeX databases are read together in declaration order, with
shared strings and cross-file parent references. Identical duplicate keyed records
can be selected once even when field order differs; conflicting records remain in
the canonical bibliography and require later resolution. Uncited metadata is kept
for enrichment. Multiple bibliography sites and BibLaTeX formatting remain separate
unfinished contracts.

The YAML contracts for `\providecommand`, `\renewenvironment`, `\AtBeginDocument`
and `\AtEndDocument` only capture their signatures and stored bodies. Preparation
preserves these blocks, does not test target existence, install replacements,
evaluate booleans in their bodies, or run/schedule hooks. No package-specific
implementation for these declarations is added to the dispatcher.

Unresolved predicates with a bounded source-operand recipe now use the reusable
[conditional scanner](src/reading/conditional_scanner.py). It retains both branches
and resumes after the closing delimiter when protected active reading and TeX-style
skipped reading agree on every conditional marker. It does not choose a truth
value or expand the operands. Each branch must return to its entry group depth.
The region has its own unit, unknown coverage, interpretation requirement and
final artifact locations. Unexecuted declarations invalidate affected meanings;
branch setters do not run. Entry catcodes and conditional meanings remain explicit
preparation assumptions, not a proof about arbitrary macro expansion.

Literal input and image headers inside these regions remain candidate dependencies.
Admitted inputs are inserted with separate occurrence/provenance records and cached
reads, including repeated inputs. Their contents must meet the bounded observational
contract and introduce no conditional tokens in either active or skipped reading.
Unsupported, computed, missing or cyclic candidates retain their command and a
located preparation requirement, while later source continues. Inputs hidden in
opaque arguments remain deferred. `candidate_tex_files` distinguishes prepared
conditional inputs from established active inputs. No branch's effects are executed
or merged into the caller, and inlining preserves the input's final line boundary.
The same observation handoff admits literal inputs and bibliography sites inside
retained environments. An existing BBL is inspected in an independent context;
its complete envelope and entry headers feed the existing bibliography pipeline,
including canonical BibTeX enrichment. Native bibliography output destined for an
unresolved region must also pass the insertion check. Unsupported bibliography
candidates preserve their declaration and a located requirement without hiding
the source that follows the enclosing region.

Genuine reading boundaries, including computed catcode assignments, unsupported
predicate headers, conflicting branch boundaries and literal grammars, still limit emission. The unfinished root operation and
following suffix are preserved in that case, with `partial` status. The survey
continues inspecting the source under an explicitly independent profile. There
is no legacy-regex or compiler fallback. Any future executable prototype
comparison uses the separate restored prototype, never a fallback in this integration.
An unsupported operation in separately retained local code can resume its caller
at the input checkpoint under explicitly recorded entry-state assumptions. The code
and missing effects remain in the payload/manifest; this is preparation recovery,
not a claim of completed package execution.

The policy now controls supported literal-role elimination/preservation, external
literal inlining, transparent-wrapper unwrapping, and the reusable
[mouth emitter](src/prepare/emission.py). Full-line and inline comments can be
retained independently; `!TeX key=value` comments can be retained, removed, or
captured as inert `source_metadata` linked to located units. The reader supplies
the comment introducer span, including alternative catcodes and `^^` spellings.
Protected bodies and separately retained local code keep their existing contracts.

Emission preserves every paragraph token and comment-suppressed endline. At EOF,
a stripped comment may retain its marker to avoid introducing an endline token;
its payload is still accounted for as removed. Ignored spaces and input-line tails
are stripped only where the reader established that behavior. Paragraph coalescing,
physical trailing-space preservation, comment sidecars, and elimination of endline
suppression are rejected before source reads, rather than silently ignored.
See the [policy contract](resources/policies/README.md) for the supported settings.
`provenance.emit_ledger` supplies the default; an explicit `emit_provenance` API
argument overrides it. `rle_compression` controls merging adjacent identity segments.
Final manifest locations do not depend on ledger emission or compression.
Experimental projection YAMLs remain provisional.
The handler registry is vocabulary, not an executable plugin loader. Core
source declarations and argument shapes live in
[source_traversal.yaml](resources/bindings/engine/source_traversal.yaml);
package-specific discovery shapes live in their package binding.

Scoped literal configuration uses the reusable
[configuration machinery](src/reading/configuration.py). The `listings` binding
declares `\lstset` as a local ordered assignment and `\lstdefinestyle` as a global
named recipe, matching the package source. Style references resolve when applied;
local listing options overlay current defaults without changing them. Key/value
splitting uses captured tokens and group depth, retaining repeated-key order and
formatting tokens without executing them. Unknown keys, computed reading values,
missing/cyclic styles and unsupported dialect/aspect syntax remain located limits.

In preparation, a physical-line listing can capture one declared TeX escape mode
(`escapeinside` or `escapechar`). Closing delimiters are matched through the mouth,
so TeX comments and escaped control symbols do not create false closers. Escape
contents remain unexpanded under entry reading state, with child unit IDs,
unknown coverage and final manifest locations. Their possible effects invalidate
bounded boolean knowledge; visible dependency commands get preparation requirements.
This is not execution of interpolated TeX, language drivers or formatting macros.
Strict dispatch still stops before interpolation. Math/combined interpolation,
inline-listing grammar and effectful code that changes escape reading remain
outside this bounded contract. External listings consult the same scoped options;
reading-affecting external resources retain the existing payload fallback.

Bibliography preparation selects source-visible citation keys across all emitted
input occurrences, including citations after the bibliography declaration. The
initial [natbib contract](resources/bindings/packages/natbib.yaml) supplies citation
argument shapes, including stars and up to two notes. An inactive package's unique
grammar can supply a located, provisional key observation without activating the
package or executing a retained style. `DeferredRegion.command` records that
distinction; it is not an executed `SourceCommand` event.

The bibliography manifest reports `citation_discovery`, its non-expanding scope,
the observed `citation_keys`, and specific `citation_gaps`. Other uninterpreted
contexts are counted in `citation_deferred_contexts`; their locations already live
in `requirements`. Partial interpretation does not select every database entry.
Only explicit `\nocite{*}` requests that. Empty/computed key sets do not manufacture
citations; unobserved entries remain in the emitted canonical `bibliography.bib`.
Known keys are formatted into `bibliography.bbl` and embedded in `master.tex`.
Unconfirmed missing keys remain diagnostics; missing established citations still
report resource errors. Selected conflicting records retain the canonical-resource
fallback. Unused duplicate keys cannot prevent formatting the selected references.

For an existing BBL, the active `natbib` binding also recognizes Harvard-family
`\harvarditem[short authors]{full authors}{year}{key}` headers. Their argument
grammar and `bibliography_key` metadata use the same machinery as `\bibitem`;
the original headers and body remain unexpanded in the inlined bibliography.
This is natbib's compatibility grammar, not a complete `harvard` package binding
or bibliography-style interpreter. The specimen index uses the manifest's validated
entry count, so package-specific entry commands are counted consistently.

All runtime YAML loaders reject duplicate keys through the shared strict loader.
Policies validate their fields and action values. Catalog loading checks binding
identities, current construct-list structure, engine/profile references and the
registered core reading actions. This is validation of the current contracts,
not a complete schema for future bindings.

## Initial structural reading

```python
from src.bindings.resolver import BindingResolver
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import TexReader

resolver = BindingResolver()
context = resolver.new_context()
reader = TexReader(source, source_id="paper.tex", occurrence_id=0,
                   catcodes=context.catcodes, endline_char=context.endlinechar)
dispatcher = StructuralDispatcher(reader, context, resolver)
for item in dispatcher:
    # ReadEvent, LiteralRegion, StoredDefinition, or a final ReadingBoundary.
    ...
```

Execution routing belongs to [StructuralDispatcher](src/reading/dispatcher.py).
It applies resolved local reading effects (`\makeatletter`, `\makeatother`,
`\ExplSyntaxOn`, `\ExplSyntaxOff`) and handles category-driven brace groups and
`\begingroup`/`\endgroup`. YAML supplies action identities, assignments and group
kinds. Mismatched or unmatched closers produce a diagnostic without popping a
scope. Group exit restores lexical settings in place, preserving cursor state.
Directives and group tokens retain their original `ReadEvent` spans.
Bounded `\catcode` scanning also supports decimal/backtick character codes and
decimal categories, terminated by space, `\relax` or EOF. Assignments retain their
source. Computed numbers, other numeric forms, global prefixes and general token
pushback remain explicit boundaries.

For local `\def`, the dispatcher delegates to
[DefinitionScanner](src/reading/definition_scanner.py), then installs the completed
`StoredDefinition` in the context. YAML selects the primitive grammar, assignment
scope, and expansion requirement. The scanner collects parameter text and a
balanced body under `STORED_DEFINITION`; body commands, apparent literals, nested
definitions and input commands do not execute. Captures retain exact source spans
and definition-time tokens, including catcodes and `^^` occurrence spans. Parameter
numbers are checked, but `##` pairs stay uncompiled and the special `#{` rule is
recorded explicitly for later interpretation. No body is serialized and retokenized.

Local definitions shadow bindings immediately and restore on matching group exit.
A scope journals only the meanings changed in that scope. A stored macro invocation
is a located boundary, including redefined literal commands and environment
entry/exit commands; it cannot silently invoke the previous binding. This increment
captures declarations, without classifying their eventual reading effects or
expanding their invocations. Expanding/global forms (`\edef`, `\xdef`, `\gdef`),
prefixes and other declaration factories remain unsupported boundaries.

The same scanner captures bounded `\newcommand` and `\renewcommand` declarations:
starred or unstarred, a literal control-sequence target (braced or unbraced), a
literal argument count 0–9, an optional first-argument default, and a braced body.
`CommandDefinition` retains that authored signature, exact spans and frozen tokens;
it does not synthesize primitive parameter patterns or optional-argument helpers.
Bodies and defaults do not execute or invalidate unrelated boolean state. YAML
specifies the handler, target requirement and reserved names. Registration and
scope restoration remain in the dispatcher. Known new-command collisions are
diagnosed; an unbound target does not prove undefinedness. Unverified existence
checks become interpretation requirements with final prepared-artifact locations,
including declarations captured during bounded option replay. Missing binding
knowledge does not prevent capturing a renewal such as `\renewcommand{\rmdefault}{ptm}`.
Inside an already deferred environment, a stored invocation retains its protected
argument envelope without executing it or reusing the shadowed binding. The
environment's pending reading contract remains explicit, and traversal can reach
later inputs, assets and bibliographies.

The dispatcher delegates kernel `\verb`, `\verb*`, `verbatim`, and `verbatim*`
to [LiteralScanner](src/reading/literal_scanner.py). Literal scanners have no
top-level execution loop. YAML selects their generic grammar handlers. A literal
records contiguous opening/body/closing spans into the
original buffer, including authored CRLF, tabs and trailing spaces. Those spans
use Python string offsets, not encoded byte offsets. Block terminators match
tokens and their category codes; inline delimiters become locally active.
Package physical-line literals use their declared regex, anchoring and suffix
rules. Plain `verbatim`, `Verbatim`/`BVerbatim`/`LVerbatim`, `lstlisting`, and
comment blocks are supported when their reading contracts are satisfied.
Interpolation and custom code hooks remain pending.
Closing a literal restores lexical settings while retaining the cursor's exit
N/M/S state. No substring readers or source copies are needed.

The generic environment registry implements the declared recipes for
`\DefineVerbatimEnvironment`, `\excludecomment` and `\includecomment`. Definitions
are scoped and do not execute inside stored definitions or skipped branches.
Included comment bodies are captured by physical lines and read again through an
in-memory window of the same source basis; their wrappers introduce no scope.
This replay can resolve child inputs and reading effects before preparation
unwraps the container. Other environment factories and declaration wrappers
beyond the bounded command forms remain future work.

The `environ` binding adds bounded `\NewEnviron` / `\RenewEnviron` declarations
through [EnvironmentScanner](src/reading/environment_scanner.py). A declaration
retains the literal name, optional count/default, processing code, body-command
name and final code. The dispatcher registers its scoped entry/exit meanings.
`\environbodyname` and `\environfinalcode` capture scoped defaults; each declaration
keeps the defaults in force at its source position. Known conflicts and unverified
existence checks use the same diagnostic distinction as command declarations.

An invocation is collected as tokens before its arguments or authored code are
interpreted. Grouped delimiter tokens are protected; ungrouped begin/end tokens
control nesting. Apparent verbatim commands and conditionals do not execute during
collection. `CollectedEnvironment` preserves opening/body/closing spans, token
categories and the declaration's unit ID. Preparation retains its complete source
and emits an interpretation requirement linked to that definition's final artifact
location. No `\BODY` substitution, trimming, final-code execution or generic macro
expansion occurs. Low-level `\Collect@Body` calls, computed declaration signatures,
and collecting across physical input EOF remain explicit limits.

External literal commands (`\verbatiminput`, `\VerbatimInput`, `\lstinputlisting`)
use the shared source cache. Safe bodies are inlined with exact source provenance;
delimiter collisions or unsupported options retain one rebased payload resource.
No original manuscript file is modified.

Local package/class loads now own bounded option contexts. `\DeclareOption`
and `\DeclareOption*` capture their bodies without running them. `\ExecuteOptions`
applies declared defaults; `\ProcessOptions` and its starred form select bodies
using declaration or request order configured in the core YAML binding. Explicit
document-class options are available to packages; literal `\PassOptionsToPackage`
and `\PassOptionsToClass` requests are accumulated for their respective targets.
Forwarded class options do not become global package options. Nested package
loads have separate option contexts; ordinary inputs share their owner's context.
Repeated loads with incompatible options produce located diagnostics.

Selected bodies reuse the structural dispatcher over a
[captured-token cursor](src/reading/token_cursor.py), preserving capture-time
catcodes and spans. They apply only supported reading effects, boolean routing,
groups and non-expanding definitions. Their source remains in the retained local
code; replay neither duplicates it in the master nor alters top-level source
coverage. Unselected bodies do not invalidate boolean state. Unknown executed
code invalidates option knowledge as well as boolean knowledge.

This follows the legacy option interface in
[the LaTeX kernel](https://github.com/latex3/latex2e/blob/main/base/ltclass.dtx),
not a general package interpreter. Selected bodies requiring macros such as
`\CurrentOption`, parameter-token compilation, file loading, or character/literal
scanning remain explicit boundaries. Each selected body must balance its own
groups and conditionals. Option controls inside additional lexical groups,
forwarding after a target is loaded, repeated processing, and key/value option
frameworks also need further contracts. Failed effect replay restores its entry
state, and preparation still publishes the retained code and a partial master.

The dispatcher also owns a conditional stack independent of lexical groups.
YAML separates conditional nesting roles from predicate evaluation. Constant
true/false predicates (`\iftrue`, `\iffalse` and declared equivalents) and
established document-local boolean tests execute;
other declared TeX82 predicates can nest inside skipped text but stop an active
scan before their arguments. `\else` and `\fi` route through the dispatcher.
[SkippedBranchScanner](src/reading/skipped_scanner.py) advances the same mouth
cursor without expansion, literal dispatch, definition publication or effects.
Thus `\iffalse\verb|\fi|LIVE` ends skipping at that first `\fi`. Comments and
current catcodes still affect tokenization. Stored author macros shadow binding
meanings, including conditional-looking names; they do not expand while skipped.

The bounded `\newif` handler captures a literal control-sequence target (optionally
in one brace group) and installs local conditional/setter meanings. The naming
prefix, initial meaning and setter recipes live in `core_latex.yaml`, following
[the LaTeX kernel's newif/@if definitions](https://github.com/latex3/latex2e/blob/main/base/ltdefns.dtx).
The dispatcher owns installation, setter execution and branch routing. Setters
copy the current true/false source meaning; they do not expand a stored body.
Boolean meanings and author definitions share one scope journal, including
shadowing, redeclaration, input handoffs and restoration. Declaration headers,
setters and conditional delimiters retain their source spans. Preparation keeps
those commands while omitting only established inactive branch contents.

Unexecuted commands, environments, opaque argument effects and unresolved package
code can make these booleans uncertain. A later test or setter then produces a
located reading boundary rather than using a stale value; preparation preserves
the unresolved source and can still publish a partial master. Potential global
effects also invalidate saved outer meanings. This conservative guard is not
general macro-effect inference or a persisted context snapshot contract.

A `SkippedRegion` covers only the discarded branch text, including any nested
conditional tokens. Its owning conditional opener is retained as a source span;
the executed branch delimiters remain separate `ReadEvent`s. The scanner hands
the already-read closing delimiter back to the dispatcher without retokenization.
Empty branches retain records. A failed skip returns a diagnostic and unresolved
source from the branch start, rather than claiming a completed skipped region.
This classifies source; it neither deletes source nor chooses output edits.

`TexReader.position` excludes unconsumed lookahead; `current_line` exposes both
the raw physical line and its trimmed mouth window. `peek_character()` stays on
that line and preserves any `^^` conversion already performed. Reader-local
`checkpoint()` / `restore()` also preserve pending characters, captured
`endlinechar`, category settings and sticky errors. They do not snapshot or roll
back execution effects or the dispatcher's group/conditional stacks. Do not use a reader-only
checkpoint to rewind executed directives. Successful group/literal exit never
restores the cursor to its entry state.

This is not yet a whole-document structural parser. Unknown commands, active
meanings, unsupported definitions, stored macro invocations, unevaluated predicates,
computed environment names, math/alignment
structure and unsupported package literal grammars return a located
`ReadingBoundary` and halt this scan. Its `remainder` covers unchanged source not
already emitted by preceding items. At EOF in executed text an unclosed group or
conditional diagnostic points to its opener but has empty residue; no duplicate source or synthetic closer is
emitted. A boundary retains already executed state for diagnosis without repair.
Unclosed literals retain that residue rather than consuming it as proven literal
content. Stored-definition, argument-scanning and skipped-branch modes require
their owning scanners; this dispatcher does not dispatch inside them. It performs
no package discovery, general computed/global assignments, macro expansion or XML work.
Reading after catalog bootstrap performs no filesystem I/O.

Conditional classification assumes established binding and author-meaning context.
It uses explicit declarations, never an `if` name prefix. The initial nesting
inventory is TeX82; extension/package conditional primitives need declarations,
and aliases are bounded by their captured donor meaning. General expansion, computed
predicates, global prefixes, unrestricted option/hook execution, outer-command checks and TeX's error-recovery repairs remain outside
this increment. Production preparation consumes this bounded dispatcher through its source owner.

## Source intervals and coverage

[spans.py](src/reading/spans.py) owns `SourceBasis`, `SourceSpan` and `SpanSet`.
Each reader creates one immutable, in-memory basis for its decoded source
occurrence. Spans carry that basis plus validated half-open character offsets;
source labels are available through `span.basis.source_id` and
`span.basis.occurrence_id`. Equal filenames, occurrence numbers, lengths or text
do not make separately created bases interchangeable. Operations reject foreign
bases even for empty coverage. This is a runtime source identity. Published
artifact revisions and source-to-emission correspondence are separate contracts
described below; token-index mapping remains outside this interface.

### Prepared locations and identities

The dispatcher assigns read-local IDs to structural units through
[units.py](src/reading/units.py). Captured observations carry explicit parent IDs;
requirements have their own IDs and link to their units. The same dispatcher can
read raw input occurrences or the finalized `master.tex`. IDs are unique within
a traversal, not permanent identities across document revisions. Ordinary character
events do not each allocate a unit record.

[edit_map.py](src/reading/edit_map.py) composes explicit edits in memory. Copied
ranges preserve offsets; replacements preserve whole-extent correspondence and
label narrower interests as enclosing when exact correspondence is unavailable.
Inserted lexical separators are separate synthetic pieces. Input/bibliography
replacements also link the original directive to the emitted replacement range.

After bibliography, image and payload rewrites, finalization computes absolute
locations. `manifest.json` contains:

- `units`: IDs, kinds, optional parents, diagnostic origins, final locations and status.
- `requirements`: IDs, `unit_id`, existing reason/stage information, and directly usable locations.
- `prepared_artifacts`: package-relative paths, SHA-256 hashes of emitted UTF-8 bytes, and decoded lengths.
- `location_contract`: zero-based, half-open Unicode-code-point offsets in the exact
  decoded artifact, with no newline translation. These are not UTF-8 byte offsets.

A location names an `artifact`, `start`, `end`, and `precision` (`exact` or
`enclosing`). Most manuscript locations target `master.tex`; retained local code
targets its prepared payload file. `location_status` is `mapped`, `enclosing`,
`partial`, `omitted`, or `unmapped`. Missing locations never imply that a requirement
has been resolved. In particular, observations from a rolled-back child can remain
unmapped in a partial preparation. The location index is not an execution schedule.
Inventory-only output carries linked IDs with `pending` locations until materialization.

The finalized master and its intentionally retained resources become downstream
source truth. Original spans are optional preparation diagnostics. Artifact edits
invalidate these locations until they are rebuilt. Context snapshots, context-effect
classification, scheduling and general expansion are not implemented by this increment.

Provenance v3 records full character tombstones with occurrence identity, explicit
replacement relations and per-occurrence `source_coverage.unaccounted` ranges.
Discard events consumed inside argument scanners are included only where source
was actually removed. Preserved bodies and emission rollback take precedence.
The accounting check reports unknown gaps rather than inferring their meaning.

`SpanSet` normalizes coverage into sorted nonempty intervals, merging overlaps
and adjacency. It supports union, intersection, difference, clipping, explicitly
bounded complement, coverage checks, and partitioning at specified offsets.
Empty spans retain locations in their original records but contribute no covered
characters. Coverage containment of an empty span is consequently vacuous; it is
not a point-membership test. Set construction sorts arbitrary input; operations
sweep normalized intervals without per-character masks or source text copies.

[coverage.py](src/reading/coverage.py) consumes established top-level dispatcher
items. It retains literal/definition/skipped records and diagnostics, coalesces observed
source extents, and treats every unobserved gap or suffix as unknown. It does not
execute the reader, reinterpret raw tokens, or certify undispatched reader events.
Use this instead of the iteration loop above to consume a fresh dispatcher once:

```python
from src.reading.coverage import ReadingCoverage

coverage = ReadingCoverage(reader.basis, dispatcher)
literal_bodies = coverage.query("literal", part="body")
definition_bodies = coverage.query("definition", part="body")
skipped_text = coverage.query("skipped")
selected_bodies = literal_bodies.union(definition_bodies)
for segment in selected_bodies.partition():
    # segment.span and segment.state: match, nonmatch, or unknown
    ...
```

Already collected dispatcher items can be supplied instead. A partial collection
does not imply that the rest was scanned, and consuming an exhausted dispatcher
does not recover earlier results. Queries can select whole regions (`part="span"`)
or bodies, optionally within a source window. Original records remain available
in `literal_regions`, `stored_definitions` and `skipped_regions`, even when adjacent coverage merges
or a body is empty. Ordinary per-token events are not retained by the adapter.
The `skipped` query selects branch extents excluding executed delimiters; only
`part="span"` applies. Such extents are known nonmatches for dispatched literals
and definitions: apparent declarations inside skipped text never ran.

Each `Coverage` query has disjoint `matches` and `unknown`; `nonmatches` is the
remaining coverage in its window. Negation preserves unknowns. Union, intersection
and difference use three-valued logic: a known match settles an OR and a known
nonmatch settles an AND; unresolved cases stay unknown. Composition requires the
same basis and window; use `restrict()` explicitly when narrowing a query.
Nonmatching literal coverage means only that the established reading did not
dispatch a literal there. It does not prove ordinary prose or authorize cleanup.

Diagnostic anchors are separate from unknown character coverage. An unclosed-structure
diagnostic at EOF can have an earlier opener as its anchor and empty remaining
coverage; the diagnostic is retained. Likewise, an empty unresolved location has
no character coverage. Empty `unknown` therefore does not imply structural validity.

The adapter accepts ordered, non-overlapping dispatcher observations and a terminal
boundary; malformed partitions, incompatible bases and contradictory extents are
rejected. This layer does not build a claim hierarchy, resume dependency requests,
plan output edits, or emit `master.tex`. Preparation consumes one coverage snapshot per input occurrence.
No additional YAML schema or dependency is needed for these interval algorithms.

## Running and checking

From this directory, with the dependencies in [requirements.txt](requirements.txt):

```text
python -B -m src.prepare.pipeline --help
python -B -m src.prepare.pipeline <source-project> [output-directory] [root-tex]
python -B -m src.prepare.inventory <source-project> [root-tex]
python -B -m unittest discover -s tests -p 'test_*.py' -v
```

### Optional rendering comparison

Rendering is a separate command with an explicitly supplied Tectonic executable:

```text
python -B -m src.validation.render <original-project> <original-main.tex> <prepared-directory> <new-comparison-directory> --tectonic <executable> --font-dir <font-directory>
```

The original main path is relative to its project; the prepared entry is
`master.tex`. The comparison directory must be new and outside both input trees.
No compiler is located on PATH, installed, or called by preparation. The default
uses only Tectonic's cached bundle resources; `--allow-downloads` explicitly permits
missing resources to enter that compiler's cache. `--bundle` selects a bundle,
and `--timeout` bounds each compiler invocation (120 seconds by default).

Each source tree is staged independently. SVGs become temporary PDF derivatives
plus small bounding-box sidecars, using the existing PyMuPDF dependency. A graphics
driver hook in the temporary main makes `graphicx` read those derivatives without
changing the canonical master, its filenames, or its assets. Original sources,
including a supplied BBL and the original jobname, are preserved. The adapter
does not supply the prepared render with assets from the original tree.

Only `original.pdf`, `prepared.pdf`, their logs, and `comparison.json` survive.
Temporary source copies, derived assets, compiler byproducts and generated font
caches are removed on success and failure. Failed renders retain their logs and
status, not partial PDFs. One failed side does not prevent attempting the other.
The report records input hashes, compiler version/configuration, conversion
warnings, page counts, word overlap and matching decoded raster images. These
are comparison observations, not a certification of manuscript equivalence.

`--font-dir` may be repeated; it creates one temporary Fontconfig configuration
shared by both renders. Alternatively, `--fontconfig` selects an existing config.
Without either option, both inherit the caller's font environment. Configuring
Fontconfig does not guarantee that the manuscript's selected fonts contain every
glyph. Compiler warnings remain in the logs.

Relocation qualification is available independently through
`python -B -m src.validation.relocation <prepared> <new-output> --tectonic <executable>`
or the specimen harness's `qualify` command. Only prepared files are staged; optional
`--raw-source` paths are hidden from the compiler, and inherited TeX input search
variables are removed. A successful engine result also needs a filesystem dependency
receipt resolving entirely to the disposable payload/driver or build products.
Compiler bundle/cache resources and fonts are allowed validation dependencies.
`--format xdv` checks compilation separately from PDF font embedding; its report
does not claim PDF rendering. These checks qualify the exercised document route,
not every possible conditional configuration or semantic equivalence to the original.

Version 2 qualification receipts include independent check records and structured,
source-linked diagnostics. Their [diagnostic taxonomy](recipes/qualification-diagnostics.md)
uses a small witnessed YAML catalog, evidence-preserving log unwrapping, and a
pure summary projection. `--diagnose` enables bounded XDV/original-source checks
after a failure; a baseline-reproduced error or successful XDV does not certify PDF
output. Unrecognized errors stay visible for later catalog growth.

The initial adapter targets Tectonic's XeTeX/LaTeX graphics route, not arbitrary
engines or SVG packages. SVG conversion warnings and external-resource failures
are explicit. Text in vector SVGs and engine/package differences still require
inspection; no claim of universal rendering fidelity is made.

Unit tests use a controlled compiler stand-in plus real PDF/image conversion.
Set `PYTEXML_TEST_TECTONIC` to an explicit executable to also run the optional live
graphics test; `PYTEXML_TEST_FONT_DIR` optionally configures its fonts. That test
uses cached compiler resources and checks scaling, clipping, rotation, nested
entry paths and cleanup.

See the [preparation contract](issues/DESIGN.md) and
[native processing/dependency note](issues/external-toolchains.md) for scope and
current limitations. The [declarative binding design brief](../../../aipithicus-issues/LaTeXAI/briefs/pytexml-declarative-bindings.md)
separates settled direction, proposed ontology/interfaces/schemas, and the
investigations required before concrete custodian recipes and broader authoring.
The current binding resources remain prototypes. Research exchanges under
`issues/` retain their historical paths and are not instructions for running the
current layout.

The [restored-prototype comparison](issues/preparation-prototype-comparison.md)
records the 2405.15943v3 run, current improvements and remaining preparation gaps.

The [specimen iteration recipe](recipes/specimen-iterations.md) describes named
multi-paper development batches, linked indexes, source/code fingerprints,
per-paper outcomes and diffs. Identical generated resources share read-only hard
links across checkpoints; source trees are retained once. The optional rendering
adapter can add separately named evidence to an existing batch.
