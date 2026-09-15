# Gauntlet records

The inventory runner owns `experiment.json` and `batch.json`. Each paper worker
owns `jobs/<attempt>/run.json`. New acquisitions do not write `receipt.json` or
a batch-level `run.json`. Historical artifacts keep their original paths and bytes.

## Migration inventory

This inventory was checked against executable sources on 2026-09-15, before
implementation and checked again after migration. It covers the currently supported inventory contract.

| Owner | Producer or consumer | Migration |
| :--- | :--- | :--- |
| CDXSCI | `src/batch-adapters/public/Get-InventoryBatchJob.ps1`, inventory dependency helpers | Plan the worker record address and pass its immutable assignment. Keep the adapter free of execution and publication. |
| CDXSCI | `src/batch-runner.ps1` | Freeze the experiment before dispatch; validate and aggregate worker records into `batch.json`. |
| CDXSCI | `tests/batch-adapters/inventory-batch.Tests.ps1` | Migrate the generic external test worker and exercise the public runner boundary. |
| LaTeXAI | `scripts/gauntlet-run.ps1`, `gauntlet-worker.ps1`, `gauntlet-convert.ps1`, `gauntlet-measure.ps1`, `gauntlet-reuse.ps1`, `gauntlet-freeze.ps1` | Freeze inputs; execute or reuse conditions; measure and compare inside the paper job; publish native outcomes and hashed artifacts. |
| LaTeXAI | `scripts/gauntlet-select.ps1` | Select observed package routes from validated worker conditions; historical receipts require an explicit legacy option. |
| LaTeXAI | `tools/dev/capture-corpus-audit.pl`, `CaptureRuntime.pm`, audit tests | Read condition evidence from worker records. Preserve the qualified comparator and explicit historical-input support. |
| LaTeXAI | `tools/dev/fetch-ctan.pl --check` | Read missing-file observations from worker conditions; keep historical receipt reading explicit. |
| LaTeXAI | `scripts/xml-inspect.ps1`, `scripts/markdown-compare.ps1` | Read the selected condition through `gauntlet-records.ps1`; require explicit legacy input for retained receipt-backed studies. |
| Both | Runtime checks and public workflow/testing documentation | Name the new authoritative artifacts and legacy entry points. |

The private TeXdig gauntlet launcher currently calls the removed
`Get-GauntletBatchJob`, emits a different `gauntlet-receipt/0.1` contract and
implements its own aggregate. It is already incompatible with the current
inventory API. Restoring that integration is separate TeXdig work; this migration
does not claim a working non-LaTeXAI production consumer. The generic external
worker tests cover the shared envelope without LaTeXAI XML semantics.

Fixture-audit `run.json` files, test-batch records, procurement deposits and
archived receipts are separate contracts and are not renamed.

## Checkpoint scope

Single-condition acquisition has `not-requested` qualification. `-CaptureParity`
declares two fresh native conditions and one required off/on comparison inside
each paper worker. `-OnFirst` reverses execution order without reversing the
comparison roles. Conditions run sequentially; the default pool has ten paper
slots. The worker invokes the shared `CaptureCompare.pm` implementation through
`compare-paper.pl` in a fresh Perl process. The corpus auditor calls the same
implementation. Comparison needs direct condition evidence, not `batch.json`.

Each comparison reports `pass`, `fail` or `incomplete`. Both successful
conversions plus a completed comparison can produce execution `complete` with
qualification `fail`. A failed conversion, missing/malformed evidence, timeout,
incomplete cleanup or changed input produces an incomplete qualification. Every
declared condition and edge stays in the plan and worker record. The coordinator
accounts for absent/nonterminal worker records without completing them.
`-FailOnArticleFailure` also fails a requested qualification gate.

`-ReuseBatch <directory>` imports a frozen paired paper-record batch into a new
experiment. Each worker independently verifies eligible conditions and executes
the remainder. `-AnalysisOnly` requires that explicit input and prohibits engine
conversions: unusable conditions become rejected evidence and keep qualification
incomplete. Selection and conversion options default to the prior experiment;
explicit options replace those defaults. The prior batch need not qualify: a
successful condition in a failed paper can be reused independently.

