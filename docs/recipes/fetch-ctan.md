# Vendoring a package from CTAN

`tools/dev/fetch-ctan.pl` (alias `lctan`) vendors a LaTeX package into `lib-ctan/<pkg>/` with provenance, using only Perl modules Strawberry ships. No TeX engine is involved. Commands run from the repository root through the `pwsh_exec` profile.

## What a package is, on the wire

A package is published in more than one form, and the binding workflow needs exactly one of them: the runnable `.sty` (or `.cls`, `.def`, `.code.tex`).

| Source | What it holds | Used for |
| :--- | :--- | :--- |
| CTAN catalogue record, `ctan.org/json/2.0/pkg/<id>` | version, date, licence, CTAN path, and the package's TeX Live name | metadata and provenance |
| CTAN directory, `<path>.zip` | what the author uploaded: sometimes the `.sty`, often only a `.dtx`/`.ins` pair, plus documentation | docs and literate source; **not** a reliable source of the `.sty` |
| TeX Live runfiles archive, `tlnet/archive/<texlive-name>.tar.xz` | the generated `.sty` in TDS layout (`tex/latex/<pkg>/`), plus a `.tlpobj` with the revision | the `.sty`, always; the pin |

A `.dtx` is literate source; the `.sty` is produced by running TeX over the `.ins`. TeX Live has already done that for every package it carries and publishes the result as one small archive per package, which is also the artifact its package database pins by revision and checksum. So runfiles always come from TeX Live, never from the CTAN zip, and the CTAN zip is optional.

Two irregular cases the script handles:

- **Bundles.** A package whose TeX Live name differs from its CTAN id (`stackrel` lives in `oberdiek`) is fetched from the bundle archive and only the members belonging to the requested package are kept. `--whole-bundle` keeps everything.
- **Single-file CTAN entries.** A package published as one `.dtx` inside a bundle directory has no `.zip` rendition; with `--docs` the bare file is fetched instead. The record's `ctan.file` flag is not reliable for telling these apart, so the script tries the zip first.

Dependencies are not resolved. Neither CTAN nor TeX Live records per-package dependencies in machine-readable form. A raw package that `\RequirePackage`s something not yet vendored surfaces that as `route="missing"` in the capture ledger, and as a `No stylefile found` warning from `texscan`; vendor it explicitly, one pin at a time.

## Fetch

```powershell
lctan nicematrix                      # runfiles + metadata + provenance
lctan --docs nicematrix               # also the CTAN directory into lib-ctan/nicematrix/ctan/
lctan --force nicematrix              # replace an existing vendoring
lctan --snapshot=2026-06-01 nicematrix
                                      # runfiles from the dated tlnet snapshot on texlive.info,
                                      # for a reproducible pin instead of the live mirror
lctan tikz-cd extarrows stackrel      # several at once; failures are reported per package
```

Result:

```
lib-ctan/<pkg>/
  ctan.json            the CTAN catalogue record, verbatim
  provenance.json      what was fetched: CTAN version/date/licence, TeX Live package,
                       revision, archive URL, SHA-512, snapshot date, list of runfiles
  tex/latex/<pkg>/…    the runfiles in TDS layout (for a bundle member: tex/latex/<bundle>/)
  ctan/                the CTAN directory or file, only with --docs
```

`provenance.json` is the record a binding header cites as what it was written from, and the record a future library manifest ingests. `lib-ctan/` is gitignored except for its README; the vendored trees are reproducible from `provenance.json` and are not committed.

## Use

**Which root.** `--outdir` defaults to `lib-ctan/`, the resident library: use it for a package the engine will read raw (a passthrough or hybrid delegates to it, a raw file requires it, or it is a data file) and for the source of a native binding kept for the census. Use `--outdir=lib-symb` for a notation vocabulary whose binding is generated from a table, and `--outdir=lib-park` for a package vendored ahead of demand with no binding. The roots and the rule for what may sit in `lib-ctan/` are [`architecture.md`](../architecture.md) section 5.

**Census with `texscan`.** Point it at the directory holding the `.sty`, and at `lib/` so it can see existing bindings and the pools (it defaults to `blib/`):

```powershell
perl tools/texscan --diff --path=lib-ctan/<pkg>/tex/latex/<pkg> --path=lib/LaTeXML/Package --path=lib/LaTeXML/Engine <pkg>.sty > temp\bindings\<pkg>\census-diff.txt
perl tools/texscan --stub --base=article.cls,amsmath.sty --path=lib-ctan/<pkg>/tex/latex/<pkg> <pkg>.sty
Move-Item <pkg>.sty.ltxml temp\bindings\<pkg>\stub.sty.ltxml
```

`texscan` warns `No stylefile found` for each dependency it cannot see and reports the package's own unimplemented control sequences. Internal `\l__pkg_…` names in that list are expl3 variables, not user surface, and do not need bindings.

**Passthrough or hybrid at runtime.** Put the same directory on the engine's search path and allow raw interpretation:

```powershell
lxml --includestyles --path=lib-ctan/<pkg>/tex/latex/<pkg> t\<pkg>\<case>.tex
```

This is how a package gets exercised empirically before deciding whether it stays raw, becomes hybrid, or is minted native; see `docs/specification/bindings.md` section 2.

## Not handled here

- Producing a `.sty` from a `.dtx` locally. Not needed while TeX Live carries the package; a package absent from TeX Live is a decision, not a fetch.
- Resolving dependencies. Deliberate; see above.
- Anything installed on the host. The script writes only under `--outdir`, and the engine never consults the host's TeX installation once the resident-library lookup replaces `kpsewhich`.
