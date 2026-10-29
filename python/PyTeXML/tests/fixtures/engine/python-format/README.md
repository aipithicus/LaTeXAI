# Python format adaptation witness

`witness.tex` runs in the pinned native environment described in
[`root-a-oracle-baseline.md`](../../../../recipes/root-a-oracle-baseline.md).
Run from this directory with `pdflatex -halt-on-error -no-shell-escape`, sending
outputs to an external working directory. The 2026-10-29 replay succeeded and
its `PYFORMAT:` observations are transcribed in `expected.json`.

The production path uses Python routines in `src/engine/latex/`. This TeX file
and the earlier `kernel-optional` fragments are reference/test material only.
`test_latex_format.py` checks ordinary native macro state; `test_format_file_tests.py`
checks file selection, side effects, resource retention and search boundaries.

Zero-arity `newcommand` is not long in this pinned kernel. Older
`command-bodies.expected.json` evidence is retained with its original flags;
its capture tests use only the body text. This receipt does not establish full
kernel/expl3 compatibility or prepared Root A render equivalence.