Both modes rerun measurement and comparison. The conversion identity covers the
source/entrypoint, engine and resident-library trees, generated modules, Perl
runtime, native invocation/supervision implementation, native policy, preloads,
resolved options and effective environment. Inspection and comparator code have
separate identities. Copied raw XML/log/streams retain their bytes; the new
condition links to the original worker, experiment and conversion freeze.
Retained inputs and artifacts are checked before use and again before publication.

`conversion.action` is `executed`, `reused` or `rejected`. Summary counters expose
each disposition. `counts.latexmlMs` counts native time in this attempt only;
reused conditions retain the original observation in `conversion.nativeDurationMs`
and `conversion.origin`, including memory. Invocation and source paths continue
to describe the original conversion. Runtime comparison validates those original
addresses before comparing root roles and pinned conversion inputs. Raw XML,
capture ranges and original records are unchanged.

Receipt-backed legacy import into paper attempts, other condition contrasts and
the full-population refactored benchmark remain later checkpoints. The existing
explicit legacy corpus reader remains available for historical comparisons.

The generic envelope and batch schemas belong to CDXSCI's `inventory-records`
module. LaTeXAI owns the `latexai/paper-experiment/1` payload schema. Both have
serialized examples and validate at publication and consumption boundaries.

LaTeXAI's [payload schema](../../scripts/schemas/paper-experiment.schema.json) and
[acquisition example](../../scripts/schemas/examples/paper-experiment.json) and
[paired example](../../scripts/schemas/examples/paired-paper-experiment.json) and
[reuse example](../../scripts/schemas/examples/reused-paper-experiment.json) accompany the
shared module's `inventory-records.schema.json` and three envelope examples.
The experiment pins assignments, declared source-tree fingerprints, worker
parameters, the worker and record-module bytes, schema and execution policy.
For paired plans, `inputs/freeze.json` (`latexai/experiment-freeze/1`) additionally
pins copied engine `lib/`, `bin/`, `scripts/`, `tools/dev/` and `lib-ctan/` trees,
including generated modules and dirty/untracked input bytes. It copies the
Strawberry `perl/` and `c/bin/` runtime trees and each source tree. Tree identity
is SHA-256 over ordinally sorted relative paths, file lengths and hashes; the
copied source must match the deposited fingerprint. File manifests retain the
exact membership. `engine.patch`, Git identity and generated version are distinct
evidence. Copying and hashing time is recorded separately from the batch.

The PowerShell executable, shared orchestration files/trees and observed host
runtime are pinned at their configured locations. This is a local experiment
freeze, not an operating-system image. Workers rehash these pins and their own
source before conversion, after each condition and after comparison. Mutations
fail qualification. Relevant Perl/TeX, locale and BLAS overrides are cleared;
the effective runtime path and inherited values are retained. Output cwd is
isolated per condition. Extra arguments are standalone flags; file-taking and
capture options are experiment-owned, and preloads resolve by module name within
the copied trees. Shared code must remain fixed for the experiment duration.

The paired specification (`latexai/paired-plan/1`) pins this freeze, condition
order/arguments, required comparison edge, model, measurement implementation and
stage deadlines. `measurement` identifies `gauntlet-measure.ps1`, which obtains
counts/details from raw artifacts for acquisition, paired execution and replay.
Native phase parsing reads the retained stderr stream, including bytes beyond
the supervisor's bounded in-memory excerpt. Worker records retain
raw native streams, XML/log hashes, stripped/projected/normalized XML, comparison
requests/reports and comparator identities. Conversion, XML inspection,
comparison and input validation timings remain distinct. Native memory is the
sampled process `PeakWorkingSet64`; it is not aggregate host or process-tree RSS.

Both record readers check worker/artifact hashes, assignments, coverage, totals
and executor agreement. The PowerShell boundary applies the envelope schema;
LaTeXAI consumers also validate their payload, while the Perl comparator checks
the fields it consumes. Historical readers require explicit format selection.
