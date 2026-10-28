# Integer-operation oracle

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
