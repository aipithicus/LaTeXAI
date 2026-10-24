
### 1. The Point in Git History (The Working Prototype)

The python initiative originally lived under the folder [`python/latex-extractor`](file:///d:/aipithicus/LaTeXAI) before commit [`cf73554`](file:///d:/aipithicus/LaTeXAI) renamed it to `PyTeXML`.

The key commits for that prototype are:

* **Recommended snapshot: Commit [`05f370d`](file:///d:/aipithicus/LaTeXAI) (`05f370dfa92c6883283da066c7e6c7dc89bccebc`)**
  * **Date**: September 29, 2026, 15:59:30 -07:00
  * **Message**: `latex-extractor updates and fixes`
  * **What it has**: This is the most complete, working state of the early monolithic pipeline before the architecture was pivoted toward the declarative YAML profile/mouth system. It contains:
    * `python/latex-extractor/pipeline.py` (coordinates [preflight](file:///d:/aipithicus/LaTeXAI/python/latex-extractor/preflight.py), [inliner](file:///d:/aipithicus/LaTeXAI/python/latex-extractor/inliner.py), [pruner](file:///d:/aipithicus/LaTeXAI/python/latex-extractor/pruner.py), [normalizer](file:///d:/aipithicus/LaTeXAI/python/latex-extractor/normalizer.py), [converter](file:///d:/aipithicus/LaTeXAI/python/latex-extractor/converter.py), and emits `master.tex`, `master.provenance.json`, `manifest.json`, and SVG conversions).
    * `python/latex-extractor/bibtex.py` and `bibliography.py` (native BibTeX parsing & `.bbl` resolution).
    * `t/latex-extractor/test_preprocessing.py` (27 passing unit tests).
* **Initial pilot commit: Commit [`de5d9b7`](file:///d:/aipithicus/LaTeXAI)**
  * **Date**: September 29, 2026, 03:45:36 -07:00
  * **Message**: `latex-extractor python pilot added`

---

### 2. The Fractals Paper & Generated `master.tex`

The example paper on fractals is arXiv **2405.15943v3**:
* **Title**: *"Transformers Represent Belief State Geometry in their Residual Stream"* (Shai et al.)
* **Root entrypoint**: `fractals_in_residual_stream.tex`
* **Source tree**: [`d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/`](file:///d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/)

The generated output package from the run is intact on disk at:
* **Directory**: [`d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/extracted/`](file:///d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/extracted/)
  * [`master.tex`](file:///d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/extracted/master.tex) (63.9 KB flattened master file)
  * [`master.provenance.json`](file:///d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/extracted/master.provenance.json) (28.7 KB RLE interval source map)
  * [`manifest.json`](file:///d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/extracted/manifest.json) (preflight audit and characterization metadata)
  * Converted vector figures (`Fig6.svg`, `LN.svg`, `MSEvsloss.svg`, `Z1R_example.svg`, `main_results.svg`, `mess3_overview.svg`, `procedure.svg`, `rrxor.svg`, `z1rmsp.svg`)
  * Local style package: [`neurips_2024.sty`](file:///d:/aghado01/codex-scientiae/supellex-private/staging/2405.15943v3/2405.15943v3-tex/extracted/neurips_2024.sty)

*(Note: There is also a second paper run output in the sibling directory for comparison: [`2608.18282v1/extracted/master.tex`](file:///d:/aghado01/codex-scientiae/supellex-private/staging/2608.18282v1/2608.18282v1-tex/extracted/master.tex).)*

---

### 3. Test Run Logs and Invocations

The captured execution outputs, run logs, and exit artifacts were written to:
* **Directory**: [`d:/aipithicus/LaTeXAI/temp/t/latex-extractor/runs/`](file:///d:/aipithicus/LaTeXAI/temp/t/latex-extractor/runs/)
  * [`native-corpus-final/result.json`](file:///d:/aipithicus/LaTeXAI/temp/t/latex-extractor/runs/native-corpus-final/result.json) & [`stdout.bin`](file:///d:/aipithicus/LaTeXAI/temp/t/latex-extractor/runs/native-corpus-final/stdout.bin) (corpus run against `2405.15943v3` and `2608.18282v1`)
  * [`corpus-01/result.json`](file:///d:/aipithicus/LaTeXAI/temp/t/latex-extractor/runs/corpus-01/result.json)
  * [`verification-final/result.json`](file:///d:/aipithicus/LaTeXAI/temp/t/latex-extractor/runs/verification-final/result.json) (27-test regression suite run)

---

### 4. How to Restore the Prototype to a Separate Directory

To inspect and study the code side-by-side without disturbing your current uncommitted changes or working tree in `PyTeXML`, you can export commit `05f370d` to an external directory:

```powershell
# Create destination directory (e.g. in your scratch area)
mkdir d:\aipithicus\LaTeXAI\temp\prototype-05f370d

# Extract only the prototype source and tests from commit 05f370d
git -C d:\aipithicus\LaTeXAI archive 05f370dfa92c6883283da066c7e6c7dc89bccebc python/latex-extractor t/latex-extractor | tar -x -C d:\aipithicus\LaTeXAI\temp\prototype-05f370d
```


Used MCP tool: nushell/evaluate
Used MCP tool: nushell/evaluate
Used MCP tool: nushell/evaluate
Used MCP tool: nushell/evaluate
Used MCP tool: nushell/evaluate
Used MCP tool: nushell/evaluate
Used MCP tool: nushell/evaluate

The prototype from commit [`05f370d`](file:///d:/aipithicus/LaTeXAI) has been extracted to:

[`D:\aipithicus\LaTeXAI\python\PyTeXML\temp\prototype-05f370d`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d)

### Extracted Layout

* **Source Code**: [`prototype-05f370d/python/latex-extractor/`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/)
  * [`pipeline.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/pipeline.py) — coordinates the preprocessing pipeline and emits `master.tex`, `master.provenance.json`, `manifest.json`, and SVG assets.
  * [`inliner.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/inliner.py) — recursive input flattener and `.bbl` splicer.
  * [`preflight.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/preflight.py) — root detection, asset classification, and draft-mode probing.
  * [`pruner.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/pruner.py) — semantic conditional simplification and comment stripping.
  * [`normalizer.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/normalizer.py) — Knuth TeX reader state machine.
  * [`converter.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/converter.py) — graphics conversion and reference rewriting.
  * [`bibtex.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/bibtex.py) & [`bibliography.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/bibliography.py) — native bibliography resolving.
  * [`provenance.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/provenance.py) & [`source_io.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/source_io.py) — RLE interval mapping and decoding.
  * [`DESIGN.md`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/DESIGN.md) & [`notes.md`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/python/latex-extractor/notes.md).
* **Test Suite**: [`prototype-05f370d/t/latex-extractor/`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/t/latex-extractor/)
  * [`test_preprocessing.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/prototype-05f370d/t/latex-extractor/test_preprocessing.py) — unit tests covering inlining, conditional pruning, root discovery, and output verification.

Your existing tracked files and working tree were left completely untouched.