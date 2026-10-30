# Specimen iteration workflow

The development harness in `src.validation.specimens` calls the public preparation
and optional rendering entry points. It owns experiment organization only; it adds
no discovery, binding or emission rules to preparation.

File tests use the same explicit resource environment as the preparation API.
Pass repeatable `--tex-resource-root <directory>` arguments to `run` for ordered
recursive external roots, or `--project-only-resources` for a deliberately closed
project-only environment. The API spelling is `tex_resource_roots=(...)`.
Omitting the setting leaves external absence unestablished; project hits still
resolve. Preparation never guesses a TeX installation from PATH or launches a
compiler for lookup. The manifest records the roots, filename-inventory hash and
whether the search is closed. The native oracle must use a matching resource
environment when qualifying branch-dependent output.

`IfFileExists` resolves literal filenames through project paths, a literal
`input@path`, then the configured external roots. It records branch selection,
executes the selected branch through the existing dispatcher, retains the TeX
test in output, and packages project files whose presence is tested, including
binary files. Definite missing `InputIfFileExists` requests also select their
else branch. Finding an external input does not by itself establish support for
executing that file. Computed filenames, conflicting matches, substitutions and
nonliteral search-path state need additional language/environment work.

Keep source projects in one catalog directory, and the run collection outside it.
This project's catalog is `tests/fixtures/specimens/catalog.yaml`, and its runs go
in the gitignored `temp/specimen-runs/`. The catalog uses explicit main documents so
changes in discovery heuristics do not silently change which manuscript is tested:

```yaml
schema: pytexml-specimens/1
specimens:
  paper-v1:
    title: A descriptive paper title
    source: paper-v1-tex
    main: main.tex
```

The source path is relative to the catalog, and the main path is relative to that
source. Identifiers become directory names. Source projects are not copied into
runs. Existing `extracted/` trees are excluded using the preparation source-store
inventory rules; historical output can stay in place.

From the PyTeXML project directory, create one named batch for all catalog entries:

```text
python -B -m src.validation.specimens --runs <run-collection> run --catalog <catalog.yaml> --name 20261023-baseline --note "Baseline before extending local-style reading"
```

Use repeatable `--specimen <id>` options for a subset. Select the environment with
`--engine-profile etex|pdftex` (default `etex`). Always use a new batch name;
existing batches cannot be overwritten. Each paper gets a bounded preparation
process (180 seconds by default, configurable with `--timeout`). A failure or
timeout is recorded without preventing attempts on the other selected papers.
The command exits unsuccessfully if any paper fails or times out; partial masters
remain successful preparation attempts with outstanding requirements.

```text
run-collection/
  INDEX.md
  resources/                    # shared generated resource bytes
  20261023-baseline/
    README.md                   # linked results and optional rendering evidence
    NOTES.md                    # human/agent investigation notes; never regenerated
    run.json                    # code, catalog, source identities and outcomes
    paper-v1/
      result.json
      console.log
      prepared/                 # master, manifest, provenance and required resources
      changes.json              # on later attempts: file changes and metric summaries
      master.diff               # when both attempts have a master
      renders/<render-name>/    # only when explicitly requested
```

`INDEX.md` shows the latest attempt for each paper, including failures, and links
all batches. It does not copy or symlink a mutable `latest/` output directory.
Each batch compares with the preceding attempt for each selected paper, including
whether its source fingerprint changed. Fewer requirements or a shorter master
are observations, not automatic improvements. The bibliography count comes from
the preparation manifest's validated entry count; the harness does not reparse
entry syntax. Earlier receipts can retain the original lexical count metric.

Receipts record the Git commit, current Python/YAML code fingerprint, source-file
hashes, Python and dependency versions, and output hashes. A dirty code fingerprint
identifies the run but is not a restorable source-code snapshot: commit meaningful
code iterations separately. Fingerprinting is an intentional additional read at
the validation checkpoint; it is not part of preparation's single-read cache.
Do not modify source or runtime code while a batch is running.

Every new specimen result also carries `performance` (`pytexml-specimen-performance/1`).
`wall_seconds` measures the preparation subprocess from launch through exit or
timeout, using a monotonic clock. It excludes parent-side source fingerprinting,
output deduplication, comparison and index generation. `worker-performance.json`
preserves the worker's measurement; `result.json`, the batch receipt, the batch
table and subsequent change receipts expose the same evidence.

