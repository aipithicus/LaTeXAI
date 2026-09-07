# Architecture

What LaTeXAI is, what surrounds it, and how its parts are named. This document is the map; the contracts live in [`specification/`](specification/) and the procedures in [`recipes/`](recipes/). Where a part described here does not exist yet, the section says so. Status lines are dated; update them when the state changes.

## 1. Purpose

LaTeXAI is a fork of LaTeXML (upstream 0.8.8) shaped to return an intermediate representation, the IR, that a manuscript compiler consumes. Upstream renders TeX to HTML and MathML, where a plausible reading is the deliverable. This fork keeps the reading and adds the evidence beside it: the bytes the author wrote, the choices the author stated, and the places the engine guessed. That contract is [`specification/ir-evidence.md`](specification/ir-evidence.md).

The engine's own output, the `ltx` XML tree with the capture namespace beside it, is the product. Everything under `lib/LaTeXML/Post/` is an instrument for checking it, not a surface. The projection that consumes the IR (a transcoder to markdown with KaTeX math) is downstream and has no home in this repository; its interface is described in section 9.

## 2. Terms

One thing can carry several names when they name different facets. The rule is that the correspondence is stated, and each name is used for its facet.

| term | what it names | use it when |
| :--- | :--- | :--- |
| **`lib-ctan/`** | the folder | in paths, commands, and file layout |
| **resident library** | the role: the set of TeX sources the engine may read at runtime | in prose about policy (what may be read, what may not) |
| **texmf index** | the lookup structure over the resident library: `lib-ctan/ls-R` and the kpsewhich shim that answers from it | in prose about how a file is found |
| **reference root** | a vendoring root the engine never reads: `lib-symb/`, `lib-katex/`, `lib-park/` | in prose about what is off the runtime path |
| **entry** | one package's directory under a root, `lib-ctan/<pkg>/`, with its provenance | when counting or naming vendored packages |
| **vendoring unit** | the TeX Live archive an entry is cut from, with its revision; named by CTAN id, or by the archive (`latex`, `graphics`) when the file has no catalogue record | when a file's origin or pin is the point |
| **binding** | `lib/LaTeXML/Package/<name>.ltxml`, loaded in place of a package, class, or definition file | always; never "binding" for a data file or a table |
| **coverage category** | native, hybrid, passthrough, ignored, raw-only, missing: what a request for a package resolves to ([`bindings.md`](specification/bindings.md) section 2) | when describing what the engine does with a package |
| **class** | structural, containment, shim, ignored, semantic: what a binding is for ([`bindings.md`](specification/bindings.md) section 2.1) | when judging a binding against its criteria |
| **status** | native, hybrid, passthrough, partial, deferred, none: where the work on a package stands | in provenance and the demand join; never in a directory name |
| **data file** | a file the pool consumes through primitives it implements: encoding definitions, named-color tables, language definitions, config files, font definition files | when a request is for a table the engine reads raw by design |
| **raw package** | a macro package the engine interprets because a binding delegates to it (passthrough or hybrid) or because a raw file requires it | when a `.sty` is executed rather than bound |
| **notation vocabulary** | a symbol or alphabet font package whose value is a set of commands with meanings and codepoints | for lib-symb material |
| **table** | `symbols.tsv`: the curated rows a notation binding is generated from | never "table" for a data file |
| **census** | what a package defines, read from its source by `tools/texscan` | for the declared side |
| **demand** | which papers request a package, and what it costs them, read from receipts | for the measured side |
| **deposit** | one paper as codex-scientiae holds it: source tree, manifest, provenance | when naming corpus input |
| **receipt** | the per-paper record the gauntlet worker writes: counts, routes, attributions | when naming corpus output |
| **golden** | the `.xml` a fixture must reproduce ([`testing.md`](testing.md)) | for fixtures only; receipts are not goldens |

## 3. Repositories and ownership

| repository | owns | does not own |
| :--- | :--- | :--- |
| **LaTeXAI** (this one) | the engine, the bindings, the vendoring roots, the tools, the fixtures and goldens, these documents | the corpus, batch execution, the transcoder |
| **codex-scientiae** | the deposits and their inventories (`supellex/`), the batch executor and its inventory adapter, the runs under `artifacts/latexai/<stamp>/`, the receipt contract | anything about TeX |
| a local KaTeX clone | the KaTeX source at a tag, from which `lib-katex/` is vendored | nothing else; it is an input |

The gauntlet worker and its launcher, the LaTeXAI side of the batch contract, are engine glue and live outside tracked files by codex-scientiae's convention. Their contract is codex-scientiae's `src/batch-adapters/README.md`, "Worker contract". Nothing tracked here links to them.

## 4. Pipeline

Each stage names its owner and what crosses the boundary.

