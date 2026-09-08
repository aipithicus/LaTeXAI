# lib-symb

Reference-only root: **notation vocabularies** — packages whose value is a set of commands with meanings, roles, logical alphabets, and codepoints. Bindings for those packages are generated from curated `symbols.tsv` tables. The engine never reads this directory. It is never on `--path` and never in `lib-ctan/ls-R`.

Consumers: `lsymb` (`tools/dev/symbind.pl`) generates and checks bindings; post and the normalization study read the `katex` column against `lib-katex/derived/`. Bindings never carry KaTeX names.

## Layout

`lib-symb/<pkg>/` mirrors an lctan entry (`ctan.json`, `provenance.json`, `tex/`, `ctan/` with `--docs`) plus **`symbols.tsv`**.

Two entries are not CTAN packages and carry only a table and provenance naming the files they were extracted from:

- `lib-symb/_kernel/` — the TeX/LaTeX pools' own math vocabulary
- `lib-symb/_latexml/<pkg>/` — tables extracted from existing native bindings (source stays under `lib-ctan/`)

## Tracking

Tracked: `README.md`, every `provenance.json`, every `symbols.tsv`.
Ignored: `tex/` and `ctan/` trees. Restore with `lctan --restore --outdir=lib-symb`.

## Table schema

Tab-separated, one header row, sorted by `command`, one row per command and mode. Columns: `command`, `kind` (`symbol` / `alphabet` / `text`), `mode` (`math` / `text` / `both`), `codepoint` (`U+XXXX` or a sequence; empty for alphabets; assigned and outside private use for symbols), `name`, `meaning`, `role`, `font`, `katex`, `source`, `note`.

`kind=text` rows that name a style class (`regular` / `solid`) generate an `ltx:text` icon constructor, not `DefMathI`.

Blanks in `katex` are legitimate and reported. The checker resolves a non-blank cell in `lib-katex/derived/katex-symbols.tsv` or `katex-macros.tsv` only.

## Tooling

```powershell
lsymb --extract <binding.ltxml|_kernel|<pkg>>   # oracle table under _kernel/ or _latexml/<pkg>/
lsymb --author <pkg>                            # scaffold from the vendored package mapping
lsymb --seed-katex <pkg>                        # fill blank katex cells by codepoint join
lsymb --check <pkg>                             # table lint
lsymb --check-cross                             # codepoint/role agreement across tables
lsymb --generate <pkg>                          # write Package/<pkg>.sty.ltxml from the table
```

`--extract` never overwrites a generated native. `--generate` refuses to overwrite a binding that was not generated from a table (pass `--force` only to replace a passthrough stub).

Vendor a notation package with `lctan --docs --outdir=lib-symb <pkg>`.
