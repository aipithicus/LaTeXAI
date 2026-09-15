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
| LaTeXAI | `scripts/gauntlet-run.ps1`, `scripts/gauntlet-worker.ps1` | Declare the acquisition condition; publish a worker record with direct native outcomes, measurements and hashed artifacts. |
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

The first migration checkpoint covers schema-validated record ownership and
today's single-condition acquisition. A completed conversion is not a parity
qualification: acquisition records have `not-requested` qualification until an
actual comparison is requested and executed. Off/on orchestration, worker-side
pair comparison, historical analysis-only attempts, selective reuse and the live
deliberate-failure experiment remain subsequent checkpoints.

The generic envelope and batch schemas belong to CDXSCI's `inventory-records`
module. LaTeXAI owns the `latexai/paper-experiment/1` payload schema. Both have
serialized examples and validate at publication and consumption boundaries.

LaTeXAI's [payload schema](../../scripts/schemas/paper-experiment.schema.json) and
[example](../../scripts/schemas/examples/paper-experiment.json) accompany the
shared module's `inventory-records.schema.json` and three envelope examples.
The experiment pins assignments, declared source-tree fingerprints, worker
parameters, the worker and record-module bytes, schema and execution policy.
It does not yet snapshot the full engine/runtime or independently recompute the
deposit's tree fingerprint. That broader experiment freeze belongs with the
off/on worker checkpoint. `measurement` identifies the worker implementation
that obtained the condition's counts and details.

Both record readers check worker/artifact hashes, assignments, coverage, totals
and executor agreement. The PowerShell boundary applies the envelope schema;
LaTeXAI consumers also validate their payload, while the Perl comparator checks
the fields it consumes. Historical readers require explicit format selection.