1. **Deposit** (codex-scientiae). A paper's source tree is ingested, validated, and described by a manifest; catalog inventories (`inventory.jsonl`, first-order or folded) are the trusted view of the population.
2. **Plan** (codex-scientiae). The inventory adapter reads rows, one job per deposit, and hands the worker the source tree, the entrypoint, and the tree hash. Nothing else is opened.
3. **Run** (LaTeXAI worker, per deposit). `bin/latexml` over the entrypoint with the corpus preload, log and streams contained in the job directory; the IR is written beside them.
4. **Receipt** (LaTeXAI worker). Counts from the engine's own tally (warnings, errors, fatals, undefined macros, missing files), element counts from the IR, package routes (`binding`, `raw-local`, `raw`, `missing`), and undefined-macro attribution to the source that should have defined it.
5. **Fold** (codex-scientiae). Receipts into `inventory-summary.jsonl` and `run.json` per run. The run directory is the unit of comparison.
6. **Demand** (LaTeXAI tools). The demand join reads binding state from the Package tree and demand from receipts; it orders binding work. Counts from any static census are seeds; receipts are the authority.
7. **Bind** (LaTeXAI). A package is vendored, censused, bound, fixtured, and its golden read, per [`recipes/package-bindings.md`](recipes/package-bindings.md). The corpus is rerun and the receipts move.
8. **Project** (downstream). The IR is transcoded; symbol tables are its interface (section 9).

## 5. Roots

Vendoring roots encode one axis: what the engine may do with the files. Nothing else is encoded in a root. The kind of source is a property of the entry; the status of binding work is metadata.

| root | engine may read | holds | indexed | provenance |
| :--- | :--- | :--- | :--- | :--- |
| `lib-ctan/` | yes, through the texmf index | the resident library: raw packages that bindings delegate to, data files the pool consumes, and the sources of native bindings kept for the census | yes | TeX Live archive, revision, snapshot |
| `lib-symb/` | never | notation vocabularies with their tables | never | TeX Live archive, revision |
| `lib-katex/` | never | the KaTeX symbol and macro sources at a tag, with derived row tables | never | git tag, commit, file hashes |
| `lib-park/` | never | vendored macro packages with no binding and no current demand | never | TeX Live archive, revision |

Every entry under `lib-ctan/` satisfies the **entry rule**: it is data the pool reads, or a raw package some binding asks for, or the source of a native binding. Anything else is parked. `lctan --check` enforces this locally, from a static scan of what bindings and raw files require plus a committed allow-list (`lib-ctan/entries.txt`), so nothing becomes raw-only interpretation by accident. The writer emits `ls-R`; the check is what refuses a tree that violates the rule.

An entry is named by its CTAN id and cut from one vendoring unit; the archive and revision are recorded in its provenance, and two entries cut from the same archive pin the same revision. Kernel files that CTAN does not catalogue are members of an entry named for their archive (`latex`, `graphics`) and are never entries of their own. A dependency a raw package requires is its own entry, marked in provenance as requested by the requirer; the census reads one entry, so a binding is never written from a dependency's source.

**Lockfile.** Provenance is the pin, not the trees. Each root gitignores its runfiles and tracks its README and `*/provenance.json`; `lib-ctan/` also tracks `ls-R` and `entries.txt` once they exist. A clone restores trees with `lctan --restore` from those pins.

Status (2026-09-06): `lib-ctan/` exists with 38 entries and no index; provenance is on disk and not yet committed; the shim, `lib-symb/`, `lib-katex/`, and `lib-park/` are specified and not yet built. Until the index exists, every passthrough request ends as a missing file.

## 6. Layers, and what gets a binding

From the engine outward:

1. **The pool**, `lib/LaTeXML/Engine/*.pool.ltxml`: the kernel's semantics, including the primitives data files call (`\DeclareTextSymbol`, `\DefineNamedColor`, `\ProvidesLanguage`). Vendoring never touches this layer.
2. **Bindings**, `lib/LaTeXML/Package/`: one per file name the engine may be asked for. This is the only layer that "gets a binding". Two sources: hand-written for macro packages, by class; generated from a table for notation vocabularies.
3. **Data files**: no binding, ever. They need a path, which the resident library provides.
4. **Raw packages**: no binding of their own beyond the passthrough or hybrid that delegates to them. They need a path.
5. **Reference vocabularies**: KaTeX. Never read by the engine; read by the table checker and by post.

Encoding definitions and named-color tables look like tables and are rows, but nobody curates them and the pool reads them by design. They are data files, layer 3, on the runtime path. Generating bindings for them re-implements file lookup one file at a time and is not done.

## 7. The binding ontology

Three independent dimensions, declared in three places:

- **Category** (what a request resolves to) is what the file does, read by `tools/texscan --all` until the coverage manifest exists.
- **Class** (what the binding is for) is declared in the binding's header, `# Class:`, and checked against the criteria in [`bindings.md`](specification/bindings.md) section 2.1.
- **Status** (where the work stands) is read by the demand join from the file and from provenance. It is never a directory: a deferred package moves to `lib-park/` because the engine must not read it, not because it is deferred, and a partial binding is a hybrid for as long as it is partial.

