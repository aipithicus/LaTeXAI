# Development specimens

Start at the [iteration index](../../../temp/specimen-runs/INDEX.md) to inspect current results.
[catalog.yaml](catalog.yaml) declares each stable identifier, title, source directory
and explicit main document. New papers can be added as new catalog records.

| Specimen | Paper | Main source |
| --- | --- | --- |
| 2306.01911v1 | Generalized Bayesian MARS | [main.tex](2306.01911v1-tex/main.tex) |
| 2405.15943v3 | Transformers Represent Belief State Geometry | [fractals_in_residual_stream.tex](2405.15943v3-tex/fractals_in_residual_stream.tex) |
| 2412.11340v4 | Fast Bayesian Functional Principal Components Analysis | [Main.tex](2412.11340v4-tex/Main.tex) |
| 2512.18792v1 | The Dead Salmons of AI Interpretability | [00_main.tex](2512.18792v1-tex/00_main.tex) |
| 2608.28281v2 | LoopArena: Benchmarking Models as Runtime Controllers for Loop Engineering | [main.tex](2608.28281v2-tex/main.tex) |
| gauntlet-master-natbib | Synthetic gauntlet master, root A | [master.tex](gauntlet-master/master.tex) |
| gauntlet-master-biblatex | Synthetic gauntlet master, root B | [master-biblatex.tex](gauntlet-master/master-biblatex.tex) |
| gauntlet-master-plain | Synthetic gauntlet master, root C | [master-plain.tex](gauntlet-master/master-plain.tex) |
| gauntlet-master-arxiv | Synthetic gauntlet master, root D | [master-arxiv.tex](gauntlet-master/master-arxiv.tex) |

The four gauntlet-master entries share one source directory, so an edit anywhere in
it counts as a source change for all four. Its [README](gauntlet-master/README.md)
describes the roots, and its [coverage map](gauntlet-master/coverage.md) ties each
case to the gauntlet inventory.

LoopArena is a witness for recovering title, author/affiliation data, abstract and
metadata from a class-defined TikZ title card. Preparation must preserve the
declarations and stored abstract input needed for that later interpretation;
rendering the surrounding box is not the extraction goal.

Source directories are inputs. Do not run preparation into their `extracted/`
directories: named iteration outputs go in the gitignored `temp/specimen-runs/`
collection.
The fractal paper's existing `extracted/` is historical prototype evidence. It is
excluded from new source fingerprints and preparation discovery.

Each iteration has a purpose note, code/source fingerprints, one result per paper,
prepared packages, and links to changes from the preceding attempt for that paper.
Add observations to the iteration's `NOTES.md`; the generated index never rewrites
that file. A failed attempt stays visible, including when a previous attempt worked.
Rendering is opt-in and receives its own named evidence directory inside the batch.

See the [workflow recipe](../../../recipes/specimen-iterations.md) for commands and
the shared-resource/retention rules.

From the PyTeXML directory, the next batch can be created with:

```text
python -B -m src.validation.specimens --runs temp/specimen-runs run --catalog tests/fixtures/specimens/catalog.yaml --name <new-iteration-name> --note "What changed and what this run checks"
```

Add `--specimen 2405.15943v3` to run only that paper. Omit it to run the full catalog.

Until 2026-10-27 this catalog lived in `temp/specimens/`, and the batches made
before then record source paths there. Pass `--catalog tests/fixtures/specimens/catalog.yaml`
to `render` or `qualify` on such a batch: the harness then finds the moved source
through the catalog and uses it only if its fingerprint still matches the batch.

## Earlier fractal-paper evidence

Earlier outputs remain at their original locations; they have not been relabelled
as results of the new batch harness or copied into it. Their receipts may refer to
the source location before the specimen was moved.

- [Historical prototype master](2405.15943v3-tex/extracted/master.tex).
- [Reader-based prepared master before specimen organization](../../../../../temp/t/pytexml/20261023-comparison/after/master.tex).
- [Original/prepared rendering comparison](../../../../../temp/t/pytexml/20261023-rendering/pair-2/comparison.json).

The first named batch establishes the baseline at the specimens' current locations.