`peak_rss_bytes` is the preparation worker process's resident-memory high-water
mark, including native libraries in that process but excluding child processes.
Windows uses [GetProcessMemoryInfo's PeakWorkingSetSize](https://learn.microsoft.com/windows/win32/api/psapi/ns-psapi-process_memory_counters);
Linux/macOS use [getrusage(RUSAGE_SELF)](https://docs.python.org/3/library/resource.html#resource.getrusage),
normalizing platform units to bytes. The receipt records the platform and method.
A normal failed preparation still reports its peak. A forcibly killed worker,
launch failure, unsupported adapter or unavailable reading records `null` with
an explicit reason; missing evidence is never zero. Historical receipts remain
unmeasured. Cross-platform values are not interchangeable memory-accounting
contracts, and these are preparation measurements, not native-render timings.

Use these receipts at each checkpoint, including Q2–Q5. Compare code, source and
resource environment as well as time and memory. Record concurrent load or
profiling when relevant; one timing is an observation, not a performance gate.

Identical generated SVG, bibliography and local-style resources share a read-only
hard link to a content-addressed pool within the run collection. This keeps normal
filenames in each standalone prepared package without storing the same resource
bytes repeatedly. Original source files are never linked. The filesystem must
support hard links; an error is explicit, without a silent copying fallback.
Do not clear read-only flags and edit these resources in place: a hard link shares
its bytes with other iterations. Make a new preparation iteration instead.
Masters, manifests, provenance and logs are independent files. Named runs are
intentional retained checkpoints; there is no automatic pruning or pool garbage
collection yet. Removing a pool link does not invalidate links retained by a run.

To add independent rendering evidence to an existing prepared checkpoint:

```text
python -B -m src.validation.specimens --runs <run-collection> render --batch 20261023-baseline --specimen paper-v1 --name system-fonts --backend tectonic --compiler <executable> --font-dir <font-directory>
```

The renderer checks that source and prepared fingerprints still match the batch.
It requires a new rendering name and follows the standalone adapter's compiler,
timeout, bundle and optional-download controls, including its default Tectonic
cache in the repository's `temp/tectonic-cache`. It does not rerun preparation.

A batch records absolute source paths. If a source has moved since the batch ran,
add `--catalog <catalog.yaml>` to `render` or `qualify`: the specimen is then found
through the catalog, and used only if its main document and source fingerprint
still match the batch.
Results are linked into the batch page; temporary rendering inputs are removed by
the adapter. The manuscript's original render is not duplicated until rendering
is explicitly requested for that checkpoint.

To qualify relocation across an existing batch:

```text
python -B -m src.validation.specimens --runs <run-collection> qualify --batch 20261023-baseline --name relocation --backend tectonic --compiler <executable> --font-dir <font-directory>
```

Use repeatable `--specimen` options for a subset. Only prepared files are staged;
raw specimen paths are hidden from the compiler and never deleted or renamed.
The dependency receipt must resolve to staged files or temporary build products.
Engine bundle/cache resources and configured fonts remain allowed. The default
uses the existing compiler cache; `--allow-downloads` permits the optional renderer
to fetch missing engine resources without adding them to preparation or its payload.
`--format xdv` qualifies TeX compilation when PDF font embedding needs separate
attention. It does not certify PDF rendering or visual fidelity.

Add `--diagnose` to enable bounded diagnostic attempts after a failed render:
an XDV check when useful and an independently staged original-source comparison.
The configured timeout applies to each attempt. Existing prepared payloads remain
unchanged. New receipts carry structured check and diagnostic evidence; the batch
index derives classifications when regenerated, rather than storing a separate
editable verdict. See [qualification diagnostics](qualification-diagnostics.md)
for catalog ownership, wrapping rules, and the limits of each classification.

Per-paper evidence lands in `qualifications/<name>/`, with a combined receipt in
the batch's `qualifications/<name>.json`. Both successful and incomplete outcomes
remain visible. A partial preparation result can pass a particular rendered route;
an apparently complete preparation still needs independent qualification.

Rebuild generated navigation after adding rendering evidence or restoring receipts:

```text
python -B -m src.validation.specimens --runs <run-collection> index
```

Earlier ad hoc runs remain historical evidence at their existing locations. Link
them from the local specimen README without changing their original receipts or
claiming they were produced by this harness.