A native binding in upstream dialect is a contribution candidate ([`bindings.md`](specification/bindings.md) sections 1 and 6). That is why bindings carry nothing renderer-specific and nothing fork-specific: no KaTeX names, no capture namespace.

## 8. How a file is found

The search order in `FindFile_aux` (`lib/LaTeXML/Package.pm`), which no vendoring changes:

1. a binding in the Package tree or a `--path` directory: **bindings win**;
2. the raw file in a `--path` directory, if raw interpretation is on;
3. fallback bindings;
4. the raw file in a `--path` directory regardless;
5. kpsewhich, with both the binding name and the raw name as candidates.

Steps 1 to 4 look in flat, explicitly named directories. Step 5 is the only tree search. The texmf index answers step 5: `LATEXML_KPSEWHICH` names the shim, the engine asks it once at startup for the roots and reads `lib-ctan/ls-R` into a cache. Upstream then spawns kpsewhich for every name the cache lacks (MiKTeX has no ls-R). `LATEXML_KPSEWHICH_CACHE_ONLY` makes the cache authoritative: a miss returns undef with no process. The aliases and the corpus worker set both. `LATEXML_KPSEWHICH` is read when the path module loads, so it is set by the process that starts perl, never from inside a running perl. A reference root is never on a `--path` and never in the index, so nothing under it can be found by any step; a lint refuses a golden whose recorded search paths name one.

`--includestyles` governs step 2 only. A passthrough interprets its raw file regardless, which is what the resident library serves.

## 9. Tables and the mapping to KaTeX

A notation binding is generated from `lib-symb/<pkg>/symbols.tsv`: one row per command with mode, codepoint, name, role, logical font, the KaTeX macro, and provenance. Two consumers read the row. The generator writes the binding from every column except `katex`. Post reads the `katex` column.

**Bindings never carry the mapping.** A generated binding emits LaTeXML tokens (name, meaning, role, font, codepoint) and nothing a renderer would recognise. The IR is renderer-neutral, and a binding that knew about KaTeX would be fork dialect.

`lib-katex/` is the truth about what KaTeX accepts, vendored verbatim at a tag. Each table is the truth about our mapping. The checker holds the second against the first: every `katex` name exists, codepoints agree where KaTeX defines one, KaTeX's atom group agrees with our role. Blanks are legitimate, reported, and expected to be rare; post emits the codepoint for them.

Every symbol binding maps to a real codepoint: no private-use characters, no font slots. Text-mode symbols are emitted as the bare character, and the codepoint is the normalized token.

## 10. The evidence loop

Bindings are prioritised by measured demand, and their effect is measured the same way. The corpus is codex-scientiae's gauntlet inventory (90 deposits at the time of writing). A run writes one receipt per paper, and the run directory is compared as a whole: totals of missing files, undefined macros, and `ERROR` nodes, and the route of every package. A paired run, with and without a change, is the form of an experiment.

Three sources of counts exist: static censuses of `\usepackage`, the demand join, and receipts. The first two are seeds. Receipts are the authority, and any table of paper counts elsewhere is regenerated from a full run rather than defended.

Goldens and receipts answer different questions. A golden says a binding does what its fixture claims. A receipt says what the corpus paid. A binding can have a passing golden and still be the package the corpus is failing on; that is what the demand join is for.

## 11. Workflows

| to | see |
| :--- | :--- |
| vendor a package into a root | [`recipes/fetch-ctan.md`](recipes/fetch-ctan.md) |
| write or replace a binding | [`recipes/package-bindings.md`](recipes/package-bindings.md), with [`specification/bindings.md`](specification/bindings.md) as the contract |
| write a fixture and read its golden | [`testing.md`](testing.md) |
| run the corpus | the launcher outside tracked files, per codex-scientiae's worker contract; runs land under codex-scientiae's `artifacts/latexai/<stamp>/` |
| build a notation table and its binding | not yet documented; the recipe gains a section when the table tooling lands |
| build or rebuild the texmf index | not yet documented; `lctan --index` when it exists |

## 12. Rules that follow

Each of these has been the wrong shortcut at least once.

- A reference root is never placed on a search path, by `--path`, by an alias, or by the index.
- A binding is written from its own package's source, never from a dependency vendored alongside it.
- A data file gets a path, not a binding. An encoding or color definition is not a table to curate.
- Status is never a directory. A package moves between roots only because what the engine may read of it changed.
- A binding never names a renderer. The mapping to KaTeX lives in the table and is read by post.
- Counts from a static census are seeds. A receipt is the measurement.
- A vendored file is either data, requested by a binding, or the source of a native binding. Otherwise it is parked, not indexed.
- A kernel file CTAN does not catalogue is a member of an entry named for its archive (`latex`, `graphics`), never an entry of its own. A kernel file CTAN does catalogue keeps its CTAN-id entry.
- `--log` is always passed. A `.latexml.log` at the repository root means something bypassed the aliases.
