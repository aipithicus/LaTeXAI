# Development specimens

Start at the [iteration index](../specimen-runs/INDEX.md) to inspect current results.
[catalog.yaml](catalog.yaml) declares each stable identifier, title, source directory
and explicit main document. New papers can be added as new catalog records.

| Specimen | Paper | Main source |
| --- | --- | --- |
| 2306.01911v1 | Generalized Bayesian MARS | [main.tex](2306.01911v1-tex/main.tex) |
| 2405.15943v3 | Transformers Represent Belief State Geometry | [fractals_in_residual_stream.tex](2405.15943v3-tex/fractals_in_residual_stream.tex) |
| 2412.11340v4 | Fast Bayesian Functional Principal Components Analysis | [Main.tex](2412.11340v4-tex/Main.tex) |
| 2512.18792v1 | The Dead Salmons of AI Interpretability | [00_main.tex](2512.18792v1-tex/00_main.tex) |

Source directories are inputs. Do not run preparation into their `extracted/`
directories: named iteration outputs go in the sibling `specimen-runs/` collection.
The fractal paper's existing `extracted/` is historical prototype evidence. It is
excluded from new source fingerprints and preparation discovery.

Each iteration has a purpose note, code/source fingerprints, one result per paper,
prepared packages, and links to changes from the preceding attempt for that paper.
Add observations to the iteration's `NOTES.md`; the generated index never rewrites
that file. A failed attempt stays visible, including when a previous attempt worked.
Rendering is opt-in and receives its own named evidence directory inside the batch.

See the [workflow recipe](../../recipes/specimen-iterations.md) for commands and
the shared-resource/retention rules.

From the PyTeXML directory, the next batch can be created with:

```text
python -B -m src.validation.specimens --runs temp/specimen-runs run --catalog temp/specimens/catalog.yaml --name <new-iteration-name> --note "What changed and what this run checks"
```

Add `--specimen 2405.15943v3` to run only that paper. Omit it to run the full catalog.

## Earlier fractal-paper evidence

Earlier outputs remain at their original locations; they have not been relabelled
as results of the new batch harness or copied into it. Their receipts may refer to
the source location before the specimen was moved.

- [Historical prototype master](2405.15943v3-tex/extracted/master.tex).
- [Reader-based prepared master before specimen organization](../../../../temp/t/pytexml/20261023-comparison/after/master.tex).
- [Original/prepared rendering comparison](../../../../temp/t/pytexml/20261023-rendering/pair-2/comparison.json).

The first named batch establishes the baseline at the specimens' current locations.
