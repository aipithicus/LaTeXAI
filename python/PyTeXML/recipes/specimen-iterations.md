# Specimen iteration workflow

The development harness in `src.validation.specimens` calls the public preparation
and optional rendering entry points. It owns experiment organization only; it adds
no discovery, binding or emission rules to preparation.

Keep source projects in one catalog directory, and a separate run collection beside
it. The catalog uses explicit main documents so changes in discovery heuristics do
not silently change which manuscript is tested:

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

Use repeatable `--specimen <id>` options for a subset. Always use a new batch name;
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
are observations, not automatic improvements. The bibliography count is a lexical
inspection metric; the preparation manifest owns actual bibliography semantics.

Receipts record the Git commit, current Python/YAML code fingerprint, source-file
hashes, Python and dependency versions, and output hashes. A dirty code fingerprint
identifies the run but is not a restorable source-code snapshot: commit meaningful
code iterations separately. Fingerprinting is an intentional additional read at
the validation checkpoint; it is not part of preparation's single-read cache.
Do not modify source or runtime code while a batch is running.

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
python -B -m src.validation.specimens --runs <run-collection> render --batch 20261023-baseline --specimen paper-v1 --name system-fonts --tectonic <executable> --font-dir <font-directory>
```

The renderer checks that source and prepared fingerprints still match the batch.
It requires a new rendering name and follows the standalone adapter's compiler,
timeout, bundle and optional-download controls. It does not rerun preparation.
Results are linked into the batch page; temporary rendering inputs are removed by
the adapter. The manuscript's original render is not duplicated until rendering
is explicitly requested for that checkpoint.

Rebuild generated navigation after adding rendering evidence or restoring receipts:

```text
python -B -m src.validation.specimens --runs <run-collection> index
```

Earlier ad hoc runs remain historical evidence at their existing locations. Link
them from the local specimen README without changing their original receipts or
claiming they were produced by this harness.
