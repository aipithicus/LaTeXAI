# gauntlet-master fixture

A synthetic TeX payload that exercises, compactly, the cases found across the
gauntlet corpus (147 source trees). The case inventory is
`reports/gauntlet-master-inventory-20261027.md` in the private issues workspace.
`coverage.md` maps every case to its place here. Nested effects and catcode
mutations get the most coverage.

## Roots

The bibliography dialects can't share one document, so there are three roots
over shared inputs.

| Root | Dialect and data |
| --- | --- |
| `master.tex` (A) | natbib author-year. `refs.bib` with the jobname `master.bbl` (plainnat). This root carries every non-bibliography case. It is a wrapper main that reads the inner main `body/paper.tex`. |
| `master-biblatex.tex` (B) | biblatex with the BibTeX backend, reading `refs.bib`. `master-biblatex.bbl` holds `\entry` records. |
| `master-plain.tex` (C) | Kernel `\cite` with the `cite` package. An inline `thebibliography` that `\input`s pasted `dcu.bst` entries from `bib/pasted-dcu.bbl`. |

All three read `sections/cite-shared.tex`, and A and B share `refs.bib`.

## Layout

- `gmvenue.cls`, `gmstyle.sty`, `gmtools.sty`, `gmstyle.cfg`: the local class
  and packages.
- `body/`: the inner main and the author macros.
- `sections/`: the body, one file per inventory area, plus `sections/nested/`
  for depth 3–4.
- `figures/`: matplotlib `.pgf` and Inkscape `.pdf_tex` stand-ins. The
  `.pdf_tex` omits its image.
- `listings/`: inputs for `\lstinputlisting` and `\VerbatimInput`.
- `bib/`: the pasted `.bbl` fragment for root C.

## Compiling

Tectonic is the oracle, as in `src/validation/render.py`. Point its cache inside
the repository so downloads don't land in `%LOCALAPPDATA%`:

```powershell
$env:TECTONIC_CACHE_DIR = 'D:\aipithicus\LaTeXAI\temp\tectonic-cache'
tectonic -X compile --untrusted --keep-logs --outdir <out> master.tex
```

Compile from a copy of this directory, as `render.py` stages it. Each root
compiles with no errors and no undefined citations or references with Tectonic
0.16.9, whose bundle has LaTeX 2021-11-15.

**The two `.bbl` files are generated, not hand-written.** They are Tectonic's
BibTeX output for `refs.bib`, copied back after a compile, and Tectonic
regenerates them on every run. Copy them back again after changing `refs.bib`
or a citation.

## Quirks this fixture records

- **Tectonic defines `\pdfoutput`.** After `\pdfoutput=1`, iftex reports PDF
  mode and hyperref would load its pdfTeX driver. `body/paper.tex` passes the
  `xetex` option under `\ifXeTeX` (case P5).
- **File hooks don't fire under Tectonic.** The bundle's LaTeX 2021-11-15 still
  uses the old `file/before/<name>` hook names. The `file/<name>/before` hooks in
  `master.tex` (case N5) are accepted but never fire there; they fire on LaTeX
  2023-06 and later.
- **Tectonic's BibTeX drops spaces in `@string` values.**
  `"TeX Users Group"` comes out as `TeXUsersGroup` in both `.bbl` files.
- **The kernel `verbatim` drops the rest of its closing line.** That is why
  the `}` after `\end{verbatim}` in case V4 sits on its own line.
- **`sections/nested/deepest.tex` is checked out with CRLF line endings**
  (`.gitattributes` here, case E1).
