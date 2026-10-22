# PyTeXML

Native Python preparation and reading machinery for a future manuscript compiler.
Preparation builds `master.tex` and its required resources; general macro
expansion and XML interpretation belong to later development.

## Current source organization

| Location | Responsibility |
| --- | --- |
| [`src/reading/`](src/reading) | Reusable N/M/S reader and cursor, structural dispatcher, literal/definition scanners, source intervals and coverage queries, regex catcode rules, mouth profiles, and scoped document state |
| [`src/bindings/`](src/bindings) | Reusable binding catalog and document-local resolution/package activation |
| [`src/prepare/`](src/prepare) | Discovery, inlining, pruning, normalization, bibliography preparation, provenance, policy loading, and publication |
| [`src/source_io.py`](src/source_io.py) | Strict source decoding and malformed-byte diagnostics |
| [`src/bibtex.py`](src/bibtex.py) | Reusable BibTeX parser and data model |
| [`src/assets.py`](src/assets.py) | Image inspection and individual asset conversion |
| [`src/yaml_io.py`](src/yaml_io.py) | Strict YAML mapping loading, with schema validation left to each consumer |

Within preparation, [discovery](src/prepare/discovery.py) owns source enumeration,
root selection, and static dependency scanning. [Inventory](src/prepare/inventory.py)
assembles [manifest records](src/prepare/manifest.py) from that discovery,
[bibliography characterization/preparation](src/prepare/bibliography.py), asset
inspection, and [implicit-graphics detection](src/prepare/implicit_graphics.py).
[Asset preparation](src/prepare/assets.py) owns destination planning and TeX
reference rewriting. The existing line-based provenance remains preparation-local.

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

The preparation pipeline still uses its existing discovery and transformations
for assembling `master.tex`. Original manuscript sources are never edited.
The reader, structural dispatcher, binding resolver, and policy loader are independently
tested foundations, not yet integrated into that pipeline. Projection YAMLs have no
runtime consumer, and the handler registry does not execute handlers. Its
`context_effect` entries describe state helpers routed for supported local effects; `deferred` entries
require future dispatch/scanning work; `scanner` entries describe the initial
in-memory literal and definition handlers.

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
prefixes, and LaTeX wrappers such as `\newcommand` remain unsupported boundaries.

The dispatcher delegates kernel `\verb`, `\verb*`, `verbatim`, and `verbatim*`
to [LiteralScanner](src/reading/literal_scanner.py). Literal scanners have no
top-level execution loop. YAML selects their generic grammar handlers. A literal
records contiguous opening/body/closing spans into the
original buffer, including authored CRLF, tabs and trailing spaces. Those spans
use Python string offsets, not encoded byte offsets. Block terminators match
tokens and their category codes; inline delimiters become locally active.
Closing a literal restores lexical settings while retaining the cursor's exit
N/M/S state. No substring readers or source copies are needed.

The dispatcher also owns a conditional stack independent of lexical groups.
YAML separates conditional nesting roles from predicate evaluation. Only constant
true/false predicates (`\iftrue`, `\iffalse` and declared equivalents) execute;
other declared TeX82 predicates can nest inside skipped text but stop an active
scan before their arguments. `\else` and `\fi` route through the dispatcher.
[SkippedBranchScanner](src/reading/skipped_scanner.py) advances the same mouth
cursor without expansion, literal dispatch, definition publication or effects.
Thus `\iffalse\verb|\fi|LIVE` ends skipping at that first `\fi`. Comments and
current catcodes still affect tokenization. Stored author macros shadow binding
meanings, including conditional-looking names; they do not expand while skipped.

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
no package discovery, dynamic/global assignments, macro expansion or XML work.
Reading after catalog bootstrap performs no filesystem I/O.

Conditional classification assumes established binding and author-meaning context.
It uses explicit declarations, never an `if` name prefix. The initial nesting
inventory is TeX82; extension/package conditional primitives and dynamic aliases
need their own declarations or future meaning support. `\newif`, `\let`, predicate
evaluation, outer-command checks and TeX's error-recovery repairs remain outside
this increment. Production preparation still uses its existing paths.

## Source intervals and coverage

[spans.py](src/reading/spans.py) owns `SourceBasis`, `SourceSpan` and `SpanSet`.
Each reader creates one immutable, in-memory basis for its decoded source
occurrence. Spans carry that basis plus validated half-open character offsets;
source labels are available through `span.basis.source_id` and
`span.basis.occurrence_id`. Equal filenames, occurrence numbers, lengths or text
do not make separately created bases interchangeable. Operations reject foreign
bases even for empty coverage. This is a runtime identity, not yet a durable
source-store revision or a mapping between source, token and emitted coordinates.

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
plan output edits, or emit `master.tex`. Production preparation remains separate.
No additional YAML schema or dependency is needed for these interval algorithms.

## Running and checking

From this directory, with the dependencies in [requirements.txt](requirements.txt):

```text
python -B -m src.prepare.pipeline --help
python -B -m src.prepare.pipeline <source-project> [output-directory] [root-tex]
python -B -m src.prepare.inventory <source-project> [root-tex]
python -B -m unittest discover -s tests -p 'test_*.py' -v
```

See the [preparation contract](issues/DESIGN.md) and
[native processing/dependency note](issues/external-toolchains.md) for scope and
current limitations. The [declarative binding design brief](../../../aipithicus-issues/LaTeXAI/briefs/pytexml-declarative-bindings.md)
separates settled direction, proposed ontology/interfaces/schemas, and the
investigations required before concrete custodian recipes and broader authoring.
The current binding resources remain prototypes. Research exchanges under
`issues/` retain their historical paths and are not instructions for running the
current layout.
