# Engine oracles

Keep language semantics, primitive exposure, rendering and filesystem closure as
separate observations. Profiles own their declared oracle contract in
`resources/engine_profiles/*.yaml`; validation accepts explicit executables.
No reference engine is patched to hide primitives or impersonate another profile.

| Profile | Language evidence | Rendering instrument | Current qualification |
| --- | --- | --- | --- |
| etex (default, plus expanded) | Shared primitive fixtures under modern pdfTeX; historical e-TeX cannot witness expanded | LaTeX in DVI mode, then dvipdfmx | Shared capabilities only: installed etex/latex expose pdfoutput |
| pdftex | pdfTeX primitive fixtures | pdfLaTeX | Selected exposure probes match; full language/backend equivalence is not claimed |

Tectonic remains an additional XeTeX instrument. The installed binary also exposes
`\pdfoutput`, so its name alone is not evidence for or against a feature probe.
Future concrete XeTeX/LuaTeX profiles need their own definitions and tests.

## Local toolchain

This development run installed portable TeX Live 2026 under the repository's
ignored `temp/texlive-oracle/`. It made no global PATH, file-association or registry
changes. Binaries are in `bin/windows/`; `pdflatex.exe`, `latex.exe` and
`dvipdfmx.exe` are the native rendering tools.

Installation used the official TeX Live installer, its bundled Windows Perl, and
`scheme-basic`, with documentation/source packages disabled. The installer was
downloaded from `https://mirror.ctan.org/systems/texlive/tlnet/install-tl.zip`;
SHA-256 was `d79ee553f4795d8f947fe1d65a5e7797dbf748aa4802bc0d8048d4f47881b9d4`.
The resolved repository was `https://mirrors.rit.edu/CTAN/systems/texlive/tlnet`.
The exact installation profile, installer and package database remain under
`temp/oracle-bootstrap/` and `temp/texlive-oracle/tlpkg/`.
This rolling mirror is not a reproducible historical package snapshot: preserve
that database and an archive of the toolchain when pinning a release oracle.

Run paired native renders with:

~~~text
python -B -m src.validation.render <original> <main.tex> <prepared> <new-report> --backend pdftex --compiler <bin>/pdflatex.exe
python -B -m src.validation.render <original> <main.tex> <prepared> <new-report> --backend etex --compiler <bin>/latex.exe --dvipdfmx <bin>/dvipdfmx.exe
~~~

The prepared manifest supplies its profile. For older payloads, pass
`--engine-profile etex|pdftex`. The report retains the primitive probe, tool
hashes/version, final compiler logs, rerun hashes and independent results for
both payloads. Native auxiliary files must settle within four passes.
External bibliography/index processors are not invoked.

A profile mismatch does not discard useful PDF observations, but it prevents
the result from being reported as a matched profile. DVI output mode alone does
not remove pdfTeX primitives. No exact modern renderer for the deliberately
restricted default profile has been qualified yet.

Native filesystem closure auditing is not implemented. The `qualify` command
still requires the Tectonic backend; native `render` is independent paired
rendering evidence, not relocation qualification.

## Language witnesses

`tests/fixtures/engine/meaning-comparison.tex` has 32 expected observations;
`expansion-continuation.tex` has six. The checked-in JSON files are compared
with PyTeXML's results, and both fixtures were also compiled unchanged by
pdfLaTeX and LaTeX/DVI in this run. Their language tests are independent of
the disputed engine-identity branch.

The live native adapter test is enabled with `PYTEXML_TEST_NATIVE_DIR` pointing
to the binary directory. It checks a simple paired PDF and DVI document and
verifies that the default-profile mismatch stays visible.
