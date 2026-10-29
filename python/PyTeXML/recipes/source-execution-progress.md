# Source execution checkpoints

## 2026-10-29: current load markers

Package/class load guards query the current `ver@<name>.sty` / `.cls` meaning.
The loader installs an empty global marker before entering source, matching the
pinned kernel's load path. Explicit definitions, aliases, `relax`, undefinedness
and group restoration therefore affect subsequent requests and loaded tests.
The historical load unit remains evidence; it cannot override a changed meaning.
Unavailable effects make a guard uncertain. Such declarations remain visible,
retain available source resources and causal requirements, and do not activate
reading knowledge on the assumption that package source executed.

Validation: 1,118 tests, 1,115 passed and three skipped. All nine specimen attempts
completed in `20261029-load-markers`, including gauntlet-master A-D. Eight master
texts are unchanged; LoopArena retains `preamble/commands.tex` and
`sections/appendix.tex` because intervening unknown source can change load guards.
Root A's master remains 511 characters; its retained figure source keeps the EPS
route instead of requesting the previous derived SVG. Its lower unresolved count
does not signify greater execution coverage. This checkpoint does not qualify
render equivalence or the forthcoming kernel/package execution gate.

Native boundary evidence: with the pinned LaTeX format, a child ending in an
optional command sees the default through braced `\input{child}`, while unbraced
`\input child [set]` consumes the caller's optional argument. The braced route
has kernel file-return tokens before caller input (latex.ltx 19935-19964).
Do not implement EOF by indiscriminately peeking directly into a parent file.
Receipts: `temp/engine-source-work/load-suite-2`, `load-specimens`, and
`optional-eof-native-run`. These are local evidence, not shipped runtime sources.
