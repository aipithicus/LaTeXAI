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

## Global definitions and restoration

`global-definitions.tex` and `global-definitions.expected.json` record Tectonic
0.16.9+20260504's `PYTEXML` observations on 2026-10-28 (local date).
The JSON is extracted from the independent compiler log, not PyTeXML output.
Reproduce with the cached, untrusted command above; the initial complete log is
retained at the repository's `temp/pytexml-global-definitions-oracle`.
Compilation succeeded with the same unrelated Fontconfig warning.

The observations cover a global write beneath multiple local writes, local
assignments following it, repeated global definitions, `\xdef` reading the old
target, copied primitive meanings, active-character identity, and T13/T14 frozen
categories surviving lexical restoration. `test_global_definitions.py` compares
the resulting replacements and categories with those observations. Failed
definitions and speculative context rollback are separate Python tests.

The underlying TeX algorithms are `geq_define` and `unsave` in
[tex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web).
The journal implementation removes superseded restoration entries eagerly;
TeX retains the global level when it later processes those entries. Neither
mechanism restores a value that predates a successful global write.

## Expanded integer operands and format constants

`integer-expansion.tex` records Tectonic 0.16.9+20260504 observations on
2026-10-28. Its expected JSON is extracted from `PYTEXML` log lines, grouping
the two lookahead observations in order. The full log remains at the repository's
`temp/pytexml-integer-expansion-oracle/integer-expansion.log`. Compilation succeeded
with the same unrelated Fontconfig warning. Use the cached, untrusted command
above to reproduce it.

The probe covers mutable/copied/restored `\active`, macro-produced signs, radix
and operands, internal category reads, raw backtick tokens, frozen versus unread
source lookahead, optional-equals expansion, one-time suppression and a chardef
target's provisional relax meaning. `test_integer_expansion.py` compares these
observations with the Python consumer; continuation boundaries and failed
publication are tested separately.

The bootstrap declaration `\chardef\active=13` is in
[ltplain.dtx](https://github.com/latex3/latex2e/blob/develop/base/ltplain.dtx#L118),
v2.3m dated 2025-04-14. The numeric algorithms are `scan_int` and
`scan_optional_equals` in
[tex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web).
An initial format value does not prove that intervening unexecuted code preserves it.

## Integer parameter cells

`integer-parameters.tex` records common-TeX parameter behavior with Tectonic
0.16.9+20260504 on 2026-10-28. Its expected JSON is extracted from the compiler's
`PYTEXML` lines and consumed by `test_integer_parameters.py`. It covers nested
local restoration, copied primitive references surviving a spelling redefinition,
internal reads, expanded operands, assignment reading its old value and both
signed integer limits. Reproduce with the cached, untrusted command above.
The full log is retained at the repository's
`temp/pytexml-integer-parameters-oracle/integer-parameters.log`; compilation
succeeded with the unrelated Fontconfig warning.

The pdfTeX-specific declaration is source-checked against
[pdftex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/pdftexdir/pdftex.web):
`pdfoutput` uses `assign_int` at `pdf_output_code`; assignment uses
`scan_optional_equals`, `scan_int` and `word_define`.
Tectonic's XeTeX is not a live oracle for that primitive or the PDF backend.
No default parameter value or engine identity is inferred from these probes.

## Legacy option forwarding

`option-forwarding.tex` and the four `of-*` class/package files exercise
actual LaTeX loads, default and starred ordering, `ExecuteOptions` restoration,
`ProcessOptions` cleanup, aliased `CurrentOption`, and forwarding to both
a base class and a package. `option-forwarding.expected.json` was extracted
from Tectonic 0.16.9+20260504's `PYTEXML` log lines on 2026-10-28; the cached
format reports LaTeX2e 2021-11-15 patch 1. The Python test reads the same source
files and compares their resolved effects to those independent observations.
Kernel list serialization has a trailing empty item; resolved request lists
omit it. The full log and invocation receipt are in
`temp/logs/pytexml-option-forwarding/oracle-output/` and
`temp/logs/pytexml-option-forwarding/oracle/` at repository root.
Compilation succeeded with the unrelated Fontconfig warning.

The implementation was also checked against the current
[ltclass.dtx](https://github.com/latex3/latex2e/blob/develop/base/ltclass.dtx):
`@pass@ptions`, `@process@ptions`, `@xprocess@ptions`,
`@process@pti@ns`, `ExecuteOptions`, and `LoadClass`.
This supports fully resolved legacy lists, not protected expansion, key/value
option frameworks, filename hooks, or arbitrary execution inside option bodies.
Expansion-produced spaces are an explicit boundary: the kernel removes source
spaces before expansion, so dropping spaces afterward would change semantics.

## Raw meaning comparison

`meaning-comparison.tex` records 30 raw `ifx` decisions and two format entry
observations using Tectonic 0.16.9+20260504 on 2026-10-28. Its cached format
reports LaTeX2e 2021-11-15 patch 1. Both `undefined` and `@undefined` have
undefined meaning in that baseline; this supports two explicit initial facts,
not a rule that an uncatalogued command is undefined.

The witness compares character aliases and chardefs, parameter cell identities,
primitive definition variants, booleans, raw spaces/braces, active characters,
macro flags, parameter delimiters/marker characters, doubled markers,
hash-brace definitions, expanded replacements and scope restoration.
Conditional bodies store results; all diagnostic output occurs afterward.
The Python test reads that same prefix and compares its stored results with
`meaning-comparison.expected.json`, independently extracted from the TeX log.
Diagnostic expansion itself is not executed by the Python witness.

The implementation also follows
[TeX82 tex.web](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web),
sections 506–507: raw command/operand comparison, or compiled macro token lists
with their flags. References inside macro bodies compare token identity without
expanding or looking up those tokens' current meanings.
Optional-argument wrappers and collecting environments are not compiled into
TeX macro meanings. Unsupported comparisons remain deferred; copied command
meanings can still be recognized. Executing `ifx` while expanding an edef
replacement requires a separate expansion continuation.

Oracle receipt and full log, at repository root:
`temp/logs/pytexml-ifx/oracle-final/result.json` and
`temp/logs/pytexml-ifx/oracle-final-output/meaning-comparison.log`.
Compilation succeeded with the unrelated Fontconfig warning.

## Expansion continuation and native profiles

`expansion-continuation.tex` and its expected JSON cover exactly-once expansion,
constructed definition targets, nested expanded lists, reinsertion after
noexpand, execution of one resulting definition, and local name restoration.
The Python test also validates the resulting source-coverage partition.

On 2026-10-28, both this fixture's six witnesses and meaning-comparison's
32 observations matched unchanged native pdfLaTeX and LaTeX/DVI runs.
These are shared-language witnesses, not full engine-profile equivalence.
See [engine oracles](../../../recipes/engine-oracles.md) for configuration.
