# Root A oracle baseline · 2026-10-29

Step 1 of the active language-core plan now has a pinned native target, a
successful unchanged Root A baseline, and a concrete first source boundary.
The machine-readable receipt is
[root-a-pdftex-20261029.json](oracle-pins/root-a-pdftex-20261029.json).
This qualifies the original native program and the bounded native source
witness. Python bootstrap and original/prepared rendering equivalence remain
separate, unfinished gates.

## Target and preservation

| Component | Pinned target |
| --- | --- |
| Native engine | pdfTeX 3.141592653-2.6-1.40.29, TeX Live 2026, Windows |
| Kernel | LaTeX2e 2026-06-01 patch 0 |
| Programming layer | expl3 2026-09-09 |
| Patching package | etoolbox 2025/10/02 v2.5m |
| Profile | Concrete `pdftex`; the default `etex` plus `expanded` is unchanged |
| Output | PDF, selected by Root A's original `\pdfoutput=1` |

The local portable installation was completed with 27 missing packages and font
resources. Existing installed-package revisions did not change. The complete
10,089-file tree, including binaries, formats, format-generation logs, sources,
package database, maps and fonts, was archived and every file was checked after
extraction at a different path. Archive, file-inventory and package-database
hashes are in the pin. This is a local native oracle snapshot; it does not
implement the separate `lib-tex` source-procurement system or a Python state cache.

The large toolchain archive and evidence archive are local, ignored artifacts,
not remotely published dependencies. Their location and hashes are recorded in
the pin. Preserve both before cleaning development receipts. Reinstalling from
the rolling CTAN mirror does not reproduce this pin.

## Original program and replay

The original `tests/fixtures/specimens/gauntlet-master/master.tex` was copied
byte-for-byte with its source/resource inventory. No entry hook, SVG bootstrap,
source repair or engine-identity substitution was injected. All staged source
bytes remained unchanged after rendering.

Both the installed and independently restored toolchains:

- Matched the concrete `pdftex` primitive-exposure probe.
- Rendered five pages, with the tracked auxiliary hashes stable after two
  passes. All native compiler invocations returned zero.
- Read the supplied `master.bbl` unchanged. No BibTeX/Biber process ran;
  this establishes use of the supplied bibliography, not its regeneration
  from `refs.bib`.
- Produced identical extracted page text, identical page pixels at 144 dpi,
  the same auxiliary hashes and the same selected runtime trace.
- Recorded 27 distinct source, 5 generated and 293 oracle input paths in the final FLS,
  with matching hashes across the relocated replay and no recorded input
  outside those roots or missing on inspection.

The selected trace is `gmstyle: loaded`, `gauntlet-master: document begins`,
`paragraph`, `gmtools: entering math`, then `left math`. The PDF includes the
patched optional-command results `[dflt)` and `[set)`, and the supplied
bibliography. No unresolved citation/reference warning remained. Existing
warnings were retained: two Unicode redefinitions, disabled shell escape for
epstopdf, one overfull box, amsmath's two foreign-command warnings and an `h`
float placement adjustment. Successful rendering does not mean warning-free
source or prove every fixture expectation.

The FLS comparison is observed TeX input evidence. It is not an OS filesystem
sandbox, a dynamic-library inventory or general native closure certification.
This check does not change the qualification of prepared Root A or roots B–D.

## First source boundary

The [kernel-optional fixture](../tests/fixtures/engine/kernel-optional/README.md)
pins byte ranges, fragment hashes, explicit initial state and expected
observations. The unmodified kernel fragments create the optional public wrapper
and hidden implementation. Their native INITEX result matches the full format's
12 observations, including argument selection, aliases and local restoration.
The fixture identifies the excluded error paths and required language behavior.
It is ready to drive the Python work in steps 2–4; it is not an executed Python
bootstrap or full kernel/expl3 initialization.

## Replay procedure

1. Verify the toolchain ZIP and evidence ZIP against the pin before extraction.
   Extract the toolchain to a fresh path and check every extracted file against
   `oracle-files.json` from the evidence archive. Do not update that tree with
   `tlmgr` while using this target.
2. Make a fresh byte-exact fixture copy and separate empty build directory. Keep
   the job name `master` and the supplied `master.bbl`. Verify the source manifest
   from the evidence archive; its fingerprint is SHA-256 of the UTF-8 JSON list
   sorted by path, with `sort_keys=True` and Python's default JSON separators.
3. Use explicit binaries from the restored tree. Remove inherited `TEX*`, `BIB*`
   and `BST*` environment overrides; set `TEXMFHOME`, `TEXMFCONFIG` and `TEXMFVAR`
   to separate empty local directories. Prepend only the chosen native binary
   directory for this process. These are local-run settings, not global changes.
4. From the source directory run `pdflatex -interaction=nonstopmode
   -halt-on-error -no-shell-escape -recorder -output-directory=<build> master.tex`
   until the auxiliary hashes settle, bounded at four passes. The existing
   `src.validation.compilers.compile_document` owns that loop. The accepted run
   settled in two; do not invoke an external bibliography processor.
5. Retain logs, FLS, auxiliary hashes, source hashes and PDF observations. Compare
   against the pin and its evidence. PDF file hashes may vary with metadata;
   use the recorded page text/pixels and trace for replay equivalence. A normal
   paired-render staging call adds its SVG hook, so it is not the byte-exact
   original-baseline procedure used here.

The evidence archive also preserves the local orchestration scripts and native
receipts. They use the existing compilation/profile adapter; this milestone adds
no second compiler backend, engine evaluator or runtime metadata registry.
