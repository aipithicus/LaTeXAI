# Generated native meanings

`root-a-20261029/meanings.jsonl.gz` contains 15,552 generated macro fixtures from
the pinned pdfTeX 1.40.29 / LaTeX2e 2026-06-01 / expl3 2026-09-09 format. Each
candidate passed native `\ifx` equality. `manifest.json` records the source,
binary, format, probe, implementation and artifact identities. Gzip uses a zero
timestamp; this is a frozen generated snapshot, not hand-authored expected data.

`tests/test_generated_native_meanings.py` replays every record through PyTeXML's
scanner and meaning representation, checking its full typed descriptor and
printed display. Native equality was established at generation time; the normal
test run does not execute these macro bodies or claim their runtime behavior is
implemented. Exception and non-macro inventories belong to the assay report.

Regenerate with the commands and qualification boundaries in
[the assay recipe](../../../../recipes/meaning-assay.md). Never overwrite this
basis silently: generate a fresh assay and fixture directory, review the change,
then update the test's selected basis and expected count.

The meaning data is derived from the native format, including LaTeX kernel and
expl3 source. The pinned `expl3-code.tex` identifies Copyright (C) 1990-2026 The
LaTeX Project; `latex.ltx` identifies Copyright (C) 1993-2026 The LaTeX Project
and individual authors. Their source notices specify the LaTeX Project Public
License, version 1.3c or later. The original source bundles remain the authority
for their notices; this generated fixture set is a separate diagnostic artifact,
not a modified upstream distribution. See the manifest for exact source hashes.
