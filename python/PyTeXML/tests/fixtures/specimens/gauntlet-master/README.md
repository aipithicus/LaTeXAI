# gauntlet-master fixture

A synthetic TeX payload that exercises, compactly, the cases found across the
gauntlet corpus (147 source trees). The case inventory is
`reports/gauntlet-master-inventory-20261027.md` in the private issues workspace.
`coverage.md` maps every case to its place here. Nested effects and catcode
mutations get the most coverage; the structural workhorses (lists, tables,
algorithms, cross-references, figures) get one compact instance each.

## Roots

The bibliography dialects can't share one document, so there are four roots
over shared inputs.

| Root | Dialect and data |
| --- | --- |
| `master.tex` (A) | natbib author-year. `refs.bib` with the jobname `master.bbl` (plainnat). This root carries every non-bibliography case. It is a wrapper main that reads the inner main `body/paper.tex`. |
| `master-biblatex.tex` (B) | biblatex with the BibTeX backend, reading `refs.bib`. `master-biblatex.bbl` holds `\entry` records. |
| `master-plain.tex` (C) | Kernel `\cite` with the `cite` package. An inline `thebibliography` that `\input`s pasted `dcu.bst` entries from `bib/pasted-dcu.bbl`. It also carries the upper-case `algorithmic` dialect, which can't share root A with algpseudocode. |
| `master-arxiv.tex` (D) | The arXiv pattern. `\bibliography{arxiv-stripped}` names a database that isn't shipped; only `master-arxiv.bbl` is. |

Every root reads `sections/cite-shared.tex`. A and B share `refs.bib`, and A and
D cite the same keys, so `master-arxiv.bbl` is identical to `master.bbl`.

## Layout

- `gmvenue.cls`, `gmstyle.sty`, `gmtools.sty`, `gmstyle.cfg`: the local class
  and packages.
- `body/`: the inner main and the author macros.
- `sections/`: the body, one file per inventory area, plus `sections/nested/`
  for depth 3–4.
- `figures/`: matplotlib `.pgf` and Inkscape `.pdf_tex` stand-ins (the
  `.pdf_tex` omits its image), and `swatch.png`, an 88-byte image for
  `\includegraphics`.
- `listings/`: inputs for `\lstinputlisting` and `\VerbatimInput`.
- `bib/`: the pasted `.bbl` fragment for root C.

## Compiling

This directory is in the specimen catalog (`../catalog.yaml`) as
`gauntlet-master-natbib`, `-biblatex`, `-plain` and `-arxiv`, one entry per root,
so the specimen harness prepares, renders and qualifies it like the paper
specimens.

Tectonic is the oracle, as in `src/validation/render.py`. The harness keeps
Tectonic's cache in the repository's `temp/tectonic-cache` unless
`TECTONIC_CACHE_DIR` is already set. Set it yourself when running Tectonic by hand:

```powershell
$env:TECTONIC_CACHE_DIR = 'D:\aipithicus\LaTeXAI\temp\tectonic-cache'
tectonic -X compile --untrusted --keep-logs --outdir <out> master.tex
```

Compile from a copy of this directory, as `render.py` stages it. Each root
compiles with no errors and no undefined citations or references with Tectonic
0.16.9, whose bundle has LaTeX 2021-11-15.

**The `.bbl` files are generated, not hand-written.** They are Tectonic's BibTeX
output for `refs.bib`, copied back after a compile, and Tectonic regenerates
them on every run. Copy them back again after changing `refs.bib` or a citation.

**Root D needs the stripped database restored before Tectonic can check it.**
Tectonic always reruns BibTeX, even with `--reruns`. Against the missing
database, BibTeX overwrites `master-arxiv.bbl` with an empty bibliography and
the citations come out undefined, although the exit status is 0. arXiv never
runs BibTeX, so there the shipped `.bbl` is used. To check root D, copy
`refs.bib` to `arxiv-stripped.bib` in the staged copy, compile, and compare the
regenerated `master-arxiv.bbl` with the shipped one. They are byte-identical.

## Quirks this fixture records

- **Tectonic defines `\pdfoutput`.** After `\pdfoutput=1`, iftex reports PDF
  mode and hyperref would load its pdfTeX driver. `body/paper.tex` passes the
  `xetex` option under `\ifXeTeX` (case P5).
- **File hooks are keyed by the file's base name.** `\input{sections/math}`
  runs `file/math.tex/before`: `\CurrentFile` is `math.tex`, and the directory is
  in `\CurrentFilePath`. A hook named `file/sections/math.tex/before` is accepted
  and never runs. That is why case N5 in `master.tex` hooks `math`. The old
  (`file/before/<name>`) and new (`file/<name>/before`) spellings both work in
  the bundle's LaTeX 2021-11-15.
- **Tectonic's BibTeX drops spaces in `@string` values.**
  `"TeX Users Group"` comes out as `TeXUsersGroup` in both `.bbl` files.
- **The kernel `verbatim` drops the rest of its closing line.** That is why
  the `}` after `\end{verbatim}` in case V4 sits on its own line.
- **`sections/nested/deepest.tex` is checked out with CRLF line endings**
  (`.gitattributes` here, case E1).
