# PyTeXML

Native Python preparation and reading machinery for a future manuscript compiler.
Preparation builds `master.tex` and its required resources; general macro
expansion and XML interpretation belong to later development.

## Current source organization

| Location | Responsibility |
| --- | --- |
| [`src/reading/`](src/reading/) | Reusable N/M/S reader, regex catcode rules, mouth profiles, reading contracts, and scoped document state |
| [`src/bindings/`](src/bindings/) | Reusable binding catalog and document-local resolution/package activation |
| [`src/prepare/`](src/prepare/) | Discovery, inlining, pruning, normalization, bibliography preparation, provenance, policy loading, and publication |
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

The YAML libraries remain at their existing locations through the first two
organization steps: [bindings](bindings/README.md), [mouth profiles](profiles/mouth/README.md),
[policies](policy/README.md), and provisional [XML projections](capture/README.md).
Their contents and identities have not changed.

The preparation pipeline still uses its existing discovery and rewrite routines.
The reader, binding resolver, and policy loader are independently tested
foundations, not yet integrated into that pipeline. Projection YAMLs have no
runtime consumer, and the operation registry does not execute handlers.

The remaining organization step will consolidate/classify the YAML libraries
under `resources/` and align validation. Policies still use their existing loader;
the strict mapping loader is currently used by mouth profiles and binding catalogs.
These changes are separate from reader/dispatcher feature development.

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
current limitations. Research exchanges under `issues/` retain their historical
paths and are not instructions for running the current layout.
