# PyTeXML

Native Python preparation and reading machinery for a future manuscript compiler.
Preparation builds `master.tex` and its required resources; general macro
expansion and XML interpretation belong to later development.

## Source organization

- `src/reading/`: reusable reader, catcode rules, and mouth profiles.
- `src/bindings/`: binding loading, resolution, and document reading state.
- `src/prepare/`: preflight, inlining, pruning, normalization, bibliography,
  preparation policy, provenance, and publication.
- `src/bibtex.py`, `src/source_io.py`, `src/converter.py`: shared helpers.

Import from the owning module, such as `src.reading.tex_reader` or
`src.prepare.pipeline`. Package imports do not eagerly load the pipeline.
Bare-module imports and direct source-file execution are no longer supported.
The next step separates mixed responsibilities inside these groups.

The YAML libraries remain in `bindings/`, `profiles/`, `policy/`, and `capture/`.
The reader, binding resolver, and policy loader are independently tested but
not yet integrated into the preparation pipeline. Capture projections have no
runtime consumer; operation-registry entries do not execute handlers.

## Running and checking

From this directory, with the dependencies in [requirements.txt](requirements.txt):

```text
python -B -m src.prepare.pipeline --help
python -B -m src.prepare.pipeline <source-project> [output-directory] [root-tex]
python -B -m unittest discover -s tests -p 'test_*.py'
```

See [the preparation contract](issues/DESIGN.md) and
[native processing/dependencies](issues/external-toolchains.md).
