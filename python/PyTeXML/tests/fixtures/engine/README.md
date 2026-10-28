# Engine-operation oracles

`integers.tex` records common TeX semantics exercised by `test_integer_operations.py`.
The `PYTEXML` log lines were captured using Tectonic 0.16.9+20260504 on
2026-10-27 (local date); their values are in `integers.expected.json`.
Ordinary unit tests read that evidence without starting a compiler. Tectonic's
XeTeX engine is an oracle for these common operations, not the identity or full
capability promise of PyTeXML.

Reproduce in a disposable output directory with the repository's existing
Tectonic cache and `tectonic -X compile --only-cached --untrusted --keep-logs
--outdir <output> integers.tex`. Keep the complete log when changing expectations;
do not generate expectations from PyTeXML. The initial run succeeded and had a
Fontconfig default-configuration warning, unrelated to the numeric log results.

The probes cover internal catcodes, raw backtick operands, signs and radix,
copied/scoped constants, frozen versus newly read number terminators, and the
temporary relax meaning of a chardef target. Negative values/range failures and
unimplemented expansion boundaries are separate Python tests; this fixture does
not claim they reproduce TeX's interactive error recovery.

## Command replacement arguments

`command-bodies.tex` and `command-bodies.expected.json` record Tectonic
0.16.9+20260504's `PYTEXML` log lines on 2026-10-27 (local date), with trailing
printer spaces removed. The kernel's `\@argdef` and `\@xargdef` consume the
replacement as a long, undelimited argument before defining the command:
[ltdefns.dtx](https://github.com/latex3/latex2e/blob/develop/base/ltdefns.dtx).
The underlying group/single-token capture is `macro_call` in
[tex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web).

The Python tests compare captured replacement text and long/star flags with
these observations; they do not claim to render `\meaning` or expand macros.
The probe also records local renewal restoration, absence of capture-time catcode
effects, and the command after a one-token replacement. Run it with the same
cached, untrusted compilation command above. The initial complete log is retained
in the repository's temp/pytexml-command-body-oracle; compilation succeeded with
the same unrelated Fontconfig warning.

## Macro expansion and expanded definitions

`macro-expansion.tex` and `macro-expansion.expected.json` record Tectonic
0.16.9+20260504's `PYTEXML` log lines on 2026-10-27 (local date), with trailing
printer spaces removed. Compilation succeeded using the cached, untrusted
invocation above; the complete log is retained in
`temp/pytexml-expansion-oracle` at the repository root. The same Fontconfig
warning did not affect the observations.

The probes cover replacement-to-source continuation, raw undelimited arguments,
copied meanings versus late name lookup, one-time `\noexpand`, expanded parameter
markers/numbers, and assignments captured without execution. The expanded
`\RequirePackage{xspace}` invocation is also observed to load the package.
`test_macro_expansion.py` compares stored token replacements to this recorded
evidence; `test_expanded_requests.py` checks the preparation consumer separately.
The simple test-only spelling of these replacements does not implement
`\meaning` or establish arbitrary package execution.

The relevant engine algorithms are `macro_call`, `scan_toks` with `xpand`
enabled, and `no_expand` in
[tex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web).
In particular, `scan_toks` expands the token following a parameter marker when
collecting an expanded definition. Unsupported continuations and expansion
operations remain explicit boundaries rather than approximations of TeX recovery.
