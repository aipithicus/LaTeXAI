# Source execution checkpoints

This file records implementation and qualification evidence. Current priorities
live in the [working queue](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-language-core/working-queue.md);
dated next-step statements below describe their checkpoint, not current dispatch.

## 2026-10-30: expanded-list insertion and generated-definition qualification

The [shared insertion implementation](behavioral-atlas.md#expanded-list-insertion-implementation)
distinguishes a `the_toks`-style token-list result from an ordinary expanded token.
Expanded-definition/list consumers copy it; ordinary expansion reinserts it as
input. The definition consumer encodes literal parameter markers in its existing
lexical representation while preserving original token occurrences and authored
capture. Work remains budgeted and publication uses the existing transaction.
A parameter-number scan inside `edef` uses ordinary expansion, not list copying.
No permanent suppression flag, helper intrinsic or native-answer installation is
used for this behavior. A pinned pdfTeX 1.40.29 source reference records the
`the_toks`/`scan_toks` algorithm separately from native binary qualification.

P03 exposed a second general issue: a valid bounded program ended by expanding
its recursion tail to nothing. Rejecting the absent executable token rolled back
the definition already created. The program continuation now accepts that empty
completion; a minimal native `P03-tail` witness matches. Physical-source and
suppressed-token continuation admission are unchanged.

**Current qualification:** 14 programs produce 40 native observations and five
native-`ifx`-qualified target descriptors, captured/replayed in 28 fresh native
processes. Python completes 11 comparisons and 29 observations, with all five
typed targets matching. P03 now derives the native-equal `mytest:NF` definition
from the original generator source. M02 still matches all eight observations.
Seven of P02's nine numbered expressions match, including T5.4, which previously
returned `\aaa ` where native returned `x`. Additional insertion contrasts cover
aliases/shadowing, protected tokens, nested definitions, local/global scope and
expanded parameter-number scanning. Observation-only cases are explicitly
separate from typed-target qualification; full original documents remain unrun.

Three execution boundaries remain, with literal harness diagnostics:

```text
P02-7: undefined_control_sequence: 'toks' is established undefined
P02-8: expanded_argument: expanded requires a balanced group
P03: undefined_control_sequence: 'romannumeral' is established undefined
```

The native primitives `toks` and `romannumeral` are absent from the implemented
Python profile; the current established-undefined report is an exposure gap,
not the native truth. P02-8 reaches a begin-group character alias. P03's failure
is now in invocation, after definition generation, and its probe transaction
rolls back all nine observations. None is counted as matching. Next gates are
general roman conversion and P03 invocation, typed token registers/`the`, and
group-opening aliases. No automatic staged resolver or full bootstrap is claimed.

The 23 focused macro-expansion tests pass, including original-occurrence checks,
bounded insertion work and rollback when a later raw parameter is invalid. A
test-authoring error initially read nonexistent `SourceSpan.text`; the corrected
test slices the reader's source at the retained span. The failed test receipt is
repository `temp/atlas-insertion-qualified-receipt`; it never ran native probes.
The pre-change native acquisition is PyTeXML
`temp/behavioral-atlas/20261029-insertion-before`, retained separately from the
final `temp/behavioral-atlas/20261029-insertion-qualified` receipt. Final outer
native/focused-test receipt: repository `temp/atlas-insertion-qualified-rerun`.
The run identifiers retain the start date; work completed across local midnight.

The full Python suite completed **1,229 tests: 1,226 passed and three skipped**
in 675.745 s. The skips are the optional live compiler-backend, relocation and
graphics-render adapter checks, whose explicit tool configuration was absent.
The dedicated pinned native program comparisons above did run independently.
Raw full-suite receipt: repository `temp/atlas-insertion-full-suite-receipt`.

The ad hoc measurement wrapper failed **after** the passing test result because
it attempted to serialize the skipped tests as Python objects. Literal output:

```text
Ran 1229 tests in 675.745s
OK (skipped=3)
TypeError: Object of type CompilerBackendTests is not JSON serializable
when serializing dict item 'skipped'
```

The audited recovery receipt is PyTeXML
`temp/behavioral-atlas/20261029-insertion-full-suite.json`. It records the raw-log
hash, parsed test result/skips and wall time; **full-suite CPU and peak RSS are
unavailable**, not zero or inferred. The outer invocation remains failed after
tests. Per-specimen native/Python measurements below are unaffected. Source
identity was checked again after the suite and matches final native qualification.
No second full-suite run was needed to establish an unchanged test result.

Final engine/validation source fingerprint:
`a8b8d3fa074714035cee2ab2ea7cefdc0e5cde3d0caaa60841f23f79b31a2bcf`.

| Fresh Python specimen | Outcome | Wall seconds | CPU seconds | Peak RSS MiB |
| --- | --- | ---: | ---: | ---: |
| P02 insertion contract | Match, nine observations | 0.840 | 0.609 | 37.26 |
| P03 empty tail | Match, two observations | 0.713 | 0.516 | 36.96 |
| P03 | Definition match; invocation blocked | 0.726 | 0.422 | 37.13 |
| P03 insertion contrast | Match, three observations | 0.437 | 0.375 | 37.30 |
| M02 | Match, eight observations | 0.547 | 0.391 | 37.60 |

All nine numbered P02 cases have separate worker receipts as well (0.342–0.941 s
wall, 0.281–0.453 s CPU, 36.96–37.30 MiB peak RSS). These are fresh-process peaks
including imports; case timers start after runner imports. Orchestration reports
39.995 s wall, 2.953 s CPU and 45,391,872 bytes peak RSS, excluding child CPU/memory.
The 28 native processes total 5.030 s wall and 3.125 s CPU; their largest individual
peak is 30,830,592 bytes. Do not sum peaks or compare these unequal scopes as
engine throughput. The competing Bayesian/Monte Carlo workloads remain recorded.

## 2026-10-29: pinned P03/M02 program comparisons

The [atlas comparison instrument](behavioral-atlas.md#pinned-native-program-comparisons)
now executes exact definition fragments plus explicit probes in the pinned
pdfTeX/LaTeX format and in PyTeXML's shared engine. Six fresh native processes
capture and replay **20 observations** across P03, M02 and a minimal insertion
contrast. Three native `ifx` checks independently qualify their reconstructed
typed target references. Source, probe, binary/format and recorded-input hashes
are retained in the tracked reference fixture; they are test data, not bindings.

**M02 matches:** all eight observations and the protocol's typed definition.
Ordinary selectors, literal parameter markers and protected/long flags reconstruct;
the generated-name body correctly fails equality; the scratch definition restores.
**P03 remains blocked:** native branches distinguish defined/undefined/relax
operands and observe local helper redefinition/restoration without changing the
generated macro. Python fails during generation, before installing `mytest:NF`.
Its target and branch observations are missing, not mismatches or passes.

The minimal contrast isolates the first shared mechanism gap:
`\edef\AtlasInserted{\unexpanded{#1}}` is native-equal to the authored `##1`
replacement, whereas Python rejects it with
`invalid_definition_parameter: Replacement text requires a declared parameter or doubled marker`.
The authored control installs in Python. The expanded-definition consumer currently
revalidates inserted tokens as fresh parameter syntax. Its insertion contract,
including the P02 barrier/token-register cases, is the next engine investigation;
later P03 gaps remain unknown until that gate passes. No engine runtime changed.

The runner reads physical fragments lazily and uses a strict diagnostic adapter
over the shared expansion/setup evaluator. It neither imports expected meanings
nor qualifies normal preparation integration, complete original documents,
current-release expl3 bootstrap, general rescanning or automatic staged replay.
Initial runner failures are retained in `20261029-native-initial` and
`20261029-native-second`: freezing physical source in program mode, rejecting
blank-line paragraph events and rejecting `SourceEnd` were harness defects.
Only the corrected run supplies final qualification.

Verification passes **six native-reference/comparison tests, six catalog integrity
tests and four existing bounded atlas checks**. The tests reject source identity
drift, missing observations, incomplete execution, changed typed meanings and
failed native equality even with matching displays. P03's blocked status is not
an expected-failure test counted as passing engine behavior.

The final native/Python receipt is PyTeXML
`temp/behavioral-atlas/20261029-native-qualified/summary.json`; the outer receipt
is repository `temp/atlas-native-qualified-receipt`. The test receipt is
`temp/atlas-native-tests-receipt`, with atlas check details in PyTeXML
`temp/behavioral-atlas/20261029-with-native-checks.json`. Final engine/validation
source fingerprint: `15b3e39a9830bcc30fa9e229a27223e9b1e25eb4b0e0d1e9d023260f1654c4f3`.

| Fresh Python specimen | Outcome | Wall seconds | CPU seconds | Peak RSS MiB |
| --- | --- | ---: | ---: | ---: |
| P03 | Blocked in definitions | 0.481 | 0.375 | 37.18 |
| P03 insertion contrast | Blocked in definitions | 0.463 | 0.313 | 36.52 |
| M02 | Native match | 0.458 | 0.359 | 37.46 |

Case timers start after runner imports; peak memory includes imports and is a
process high-water, not retained engine-object memory. The orchestrator records
8.746 s wall, 1.484 s CPU and 44,183,552 bytes peak RSS; its CPU/memory exclude
children. Six native process receipts total 1.038 s wall and 0.594 s CPU, with
individual peaks about 29.1–29.2 MiB. These scopes differ and are not an engine
speed comparison. Concurrent Bayesian/Monte Carlo workloads remain recorded;
no regression or throughput improvement is inferred.

## 2026-10-29: behavioral atlas from existing LaTeXML fixtures

The [behavioral atlas](behavioral-atlas.md) adds nine cases across spacing,
meaning reconstruction and generated parameters, with 17 source-file hashes,
21 exact byte ranges, prerequisites, observation authority and staged-resolution
experiments. Existing sources and XML targets are preserved in place. The
catalog/receipt checker verifies identity, locations and supporting test methods;
it does not install meanings or import LaTeXML output as engine behavior.

Four new bounded checks pass: physical trailing spaces/tabs with exact source
excerpts; manual checkpoint rereading after a category refinement; a source-derived
generated name whose display reconstruction changes token identity; and an
upstream expansion fragment that constructs an identity macro's parameter from
separate tokens. Six integrity tests reject source/fragment drift, missing test
references, duplicate/unlocated cases and unsupported qualification, and preserve
the mixed-newline helper bytes. No engine runtime changed, no complete original
document was run, and no new native comparison was acquired. Manual reader replay
does not establish the proposed general staged resolver.

The first failed receipt is retained separately from qualification: test-authoring
errors concerned endlinechar setup, a span field, and a tab already skipped after
a space. Correcting the harness required no production-engine fix. Raw failures
remain in repository `temp/behavioral-atlas-initial-receipt` and the atlas's
`20261029-initial.json`; they are not counted as engine gaps.

The qualified atlas receipt is PyTeXML
`temp/behavioral-atlas/20261029-qualified.json`; the outer receipt, including the
six integrity tests, is repository `temp/behavioral-atlas-qualified-receipt`.
The atlas verification/exercise process records **1.933 s wall, 1.438 s CPU and
39,817,216 bytes peak RSS (37.97 MiB)**. Per-check wall/CPU and cumulative process
high-water values are recorded separately; these do not establish per-check
allocations or a controlled performance baseline under the user's competing
Monte Carlo workloads. All ten checks pass. The reduced expl3 conditional
generator and meaning/scantokens reconstruction protocol remain source-backed
research entries awaiting complete prerequisite and invocation witnesses.

## 2026-10-29: display triage and census comparison of source-derived state

The [qualification follow-up](meaning-qualification.md) owns details and commands.
Native diagnostic support now prints the reconstructed candidate separately from
comparing it with the original target. All **533 display-difference records** were
checked in both regimes: **1,066 Python/native candidate displays agree**, and
all 1,066 candidates remain native-unequal to the target. The first-regime diffs
remove spaces in 367 records, add them in 146, and do both in 20. No formatter
defect was found in this group; no engine display behavior changed.

A reusable checksum/basis-checked comparator now reports semantic hashes and
typed descriptors for source-derived final bindings. The kernel-source witness
creates 54 new/changed bindings: **41 qualified macro references match**, with
five reconstruction exceptions and eight non-macro meanings reported as lacking
a qualified reference. No missing/uncertain/uncomparable item is counted as a
match. Its progress fraction is 41/15,552 qualified macros, with explicit family
and state boundaries; this is not whole-format completion or behavior coverage.

Qualification passes **58 meaning tests plus four kernel-source tests**. The
native triage run `20261029-display-triage-qualified` and the fresh source-state
comparison receipt are identified by repository
`temp/meaning-followup-qualified-receipt`. No runtime engine source changed and
no new all-nine extraction equivalence is claimed.

Planning now requires representation compaction before broad source bootstrap
and a qualified derived-state snapshot before collection-scale bootstrap runs.
The 214.43-byte/token figure is an amortized object-graph ratio; the 16-second
traced pass includes scanning/allocation. 15,552 names have 11,401 distinct macro
descriptors. The named primitive-alias layer includes 442 undefined entries, and
`exp_args:Nc` is a macro. These facts constrain the interpretation of cost and
coverage without changing the raw assay. Workload-selected Q4 family gates remain;
static exception frontiers inform their investigation rather than defining it.
The user's subsequent clarification makes the wider exception corpus an input
to mechanism discovery and anticipatory testing, including cases outside current
workload demand. Group patterns, identify failing assumptions and qualify general
rules; do not turn exception names into individual engine additions. The
qualification note records this purpose separately from completed measurements.

## 2026-10-29: qualify the assay as an oracle for source-derived meanings

The user clarified that engine work must derive meanings through reusable
language mechanisms, not hardcode the entire kernel vocabulary. The
[assay recipe](meaning-assay.md#qualification-the-engine-derives-meanings-from-source)
now separates reconstruction evidence from source execution, semantic coverage
and workload cost. Its 15,552 generated fixtures are reference/regression data;
the 1,994 reconstruction exceptions are not 1,994 implementation requirements.
The 69.76 MiB measurement materializes the accepted corpus and is not a required
production footprint. Static fan-in alone does not select intrinsics.

The existing kernel-source fixture is the concrete qualifying pattern: upstream
definitions construct ordinary public/hidden meanings; real etoolbox definitions
then patch them. The current rerun passes all **three tests**, including all 19
pinned native observations and direct optional-wrapper behavior. Output is
retained under repository `temp/meaning-assay-source-qualification-receipt`.
This rerun checks the existing bounded capability, not full startup or normal
preparation integration. No engine code or native assay artifact changed.

The current plan now prioritizes source families and the shared primitives/state
operations they require across the workloads. A derived-state cache is optional
after source execution is qualified; the engine must still handle new computed
names and declarations. Existing Python declarator adaptations remain implemented
behavior, while source-bootstrap integration and any later intrinsic replacement
need their own witnesses. The newest L14 entry and semantic-engine contract
supersede earlier production-table/adapt-every-routine wording. Historical
checkpoints below retain their original evidence and then-current plans.

## 2026-10-29: frontloaded native knowledge assay and generated fixture corpus

The user's assay is now executable ahead of Q4 implementation. See the
[meaning-assay recipe](meaning-assay.md) for the method, complete category
tables, exception classes, costs and reproduction commands. It uses the pinned
LuaLaTeX hash inventory, source vocabulary and iterative pdfTeX reference
discovery. Native `ifx` qualifies reconstructed macros; printed equality alone
does not. The native formats agree on LaTeX2e 2026-06-01 and expl3 2026-09-09.

The final run inventories **23,160 candidates**, including **20,239 observed
pdfTeX-defined names** and **17,546 macros**. Lua contributes 23,039 hash entries,
including 1,549 undefined entries and one unavailable empty-name token. There
are **40 target-defined names absent from Lua's hash**, so a Lua census alone is
not target-complete. Cross-engine displays agree for 19,990 compared names and
differ for 2,697; neither count proves cross-engine token equality.

**15,481 first-regime and 71 alternate-regime reconstructions pass native `ifx`.**
The remaining 1,994 macros and 352 names outside the probe's byte-name domain
are individually recorded exceptions. A native error does not terminate the
whole census: the rejected record is isolated and subsequent candidates resume.
The four native error logs and their parameter-token limitation are documented
in the recipe. Non-macro meanings are inventoried without claiming register
initialization or primitive behavior has been reconstructed.

The graph has 51,702 static control-sequence references and four active-character
edges, with 2,270 possible computed-name users. It records body references and
fan-in, not execution counts or complete intrinsic eligibility sets. A frozen
1,416,829-byte gzip corpus supplies **15,552 generated fixtures** to the ordinary
test tree, with semantic descriptors, hashes and basis/probe provenance.

The accepted PyTeXML object representation retains **73,143,908 bytes (69.76
MiB)** for 301,919 body tokens plus 39,187 parameter tokens. The assay takes
38.043 seconds wall, 30.703 seconds Python CPU and 5.328 seconds native CPU;
Python peak resident memory is 266.57 MiB, and the largest native peak is 111.05
MiB. The traced construction pass, measurement scopes and the user's concurrent
Bayesian/Monte Carlo workloads are explicit. This is not a performance baseline,
runtime installation measurement or package-cost allocation.

Qualification: **56 focused tests pass**, including replay of every generated
entry and the existing meaning assignment/comparison tests. Native run evidence
is retained under PyTeXML's `temp/meaning-assays/20261029-final`; outer receipts
are under repository `temp/meaning-assay-final-receipt` and
`temp/meaning-assay-fixture-receipt`. Earlier failed attempts remain evidence and
do not qualify the frozen snapshot. The snapshot is code-fingerprinted from the
working tree based on `3e6ae49` before this change's commit.

Implemented: acquisition assay, bounded candidate validation, graph, reporting
and fixture replay. Still proposed: a generic lossless serializer, complete
target-only coverage, non-macro state installation, production tables, interned
identities, dependency guards and intrinsics. No preparation behavior changed;
the all-nine document status is not requalified by this assay. Q2 remains the
next engine increment; Q4 now starts from measured acquisition evidence.

## 2026-10-29: Q4 acquisition proposal and meaning-identity counterexamples

Q4 now proposes offline extraction through the pinned native engine/format,
with typed data installed during preparation. This avoids requiring PyTeXML to
execute expl3 in order to obtain the meanings needed to execute expl3. The
[semantic-engine contract](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-language-core/pytexml-semantic-engine.md#61-bootstrap-contract-and-lexical-evidence)
and [L14](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-language-core/decisions/L14-kernel-bootstrap.md)
specify inventory, complete basis/environment identity, native reconstruction
checks and dependency-aware intrinsic eligibility. Q2 remains the next increment.

The [meaning-comparison witness](../tests/fixtures/engine/meaning-comparison.tex)
adds three observations to the existing independent fixture:

- Macros containing `!` with catcodes 12 and 11 have different native meanings
  (`ifx` false), but their `meaning` texts are equal. Printing a retokenized body
  back cannot establish catcode fidelity; native candidate reconstruction and
  `ifx` equality are the proposed stronger gate.
- A caller and its saved alias remain `ifx` equal after a helper is redefined.
- Their caller's expansion before/after the helper change differs. An unchanged
  caller stamp cannot justify an intrinsic that assumes the old helper behavior.

The native pdfTeX 1.40.29 / LaTeX2e 2026-06-01 / expl3 2026-09-09 run matches
all **35 expected observations**. The compiler and format SHA-256 values were
checked against the existing oracle pin. The Python meaning-comparison suite
passes **34 tests**, including the extended fixture. Receipts are retained under
repository `temp/q4-meaning-gates/`. No engine code changed; these are validation
witnesses and a revised plan. The extractor, full l3 inventory/table, native
candidate serializer/validator, stamps and intrinsic eligibility mechanism remain
unimplemented. The small witnesses do not establish extraction completeness,
table installation cost or native equivalence of future intrinsics.

## 2026-10-29: CPU and memory footprints with workload context

Specimen receipts now use `pytexml-specimen-performance/2`: elapsed preparation
time, worker CPU time (including a user/system split), peak resident memory,
measurement scopes/methods and explicit absent readings. Host description,
logical CPU count, workload note and instrumentation mode travel with each result
and its comparison receipt. Historical receipts are not rewritten or backfilled.
The ordinary mode adds only process counters to the existing memory receipt.
See [specimen iterations](specimen-iterations.md) for the CLI and metric contracts.

Optional `--profile-cpu` records main-thread function costs and call counts, with
a readable report, complete JSON rows and a raw caller graph. It uses thread CPU
time rather than elapsed time, excludes other threads/child processes, and has
explicit instrumentation overhead. Worker totals still cover all its threads.
Profile export occurs after the total/peak readings. Both normal success and
normal failure publish receipts; interrupted workers retain unavailable metrics.
Neither shared engine functions nor whole-process peaks establish a particular
TeX package's cost. Package-level attribution, Python allocation tracing,
process-tree memory/CPU and performance budgets remain unimplemented.

The user reported two concurrent heavy Bayesian regression/Monte Carlo sessions
straining the laptop. New measurements carry that note. The earlier Q1 wall-time
comparisons below are uncontrolled observations and cannot attribute a regression
to checkpoint changes. CPU time is more useful under scheduling contention, but
can still change with CPU frequency, cache/memory contention and paging. No
speedup, slowdown or throughput parity is qualified by this checkpoint.

Verification: **16 specimen-harness tests pass**, covering real preparation,
failed-worker counters/profile export, missing timeout counters, profile files,
workload/history propagation and unmodified historical receipts. The all-nine
batch `20261029-resource-footprints` records both CPU and resident peaks for every
specimen. Source fingerprints, emitted master hashes and preparation summaries
match `20261029-q1-checkpoints-qualified`; all nine remain partial. This is
reporting qualification, with no new native-render or recovery-equivalence claim.

| Specimen | Wall seconds | Worker CPU seconds | Peak resident MiB |
| --- | ---: | ---: | ---: |
| 2306.01911v1 | 30.411 | 17.844 | 163.40 |
| 2405.15943v3 | 16.969 | 9.469 | 115.97 |
| 2412.11340v4 | 22.175 | 6.766 | 76.63 |
| 2512.18792v1 | 97.218 | 50.109 | 588.11 |
| 2608.28281v2 | 28.361 | 13.922 | 128.59 |
| Root A | 4.005 | 1.531 | 71.53 |
| Root B | 4.187 | 1.734 | 71.52 |
| Root C | 4.157 | 1.781 | 71.70 |
| Root D | 4.340 | 1.750 | 72.65 |

The separate `20261029-root-a-cpu-profile` run preserves Root A's master and
summary. Its instrumented receipt records 19.895 elapsed seconds, 10.516 worker
CPU seconds and 76.57 MiB peak resident memory. The main-thread profile records
224,663 calls each to the character-rule `fullmatch` and `_bounds` helpers; these
are concrete investigation candidates, not a demonstrated optimization or a
package-cost allocation. The large instrumentation overhead reinforces keeping
these diagnostic runs separate from ordinary counter-only measurements. Small
or zero function times can reflect clock granularity rather than free work.
Full test/batch output is retained under repository
`temp/footprint-reporting/qualification/`; the normal and profiled batches live
in the existing specimen run collection.

## 2026-10-29: Q1 shared checkpoints and early Q6 measurement

The first Q1 gate is now consolidated around `engine.checkpoints.Checkpoint`
and preparation's `RecoveryCoordinator`. Command dispatch, bounded token
programs, input retention and materialization requests share rollback ordering.
The opening token is captured before expansion; direct readers retain their
operand-cursor contract. Preparation keeps the checkpoint open through owner
acceptance, covering language state, pending work, options/loads, file events,
resource records and staged output. Failed-attempt facts are committed after
rollback and survive enclosing retention. Repeated recovery of one request is
idempotent. Resume needs an established continuation; otherwise the containing
source is retained. See [resource recovery](resource-recovery.md).

The strengthened gate covers partial mutations before failure, expansion-created
meanings, earlier completed effects, pending packages/actions, nested rollback,
assumption propagation, retained replay boundaries and file-hook observations.
A failed asset conversion removes its partial staged file while a later asset
can succeed. Bibliography requests use the same protocol without rewinding the
completed language pass. Arbitrary implementation/publication errors still
propagate. The general segment outcome/retry API remains planned work.

Q6's timing receipt was brought forward at the user's request. All subsequent
specimen batches record preparation wall time and worker peak resident memory,
with platform/method/scope and explicit unavailable measurements. A real failed
worker is tested; timeouts do not fabricate a zero peak. The batch table, per-run
receipt and comparisons expose the evidence. See [specimen iterations](specimen-iterations.md).

The measurements exposed excessive checkpoint copying. The first consolidated
all-nine run (`20261029-q1-checkpoints-profile`) took 404 seconds in its outer
receipt; copying immutable output containers reduced the next run to 206 seconds.
Completed manifest fact rows are now treated as append-only during reading, with
container snapshots; mutable summaries remain independently copied. Later
projection occurs outside that reading checkpoint. These ownership rules must
be preserved when introducing new mutations. The initial timing run overlapped
focused tests briefly; these are observed runs, not a controlled speedup claim.

The final full suite ran **1,191 tests: 1,188 passed and three skipped**, in
311.931 seconds. The preceding Q1 suite ran in 210.319 seconds; the broader
checkpoint coverage still has observable cost. Keep timing receipts at every
increment and investigate regressions before compounding them with new package
execution. The focused recovery gate passes all 29 tests; a preceding 194-test
check also covered reader contracts, definitions, conditions, hooks and timing.

Earlier failing runs are retained under repository `temp/q1-checkpoints/`,
including the corrected cursor/retention regressions and the initial invocation
of unavailable pytest. The repository's unittest discovery is the full-suite
driver; focused modules that import `reader_support` also need the tests directory
on their import path. `qualification-final` owns the final sequential suite,
specimen and copied-payload reread output.

The final batch `20261029-q1-checkpoints-qualified` uses the same explicit native
resource root as the earlier Q1 comparison. All nine payloads remain partial.
Their master lengths, SVG counts and bibliography entry counts match that
checkpoint. 2405's binding requirements rise from 8 to 20: retaining an unfinished
package input now also rolls back its `natbib` activation, so twelve later
citations no longer inherit that speculative fact. Root A gains two typed
preparation requirements for retained commands, without changing its four legacy
unresolved diagnostics or 754-character master. These are consequence accounting
changes, not new closure or native-render claims.

| Specimen | Preparation wall seconds | Peak worker MiB |
| --- | ---: | ---: |
| 2306.01911v1 | 29.480 | 163.07 |
| 2405.15943v3 | 21.875 | 117.13 |
| 2412.11340v4 | 11.500 | 76.62 |
| 2512.18792v1 | 66.882 | 588.68 |
| 2608.28281v2 | 22.611 | 127.67 |
| Root A | 6.383 | 72.04 |
| Root B | 6.110 | 72.14 |
| Root C | 6.893 | 72.63 |
| Root D | 8.160 | 71.53 |

All nine memory readings were measured on Windows using the worker's peak working
set. Batch start-to-finish was 192.122 seconds, including parent bookkeeping;
the preceding Q1 outer receipt was 64.980 seconds. The initial consolidated
2306 request took 201.519 seconds; the final one takes 29.480. Run conditions were
not controlled enough to claim a general speedup or throughput parity. Repeated
matched measurements and profiling remain required before expanding package
execution. The receipts expose that issue instead of hiding it behind successful
extraction.

All nine final `master.tex` hashes match the preceding Q1 checkpoint exactly.
All nine copied-payload rereads also finish partial, with measured time and peak
memory, under the identical code fingerprint
`d6a298c9216c87491246d79c9be33ffbec27a91431caaf471c6b46e012f00a84`.
The rereads still do not import recovery-state/item lineage from the prior
manifest: 2306/BFPCA expose later package failures and 2512 gains an unresolved
reading boundary. Marker survival therefore remains distinct from replay
equivalence. Receipts and isolated copied sources are under repository
`temp/q1-checkpoints/payload-rereads/`. No new native render equivalence is claimed.

## 2026-10-29: Q1 resource failures and continued recovery

The first Q1 gate is implemented in the existing preparation traversal, request
records and source maps. `recovery="best_effort"` is the API/CLI default; diagnosed
resource failures retain item identity, outcome, cause, partial knowledge,
affected domains and disposition. Active failures produce correlated text markers
and journal events. Projection happens after splice rollback, including retained
package/input files. Independent readable requests continue. No file is fabricated
at an absent resource's name. See [resource recovery](resource-recovery.md) for the
implemented contract and acceptance/status fields.

Unavailable programs invalidate captured meanings and state evidence. Subsequent
reading carries explicit caller-state recovery contexts. Uncertain load guards
remain possible loads; they are not promoted to active missing items. Access,
decoding, ambiguity, an unspecified search environment and unevaluated names stay
distinct from confirmed absence. Undecodable child bytes survive under an opaque
artifact identity. Authored file-test fallbacks execute before generated recovery.
`recovery="strict"` rejects after discovery, survey and materialization attempts,
preserving an earlier published payload and the new attempt's diagnostics.

The all-nine batch `20261029-q1-resource-recovery-qualified` uses the preceding
`20261029-python-format-files-final` checkpoint's explicit native resource root.
Its resource inventory fingerprint matches that checkpoint for every specimen.
All nine attempts publish partial payloads:

| Specimen | Master characters | Unresolved diagnostics | Newly visible recovery |
| --- | ---: | ---: | --- |
| 2306.01911v1 | 105923 | 0 | `eso-pic` absent; bibliography entry reading conditional on recovery state |
| 2405.15943v3 | 67710 | 1 | Existing reading boundary; no resource tombstone |
| 2412.11340v4 | 117103 | 1 | `setspace` absent; later declaration reading remains unresolved |
| 2512.18792v1 | 169440 | 0 | `eso-pic` absent, marker in retained source |
| 2608.28281v2 | 69902 | 3 | Existing reading boundaries; no resource tombstone |
| Root A | 754 | 4 | Existing continuation boundaries; no resource tombstone |
| Root B | 1081 | 1 | `biblatex` absent |
| Root C | 1931 | 1 | `cite` absent |
| Root D | 1866 | 2 | Existing reading boundary; no resource tombstone |

These are not coverage gains. Earlier preparation left unknown external packages
as binding requirements without checking the resource obligation. The explicit
resource tree really lacks these names. BFPCA therefore changes from `complete`
to `partial`; its original root text is retained, while the earlier 24 asset
derivatives and formatted bibliography are no longer claimed as established
extraction. The missing `eso-pic` also leaves 2306's bibliography entry grammar
conditional: unrecognized entries are reported unresolved, not absent. Counts in
the legacy `unresolved` list do not include all typed requirements or tombstones.
Root A's D5 absence remains an authored false branch; computed `gmlisting`
closure and paired native rendering remain Q2 work.

All nine copied-payload rereads finish with `partial` status. They do not qualify
replay equivalence: 2306's unresolved count changes from zero to one and exposes
`lipsum`; BFPCA exposes `bbm`; 2512's unresolved count changes from zero to one.
The marker text survives, but a fresh preparation does not import the earlier
manifest's state consequences. Keeping the old marker is not equivalent to
replaying its assumptions. The other six rows retain their prior unresolved
counts, including Root A at four. This evidence makes recovery-state import an
explicit follow-on rather than allowing an idempotent-payload claim.

The full suite ran 1,183 tests: 1,180 passed and three skipped. The final correction
for unreadable conditional package retention additionally passes all 23 focused
recovery tests. Those tests include five independent missing requests in one run,
authored fallback, content on both sides, state invalidation, rollback, strict
rejection after discovery, corrupt/denied sources, conversion failure with later
successful assets, and propagation of implementation/publication errors.

This closes Q1's scanned-request recovery gate, not the whole staged-pipeline
proposal. Arbitrary malformed-source resynchronization, complete discovery through
opaque/computed source, a universal open-item taxonomy, and importing recovery
state from an earlier prepared payload remain unimplemented. Text markers are a
recovery projection, not proof of native rendering or original-resource closure.

Receipts are under repository `temp/q1-recovery/`: `suite-final`, `focused-final`,
`specimens-qualified`, `reread-run` and `payload-rereads/receipt.json`. Earlier
failing runs remain diagnostic history. The first all-nine run used an unspecified
external search and is not the matched-environment comparison above.

## 2026-10-29: review reconciliation and recovery direction (planning only)

The user clarified the product contract: recover useful content from broken
LaTeX by default, including severe source failures. Strict rejection is
user-selected. An active missing asset produces a typed error tombstone at its
expected output position and a correlated log record; surrounding extraction
continues. Author-provided fallbacks execute through the engine and take
precedence over generated recovery. A failure must not suppress discovery of
independent failures. Scope consequences and preserve assumptions where recovery
continues without complete language-state knowledge.

The [staged pipeline §6.1](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-language-core/pytexml-staged-resolution-pipeline.md#61-failure-consequences-continued-discovery-and-recovery-policy)
owns that contract. The [working queue](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-language-core/working-queue.md)
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
