# Source execution checkpoints

## 2026-10-29: review reconciliation and recovery direction (planning only)

The user clarified the product contract: recover useful content from broken
LaTeX by default, including severe source failures. Strict rejection is
user-selected. An active missing asset produces a typed error tombstone at its
expected output position and a correlated log record; surrounding extraction
continues. Author-provided fallbacks execute through the engine and take
precedence over generated recovery. A failure must not suppress discovery of
independent failures. Scope consequences and preserve assumptions where recovery
continues without complete language-state knowledge.

The [staged pipeline §6.1](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-staged-resolution-pipeline.md#61-failure-consequences-continued-discovery-and-recovery-policy)
owns that contract. The [active plan](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-language-core.md#active-implementation-plan)
owns dispatch: continued discovery/recovery and computed-resource closure can
advance before full expl3/package integration. These are planned changes; the
runtime still raises on some required dependency and materialization failures.
No new implementation or qualification is claimed by this entry.

Reconciliation with the [roundup review](../../../../aipithicus-issues/LaTeXAI/briefs/feedback/opus-roundup-review.md):

- D5's `gmlogo.pdf` is intentionally absent. Its false branch defines `gm@logo`
  as `no logo`; the existing recorded false decision is correct. It must not be
  turned into an asset requirement or a fabricated file. Active missing-image
  references need their own typed-tombstone recovery witnesses.
- `gmlisting` is declared in `body/paper.tex` and requests the existing
  `listings/snippet.py` through a computed path. Close that request through its
  actual invocation context. The prepared render's first failure does not prove
  that it is the only remaining failure.
- Add differential declaration coverage and make successful-declaration target
  assumptions explicit. The Python hidden-before-public assignment order differs
  from pinned kernel source; collision/restoration cases need qualification.
- A native hit-state receipt already records `@filef@und` as the relative quoted
  `etoolbox.sty` name. The tracked witness still overwrites the hit before
  inspection, so promote that observation into the reusable fixture.
- The search fingerprint is names-only and the index is rebuilt per session.
  Preserve that scope, then qualify content identity, snapshot reuse and native
  duplicate-path ordering. Current ambiguity refusal is conservative, not a
  qualification of native search precedence.
- The newer L14 direction in issues commit `6db82c3` makes expl3 engine-native;
  it supersedes the review's runtime source-loading suggestion. Constructing
  ordinary macro meanings informs binding design without establishing a new
  overlay/replace precedence mode.

## 2026-10-29: Python format routines and explicit file search

The user clarified the implementation boundary: adapt kernel routines in Python;
retain kernel TeX fragments as reference/oracle fixtures; execute package source
through the shared language engine. This entry supersedes the earlier proposal
below to load kernel fragments in normal preparation.

Normal preparation now uses `src/engine/latex/` for new/renew/provide-command
declarations and optional dispatch. The immutable format registry selects Python
operations. Native public/hidden macro meanings share the ordinary scope table,
scanner and token-origin machinery. Authored `CommandDefinition` objects remain
observations. The operational declaration bridge and its YAML recipes are removed.
Aliases see later changes to hidden implementations with the same argument grammar.
Changed hidden grammars, non-typesetting protection and pure-expansion requests
remain explicit boundaries. Private scratch meanings not yet adapted exactly are
marked uncertain with scope restoration; no old value is silently kept.

`IfFileExists` now resolves project files, literal `input@path` directories and
configured external roots, selects the branch and records the search evidence.
It maintains the bounded kernel file-test meanings, retains the test in emitted
TeX, and packages local presence-tested resources as bytes. Definite missing
`InputIfFileExists` also executes its else branch. Finding an external source does
not assert its execution. The [iteration recipe](specimen-iterations.md) documents
the API/CLI and the distinction between omitted search configuration and an
explicit project-only environment.

The [native format witness](../tests/fixtures/engine/python-format/README.md)
matches public/hidden macro meanings, zero-arity flags and missing-file state on
pdfTeX 1.40.29 / LaTeX 2026-06-01. The configured native resource query finds
`etoolbox.sty` and confirms `gmlogo.pdf` absent. Root A's file-test decision is now
false with explicit search evidence; its first broad state-uncertainty cause is
the unsupported `seq_new:N` in `gmvenue.cls`, followed by unexecuted etoolbox and
configuration-file continuation work.

All nine attempts finish in `20261029-python-format-files-final`. Compared with
the previous `20261029-source-scope-closure` checkpoint:

| Specimen | Preparation | Master characters | Unresolved | Change |
| --- | --- | ---: | ---: | --- |
| 2306.01911v1 | partial | 105849 | 0 | Same master/count |
| 2405.15943v3 | partial | 67710 | 1 | Optional declaration now needs the actual `escapechar` |
| 2412.11340v4 | complete | 133513 | 0 | Same master/count |
| 2512.18792v1 | partial | 169440 | 1 | Same master/count |
| 2608.28281v2 | partial | 69902 | 3 | Same master/count |
| Root A | partial | 754 | 4 | File test resolved; later language state still unresolved |
| Root B | partial | 1136 | 1 | Same master/count |
| Root C | partial | 1913 | 1 | `providecommand` cannot establish the prior `harvarditem` meaning |
| Root D | partial | 1866 | 2 | Uncertain `doi` meaning retains supplied BBL |

The narrower treatment of `providecommand` exposes a real initialization gap.
An unknown name is not assumed undefined, and a possibly existing definition
does not acquire the supplied replacement as a known meaning. Root D previously
crashed when bibliography processing mistook the retained BBL for a malformed
environment. It now preserves the declaration and byte-exact jobname BBL, with
a reading requirement. These changed statuses are not reported as coverage gains.
All nine copied-payload rereads preserve statuses and unresolved counts.
The full suite ran 1,160 tests: 1,157 passed and three skipped. The scoped registry
type check passed for 18 source files. A final native-backed external-file-state
correction has its own ten passing file tests: absolute lookup provenance stays
separate from the relative filename in `@filef@und`. Root A's retained `refs.bib`,
supplied `master.bbl` and `listings/prompt.txt` match the original contents.

A separate `pdftex` Root A preparation/render attempt is recorded in
`20261029-python-format-root-a-pdftex`. Native profile exposure matches; unchanged
original source renders five pages in two converged passes. Prepared compilation
fails at `gmlisting{snippet.py}` because `listings/snippet.py` is not packaged.
The compiler reports `Package Listings Error: File listings/snippet(.py) not found`.
Computed external-literal dependency closure remains open. This checkpoint does
not qualify prepared Root A render equivalence.

The next-increment ordering at this checkpoint was: establish the relevant format namespace and Python expl3/kernel
declaration routines; integrate package-source execution with explicit resource
ownership; then close computed resource requests and rerun paired native rendering.
The recovery clarification above revises that ordering in the active plan.
Keep the original source witnesses, initialization gaps, source continuation,
declaration observations and output qualification separate.

Local receipts are under `temp/bootstrap-work/`: native-format-run,
native-state-tests, file-state-final, registry-types-final, python-suite-verified, all-nine-final,
reread-run and root-a-render. Earlier failed attempts are retained as diagnostic
history, not accepted qualification.

## 2026-10-29: selected kernel and package source execution

The shared engine executes the pinned kernel definitions that construct optional
commands, then the selected etoolbox 2.5m patching source. Public wrappers, hidden
implementations, aliases and local restoration use ordinary current meanings.
The source recipes, expected observations and scope are in the
[kernel-optional fixture](../tests/fixtures/engine/kernel-optional/README.md).
Python matches all 12 kernel observations and seven package observations; the
selected-source and full-format native witnesses also agree. No Python handler
implements `patchcmd` or manufactures the hidden implementation.

The source prerequisites now include raw delimited macro arguments, definition
prefixes/protection, global assignment overrides, character/name/integer tests
inside expansion, token-display conversions, typed count/dimension cells, frozen
`futurelet`, and definition-only `scantokens`. Families declare operations in the
existing immutable catalog. Raw observation remains a separate capability; adding
expansion did not authorize execution inside retained source. Failed assignments,
predicates and generated definitions restore state, continuation and provenance.

An unexecuted command can make `globaldefs` unknown. For retained native `def`/
`gdef`/`edef`/`xdef` and `let` assignments, both possible scopes establish the same
current meaning. Preparation records that value and an `assignment_scope`
interpretation requirement, while marking every enclosing restoration uncertain.
It neither guesses a lifetime nor stops the rest of the file. Later definite
global writes clear those restoration entries. Bounded setup execution still
requires definite assignment scope. Register and reading-state assignments retain
their explicit boundary where equivalent uncertainty representation is unavailable.

Preparation uses `endinput` as a native operation, including the
`expandafter/endinput/fi` idiom. A braced LaTeX input's return continuation can
establish an omitted optional argument at child EOF. Flattening then emits an
inert lookahead barrier, with a line break if the child ends in a comment. Original
and prepared native witnesses agree on the selected default, page text and exact
144-dpi pixels. `lstinline` uses its reader grammar for options and raw delimiter
or brace-terminated bodies; it is not a primitive.
The barrier's spelling and current meaning are checked before and after the setup
body; redefining it rejects and rolls back the request rather than emitting it.

**Boundaries:** physical `futurelet`, unbraced cross-file optional lookahead,
general pseudo-file execution, kernel diagnostic closures and full kernel/expl3
startup remain unresolved capabilities. The source gate uses an explicit ASCII
primitive initial state and pinned external sources. Default preparation still
uses its captured-declaration bridge; automatically installing this boundary and
retiring that bridge requires a source/bootstrap and declaration-observation
integration step. This witness does not qualify prepared Root A render equivalence.

**Final verification (`bbe87f1`):** 1,145 tests run, 1,142 passed and three skipped.
All nine attempts in `20261029-source-scope-closure` finish without process errors.
Master bytes, preparation statuses and unresolved counts match `20261029-load-markers`.
Root A remains partial at 511 characters with five unresolved diagnostics; roots
B/C/D remain partial/complete/complete. BFPCA remains complete with its uncertain
assignment lifetime recorded as an interpretation requirement. The intermediate
publication crash and scope-uncertainty regression are preserved in their earlier
batch receipts; both are resolved in this checkpoint.

All nine copied-payload rereads preserve statuses and unresolved counts. Root A's
`refs.bib`, supplied `master.bbl` and `listings/prompt.txt` remain byte-exact. Eight
reread masters match the older bounded-setup reread; LoopArena reflects the load
guard retention change already recorded below. Rereading is not generally byte
idempotent and is not a rendering proof. The next Root A state gate is its
unresolved `IfFileExists` call in `gmvenue.cls`, which propagates uncertainty to
`globaldefs` and `escapechar`; grammar-provider activation also remains unresolved.

Local receipts are under `temp/engine-source-work/`: `scope-suite`,
`scope-specimens`, `scope-rereads`, `compare-scope-rereads`, `patch-native-run`,
`return-native-run` and `return-native-current`. The final specimen batch's
`NOTES.md` preserves the five-diagnostic cause/remaining-work scorecard.

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
