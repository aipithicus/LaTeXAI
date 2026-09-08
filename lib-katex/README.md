# lib-katex

Reference-only root: a pinned slice of [KaTeX](https://github.com/KaTeX/KaTeX) and the tables derived from it. The engine never reads this directory. Bindings never carry KaTeX names. Post and `symbind.pl` check mappings against `derived/`.

KaTeX is a gate, not a target. The tables say whether a name is known and, for symbols, operators, macros, and fonts, what KaTeX does with it. They are not a parser: they do not carry argument signatures, so they cannot say whether a structural spelling with arguments parses.

## Rules

1. Bindings emit LaTeXML tokens (`role`, `meaning`, `name`, font). No KaTeX name appears in `lib/LaTeXML/Package/`.
2. The engine never finds this root: not on `--path`, never in `lib-ctan/ls-R`. The index writer walks `lib-ctan` only; the aliases and worker never name a reference root.
3. Post reads `derived/`. The `katex` column of `lib-symb` tables is checked against those files.

## Tracking

Tracked: `README.md`, `provenance.json`, `derived/*.tsv`.
Ignored: the copied KaTeX sources. A checkout without a KaTeX clone still validates. Restore the sources with `lkatex --restore --clone=<path>` from a clone at provenance's tag and SHA. `cloned_from` in provenance is telemetry and is never read by restore.

## Tooling

```powershell
lkatex --clone=<path>                 # clone must be at a tag with a clean tree
lkatex --restore --clone=<path>       # clone must match provenance tag and SHA
lkatex --derive                       # regenerate derived/ from vendored sources
lkatex --check                        # hashes, sort, TSV headers, counts vs provenance
```

`--clone` rewrites provenance only when a file hash or the pin changed.

## Resync

Move the clone to a new tag (clean tree), then `lkatex --clone=<path>`. Read the derived diff. Commit tables and provenance together.

Pin at first vendoring: tag `v0.18.7`.
