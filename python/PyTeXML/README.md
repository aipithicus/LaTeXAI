# PyTeXML

Native Python preparation and reading machinery for a future manuscript compiler.
Preparation builds `master.tex` and its required resources; general macro
expansion and XML interpretation belong to later development.

## Current source organization

| Location | Responsibility |
| --- | --- |
| [`src/reading/`](src/reading) | Reusable N/M/S reader and cursor, initial literal dispatcher, regex catcode rules, mouth profiles, and scoped document state |
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
The reader, literal dispatcher, binding resolver, and policy loader are independently
tested foundations, not yet integrated into that pipeline. Projection YAMLs have no
runtime consumer, and the handler registry does not execute handlers. Its
`context_effect` entries describe existing state helpers; `deferred` entries
require future dispatch/scanning work; `scanner` entries describe the initial
in-memory literal handlers.

All runtime YAML loaders reject duplicate keys through the shared strict loader.
Policies validate their fields and action values. Catalog loading checks binding
identities, current construct-list structure, engine/profile references and the
registered core reading actions. This is validation of the current contracts,
not a complete schema for future bindings.

## Initial literal reading

```python
from src.bindings.resolver import BindingResolver
from src.reading.dispatcher import LiteralDispatcher
from src.reading.tex_reader import TexReader

resolver = BindingResolver()
context = resolver.new_context()
reader = TexReader(source, source_id="paper.tex", occurrence_id=0,
                   catcodes=context.catcodes, endline_char=context.endlinechar)
dispatcher = LiteralDispatcher(reader, context, resolver)
for item in dispatcher:
    # ReadEvent, LiteralRegion, or a final ReadingBoundary; no source edits.
    ...
```

This bounded component supports kernel `\verb`, `\verb*`, `verbatim`, and
`verbatim*` in an established active context. YAML selects the generic grammar
handlers. A literal records contiguous opening/body/closing spans into the
original buffer, including authored CRLF, tabs and trailing spaces. Those spans
use Python string offsets, not encoded byte offsets. Block terminators match
tokens and their category codes; inline delimiters become locally active.
Closing a literal restores lexical settings while retaining the cursor's exit
N/M/S state. No substring readers or source copies are needed.

`TexReader.position` excludes unconsumed lookahead; `current_line` exposes both
the raw physical line and its trimmed mouth window. `peek_character()` stays on
that line and preserves any `^^` conversion already performed. Reader-local
`checkpoint()` / `restore()` also preserve pending characters, captured
`endlinechar`, category settings and sticky errors. They do not snapshot or roll
back execution effects in `ReaderContext` and are not used for successful literal
exit.

This is not yet a whole-document structural parser. Unknown commands, active
meanings, definitions, conditionals, computed environment names and unsupported
package literal grammars return a located `ReadingBoundary` and halt this scan.
Its `remainder` covers unchanged source from the unresolved construct onward.
Unclosed literals retain that residue rather than consuming it as proven literal
content. Stored-definition, argument-scanning and skipped-branch modes require
their owning scanners; this dispatcher does not dispatch inside them. It performs
no package discovery, arbitrary catcode assignments, macro expansion or XML work.
Reading after catalog bootstrap performs no filesystem I/O.

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
