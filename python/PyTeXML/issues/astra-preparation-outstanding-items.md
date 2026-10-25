We now have a working preparation pipeline built around the reader. The remaining work is chiefly **extending bounded reading knowledge, closing specific payload gaps, and finishing publication/cleanup discipline**.

The intended endpoint remains: **`master.tex` plus its necessary payload becomes the source of truth**, with raw-source provenance retained for diagnostics. General macro expansion is not a prerequisite.

Currently, preparation:

- Indexes sources and caches reads, excluding generated output.
- Traverses established inputs with shared reading state and distinct occurrence identities.
- Preserves definitions and literal regions, handles supported conditionals, and records unresolved constructs.
- Inlines supported sources and bibliographies, converts admitted assets, and retains necessary local code.
- Normalizes established mouth events, tracks edits, and publishes final locations independently of the provenance sidecar.

That sequence is implemented in the [preparation path](D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py:13).

The latest qualification is **664 passing tests**, with these specimen outcomes:

| Specimen | Preparation status | Remaining preparation work |
|---|---|---|
| Bayesian MARS | Complete under recorded assumptions | None currently identified |
| FPCA | Complete under recorded assumptions | None currently identified |
| Fractal | Partial | Possible `lineno` dependency inside an unresolved branch |
| DeadSalmons | Partial | Natbib option-state uncertainty; image dependency inside a deferred shipout expression |

All four publish their payloads. “Complete” here describes the bounded preparation contract; it does not mean all their interpretation requirements are resolved.

I would organize what remains into five areas.

1. **Capture more ordinary declarations and deferred code accurately.**
   This is the next useful extension. Natbib’s uncertainty starts at an unsupported `\providecommand`; Fractal’s local style contains ordinary `\renewenvironment` declarations and hooks. These should have declarative capture contracts so defining or scheduling code does not look like executing arbitrary code immediately. Start with bounded `\providecommand`, then ordinary environment declarations and hook registration. Preserve bodies and account for their timing without expanding them.

2. **Finish source-visible dependency preparation inside deferred and retained code.**
   We now distinguish possible dependencies correctly, but identifying one does not always prepare it. DeadSalmons’ shipout image is a concrete example. Imports and asset references inside retained local styles also have explicit limitations. The objective is to prepare literal, safely resolvable resources while preserving the enclosing construct and its unresolved activity. Computed filenames that genuinely require interpretation should remain clearly identified.

3. **Broaden resource fidelity.**
   PDF assets need per-occurrence page selection and variant identity: one file can supply several different figures. Non-first-page requests are **explicitly deferred today**, rather than silently converted as page one. Bibliography support still needs BibLaTeX and multiple bibliography sites; multiple databases feeding one bibliography are a different case and already supported. Subfile preamble handling also remains unfinished. See the current [asset admission check](D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py:384) and [bibliography formatter](D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/bibliography.py:28).

4. **Finish preparation hygiene.**
   Ordinary whitespace normalization and comment removal already follow reader events; literal and stored bodies remain protected. Further compaction and package/draft cleanup need explicit policies over established spans. General lint/repair is still unimplemented. Publication also needs stale-output management and a transactional checkpoint: currently a rerun removes the previous master before preparation completes. The append-only log exists, but the reusable structured logger you wanted does not yet. Five pre-existing empty EOF units also need their final locations completed.

5. **Strengthen qualification of the prepared artifact itself.**
   Add relocation checks—resolve prepared dependencies with the raw source unavailable—and exercise the optional original-versus-master rendering adapter across the specimens. The latest iteration verified source accounting, output locations, references and assets; it did not perform a fresh full-paper rendering comparison for all four. Continue adding specimens by distinct reading/resource behavior.

**My recommended next increment is bounded declaration capture, beginning with `\providecommand`.** It addresses an observed obstruction and improves the reader’s distinction between storing code and running it. Follow that with environment declarations and hook capture, then revisit the remaining specimen dependencies.

Full expansion, XML construction, counters/reference resolution, asynchronous scheduling, and broad binding migration remain downstream work. Their outstanding requirements should not prevent us from finishing this preparation contract.


---

Viewed astra-preparation-outstanding-items.md:1-46

Looking at [`astra-preparation-outstanding-items.md`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/issues/astra-preparation-outstanding-items.md), you are standing at the **most critical fork in the road** for the entire PyTeXML architecture.

Astra’s closing recommendation (lines 43–44):
> *"My recommended next increment is bounded declaration capture, beginning with `\providecommand`... Follow that with environment declarations and hook capture..."*

**Astra is recommending the exact Facehugger trap.**

Astra sees that `DeadSalmons` stalls on `\providecommand` and `Fractal` stalls on `\renewenvironment` and hooks. The agent’s natural instinct is: *"Let's add `\providecommand` to the dispatcher! Then let's add `\renewenvironment`! Then let's add hook timing!"*

If you take that path, here is what happens next week:
1. You add `\providecommand` to [`definition_scanner.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/definition_scanner.py).
2. Then a paper uses `\DeclareRobustCommand`, so you add that.
3. Then `Fractal` needs hook execution ordering (`\AddToHook`, `\AtBeginDocument`), so you start building a mini-hook scheduler inside [`session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py).
4. Then a package uses `\let` or `\csname`, and you start adding macro expansion.
5. **Result:** `dispatcher.py` and `session.py` blow past 1,500 lines of spaghetti, and preparation has completely lost its identity. It has become an accidental, incomplete LaTeX engine.

---

### The Litmus Test: What Belongs in `master.tex` Preparation?

To decide what is **general and aligned** versus what **compounds technical debt**, use this simple rule:

| Belongs in Preparation (Phase 1) | Belongs in Interpretation (Phase 2) |
| :--- | :--- |
| **Hermetic Containment:** Inlining files, bundling assets, normalizing UTF-8/Mouth characters, emitting single `thebibliography`. | **Macro Semantics:** Expanding macros, executing booleans, running hooks, tracking registers. |
| **Asset Packaging:** Converting PDFs/EPS to SVG, extracting multi-page figures (`page=2`), flattening directory paths. | **Layout & Document State:** Counter increments, cross-references (`\ref`), environment math scoping. |
| **Opaque Pass-Through:** Preserving unexpanded commands/environments cleanly into `master.tex`. | **AST/DOM Construction:** Turning TeX constructs into structured XML/HTML. |

---

### Evaluating Astra’s 5 Areas Under This Litmus Test

#### Area 1: Declaration Capture (`\providecommand`, hooks, `\renewenvironment`) $\rightarrow$ ⚠️ **HIGH RISK (Debt Compounding)**
* **Why it's a trap:** Trying to *evaluate* or *simulate* these commands inside `dispatcher.py` pulls Phase 1 into the LaTeX Gullet/Stomach.
* **The General, Clean Alternative:** **Opaque Pass-Through.**
  Instead of teaching `StructuralDispatcher` how to evaluate `\providecommand` or schedule hooks, treat them as **uninterpreted source slices**. Preparation should simply pass them through into `master.tex` untouched. They are the downstream parser's problem, not preparation's problem.

---

#### Area 2: Source-Visible Dependencies in Retained Code $\rightarrow$  **HIGH LEVERAGE (Directionally Aligned)**
* **Why it's aligned:** If a paper has an image reference inside an uninterpreted macro (e.g. `\AtBeginShipout{\includegraphics{watermark.png}}`), preparation *must* discover `watermark.png` and convert it to SVG. Otherwise, `master.tex` will reference an asset that does not exist in the output directory.
* **The Boundary:** Harvest **literal filenames** from observed commands without executing the enclosing TeX code. If the filename is literal, package it. If it is computed (`\includegraphics{\myfig}`), emit a located requirement. Zero TeX VM creep.

---

#### Area 3: Broaden Resource Fidelity (PDF Page Selection & BibTeX) $\rightarrow$  **HIGH LEVERAGE (Pure Packaging Physics)**
* **Why it's aligned:** 
  - **Multi-page PDF figures:** Papers frequently do `\includegraphics[page=2]{figures.pdf}`. Currently, PyTeXML explicitly defers non-first pages. Making the asset pipeline convert page 2 into `figures_p2.svg` is pure asset engineering (PyMuPDF/Inkscape). It has zero macro-expansion risk and makes dozens of real-world papers compile cleanly.
  - **BibTeX multi-file resolution:** Searching multiple `.bib` files and flattening them into a single `\begin{thebibliography}` is the crown jewel of `master.tex` preparation. Finishing BibLaTeX resource harvesting follows that exact same clean model.

---

#### Area 4: Preparation Hygiene & Transactional Publishing $\rightarrow$  **FOUNDATIONAL EXCELLENCE**
* **Why it's aligned:**
  - **Transactional publishing:** Currently, a rerun unlinks the previous `master.tex` before preparation finishes. Making it atomic (`out_dir / master.tex.tmp` $\rightarrow$ atomic rename on completion) ensures partial failures never leave a corrupted artifact.
  - **Structured logging & location finalization:** Cleaning up the 5 empty EOF unit locations and emitting structured logs is pure build-tool hygiene.

---

#### Area 5: Relocation Qualification $\rightarrow$  **THE GOLD STANDARD (The Ultimate Litmus Test)**
* **Why it's aligned:**
  - Astra suggests: *“Resolve prepared dependencies with the raw source unavailable.”*
  - **This is the true definition of done for Phase 1:** Take the generated `extracted/` folder, copy it to a blank temporary directory with the original source completely inaccessible, and verify that `master.tex` and its SVGs are 100% self-contained.
  - This proves that Phase 1 succeeded without needing any downstream binding framework to be finished.

---

### Recommended Strategic Roadmap

Here is how you can direct your work to maximize general engineering quality and freeze the technical debt:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: ASSET & PACKAGING FIDELITY (Areas 2 & 3)                                │
│ • Implement PDF multi-page figure extraction (page=N -> figure_pN.svg).         │
│ • Harvest literal asset dependencies inside retained/deferred commands.         │
│ • Solidify multi-database BibTeX inlining.                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│ STEP 2: RELOCATION QUALIFICATION HARNESS (Area 5)                               │
│ • Build the automated check: compile/render master.tex with raw source deleted. │
│ • This locks in the "Hermetic Container" guarantee across your 4 specimens.      │
├─────────────────────────────────────────────────────────────────────────────────┤
│ STEP 3: TRANSACTIONAL HYGIENE (Area 4)                                          │
│ • Atomic output publishing (no broken master.tex on error).                     │
│ • Fix the 5 dangling EOF unit locations.                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│ STEP 4: BOUNDARY DEFENSE ON DECLARATIONS (Area 1 Alternative)                   │
│ • Tell Astra: Do NOT simulate \providecommand or hooks in dispatcher.py.       │
│ • Treat \providecommand and \renewenvironment as OPAQUE PASS-THROUGH blocks:    │
│   preserve their source spans into master.tex without evaluating booleans.      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

This sequence keeps `master.tex` laser-focused on **source containment, asset packaging, and character physics**, while slamming the door shut on the TeX Interpreter Creep.


### 1. The Reality Check: You Have Actually Won Phase 1

Astra reports: *"four-specimen PDF qualification remains incomplete."* 

Do not let this phrasing mislead you. Looking at the relocation logs and `run.json`, **this iteration is a decisive victory for the Preparation contract**:

1. **Bayesian MARS (2306.01911v1):** 43 pages $\rightarrow$ **Relocation PDF Qualified.**
2. **Fractal (2405.15943v3):** 19 pages $\rightarrow$ **Relocation PDF Qualified.**
3. **FPCA (2412.11340v4):** **Relocation XDV Qualified.**
   - In `relocation-xdv.json`: `"outside": []`, `"missing": []`.
   - Every single graphic, `.bbl`, `.bib`, and file was packaged 100% hermetically.
   - XeTeX/Tectonic processed the entire `master.tex` without a single missing file. The only blocker to PDF was `xdvipdfmx` complaining about a missing physical Metafont/Type1 font (`bbm12` — blackboard bold 12pt) on the host Windows machine. That is a **host TeX distribution dependency**, not a PyTeXML packaging defect.
4. **DeadSalmons (2512.18792v1):** Fails on an `xcolor` option clash that **reproduces identically on the raw unmodified author source**.
   - If an author wrote conflicting `\usepackage` options that standard LaTeX cannot compile out-of-the-box, PyTeXML's job is to faithfully preserve the source, not rewrite the author's preamble logic.

Astra also followed the boundary doctrine:
- YAML-driven opaque capture for `\providecommand` and `\renewenvironment` (zero dispatcher engine creep).
- Page-specific PDF extraction (`page=N`).
- Staged publication with rollback and zero unmapped EOF units.
- Relocation harness that deletes/hides raw source during qualification.
- 0 duplicated pooled bytes; 687 tests passing.

---

### 2. What Would Compound Technical Debt Right Now (The Traps)

If you take the wrong step at this crossroads, here is where debt will instantly compound:

| Tempting Action | The Debt It Creates | Verdict |
| :--- | :--- | :--- |
| **"Fix DeadSalmons's Option Clash"** | Trying to make `dispatcher.py` or `session.py` resolve package clashes by reordering `\usepackage` or stripping options (`[table]`). You turn preparation into an ad-hoc heuristic preamble re-writer. | ❌ **TRAP** |
| **"Fix FPCA's Font Dependency"** | Trying to make PyTeXML resolve Metafont/PK bitmap fonts or embed system font mappings for Tectonic. | ❌ **TRAP** |
| **Stacking Phase 2 Features onto a Dirty Tree** | Beginning AST generation or downstream interpretation while 687 tests and massive packaging changes remain uncommitted. | ❌ **TRAP** |
| **Simulating More TeX Commands** | Expanding `dispatcher.py` to evaluate more macros or hooks just to clear "partial" status flags. | ❌ **TRAP** |

---

### 3. What is General, High-Leverage, and Aligned With Your Direction

Here is the clean, disciplined sequence of next steps:

#### Step 1: Commit and Freeze the Packaging Milestone
Astra notes: *"Changes remain uncommitted."*
Before touching anything else:
- Review the diff to confirm Astra did not slip subtle fallbacks into `session.py` or `dispatcher.py`.
- **Commit this packaging milestone.** It establishes your verified baseline (687 tests green, relocation harness in place, zero pooled byte leaks).

#### Step 2: Formalize the Failure Taxonomy in the Qualification Harness
Currently, the report lumps everything into *"qualification incomplete"*, which tempts agents to fix things that aren't preparation bugs. 

Enhance the qualification schema to classify specimen outcomes into three distinct buckets:
- `QUALIFIED`: Staged payload compiles cleanly to PDF or XDV with zero source leaks.
- `BASELINE_DEFECT`: Compilation fails identically on raw author source (e.g. DeadSalmons `xcolor` clash). **Status: Preparation Succeeded, Author Code Broken.**
- `ENVIRONMENT_LIMITATION`: XDV succeeded with zero payload leaks (`outside: []`, `missing: []`), but PDF driver lacks host system fonts (e.g. FPCA `bbm12`). **Status: Packaging Hermetic, Host Lacks Font.**

This one schema clarification permanently protects your architecture from agents trying to "fix" author errors inside preparation.

#### Step 3: Cash In on the Safety Net — Seam Purification (The Refactor Step)
You now have the **strongest regression test net in the project's history**: 687 passing unit tests *plus* a multi-specimen relocation harness.

This is the exact moment to perform the overdue refactoring we audited in [`gemini-refactor-audit-smells.md`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/gemini-refactor-audit-smells.md) without adding any new features:
1. **Relieve `StructuralDispatcher` (797 LOC) & `PreparationSession` (728 LOC):**
   - Now that `\providecommand` and `\renewenvironment` are YAML-driven opaque blocks, audit and prune any dead speculative hooks from `definition_scanner.py` and `dispatcher.py`.
   - Enforce the narrow interface for `prepare_bibliography(spec, out_dir)` so `session.py` stops passing its entire internal state.
2. **Replace Loose Dicts with Typed DTOs:**
   - Migrate the unvalidated dictionaries in `verification.json` and publication staging into typed dataclasses (e.g. `PublicationManifest`, `SpecimenQualificationReceipt`).

#### Step 4: The Clean Transition to Phase 2 (Interpretation / AST)
With `master.tex` guaranteed to be self-contained:
- **Phase 1 is complete.**
- You can now start Phase 2 (the downstream parser/XML generator) as a **completely independent subsystem**. It reads `master.tex` directly. It never imports `assets.py`, never talks to BibTeX, and never touches multi-file filesystem trees.

---

### Summary Checklist for Your Crossroads

- [ ] **Lock It:** Commit the 4 uncommitted workstreams.
- [ ] **Classify It:** Distinguish `BASELINE_DEFECT` / `HOST_FONT` from true preparation packaging failures in the relocation runner.
- [ ] **Purify It (Optional before Phase 2):** Use the green 687-test suite to clean up `session.py` micro-debt.
- [ ] **Cross the Seam:** Declare Phase 1 `master.tex` preparation done; begin Phase 2 interpretation cleanly above the seam.


**Yes to both**, and your intuition here cuts straight to the core difference between **real-world document ingestion** and a **rigid TeX compiler**.

In fact, if you want PyTeXML to ingest real-world arXiv papers at scale, handling font substitutions and repairing author-side preamble bugs are both **essential capabilities**.

The entire trick is **how** and **where** to do them so they remain general and clean, rather than turning into brittle, ad-hoc spaghetti.

---

### 1. The Font Issue: Content vs. Notational Morphology

Your premise is 100% correct.

#### What actually happened in FPCA:
In `2412.11340v4/Main.tex`:
```latex
\usepackage{bbm,comment}
...
\mathbbm{1}(\mathbf{\Psi} \in \mathcal{V}_{K,Q})   % Used exclusively for the indicator function 1!
```
- The author only loaded `bbm` to get a blackboard-bold digit 1 ($\mathbb{1}$).
- `bbm` is a 1990-era legacy package that relies on METAFONT bitmap files (`bbm12.mf` $\rightarrow$ `.pk`).
- Tectonic **successfully parsed and compiled the entire document into `.xdv`** (eXtended DVI). The `.xdv` holds 100% of the content, math, layout, and document structure.
- The failure only occurred downstream in `xdvipdfmx` when trying to locate the physical bitmap font rasterizer to paint pixels on a page.

#### How to handle this cleanly (Content-First):
1. **In Semantic Extraction (Phase 2):**
   Fonts are irrelevant. In [`capture/packages/bbm.yaml`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/resources/bindings/packages):
   `\mathbbm{1}` simply maps to `<m:mn mathvariant="double-struck">1</m:mn>` (Unicode `U+1D7D9`). Zero font files needed.
2. **In Qualification / PDF Rendering:**
   If you want visual PDF qualification without installing ancient bitmap fonts on the OS, use a **font/package compatibility shim**:
   - Provide a qualification shim (e.g. Injected preamble policy: `\usepackage{dsfont}` with `\let\mathbbm\mathds`, or `\providecommand{\mathbbm}[1]{\mathbf{#1}}`).
   - Tectonic compiles directly to PDF without choking on missing bitmap fonts.

---

### 2. Diagnosing and Repairing Author Code (The `xcolor` Clash)

Your intuition is again spot on. Authors submit broken, fragile LaTeX all the time.

#### What actually happened in DeadSalmons:
```latex
\documentclass{article}
\usepackage{iclr2026_conference,times}  % iclr2026 loads eso-pic, which loads xcolor WITHOUT options
...
\usepackage[table]{xcolor}              % CRASH: Option clash for package xcolor
```
Standard LaTeX rules state that if a package is already loaded with no options, a subsequent `\usepackage[options]{...}` throws a fatal option clash.

The standard fix every LaTeX author uses is simply placing:
```latex
\PassOptionsToPackage{table}{xcolor}
```
**before** `\documentclass` or before the first package.

---

### 3. How to Do Both Without Compounding Technical Debt

The reason earlier audits warned against "fixing" these inside preparation wasn't because repairing them is bad—it was because of **how AI agents usually implement them**:
- ❌ **The Debt Trap (Silent Mutation inside the Parser):**
  An agent adds a regex inside `StructuralDispatcher.read_command` that intercepts `\usepackage` calls, guesses author intent, and silently deletes `[table]`. Now the parser is full of magical side effects, breaks round-trip provenance, and will fail on the next 10 packages.

-  **The Clean Architectural Pattern (Explicit Diagnostic & Repair Passes):**
  Treat diagnosis and repair as an **explicit, modular Pre-Flight pass** with a clear contract:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. DIAGNOSTIC LINTER (Pre-Flight Analysis)                  │
│    • Audits the raw AST / Preamble.                         │
│    • Detects known clashes:                                 │
│      - Option Clash: [table] on xcolor loaded after iclr    │
│      - Legacy Bitmap Font: bbm loaded in modern engine      │
├─────────────────────────────────────────────────────────────┤
│ 2. REPAIR / NORMALIZATION PASS (Explicit Policy)            │
│    • Injects canonical remedy:                              │
│      \PassOptionsToPackage{table}{xcolor}                   │
│      \let\mathbbm\mathbf (or modern unicode-math alias)     │
│    • Records an EXPLICIT patch in `master.provenance.json`: │
│      "remediations": [{"type": "option_clash_resolution"}]  │
├─────────────────────────────────────────────────────────────┤
│ 3. HERMETIC COMPILER / QUALIFIER                            │
│    • Compiles the repaired `master.tex`.                    │
│    • 100% of specimens achieve qualified PDF output!        │
└─────────────────────────────────────────────────────────────┘
```

### Why this is general and powerful:
1. **Separation of Physics and Policy:** The `StructuralDispatcher` remains a neutral, predictable LaTeX reader. It doesn't need to know about `xcolor` or `bbm`.
2. **Transparent Provenance:** You never silently tamper with author source without leaving an audit trail in `master.provenance.json` and `master.diff`.
3. **Solves Real Ingestion:** This turns PyTeXML into an intelligent, resilient ingestion pipeline that can take dirty arXiv submissions, diagnose them, apply standard LaTeX pre-flight remedies, and produce qualified, compilable artifacts.

--- 

Listed directory skills-dev

Not only is it feasible, it is arguably the **single best architectural home** for this kind of work.

Attempting to hardcode author preamble repairs into PyTeXML’s core engine (`dispatcher.py` or `session.py`) creates an unmaintainable "Facehugger." In contrast, encapsulating it as an **Agent Skill** (e.g. `latex-preamble-doctor` or `latex-preflight-repair`) keeps the core engine pure while leveraging an LLM's greatest strength: interpreting messy, contextual compiler diagnostics and applying targeted domain recipes.

Here is how such a skill would be structured, why it works so well, and the invariants that keep it disciplined.

---

### Why an Agent Skill Excels Here

| Approach | Where It Struggles | Why the Skill Wins |
| :--- | :--- | :--- |
| **Compiler / Parser Engine** | LaTeX preambles are Turing-complete. Hardcoding regexes for package order or option conflicts leads to endless edge cases and breaks source provenance. | Keeps the ingestion engine purely focused on character physics, inlining, and asset packaging. |
| **Static Linters (chktex, etc.)** | Traditional linters check formatting (unmatched brackets, punctuation, spacing). They have zero understanding of package dependency graphs or compiler option clashes. | Reads the compiler log (`prepared.log`), identifies the specific TeX error, and correlates it with the package loading order. |
| **Agent Skill** | — | **Surgical & Audited:** Diagnoses the log, applies a standard TeX recipe, verifies compilation, and writes an explicit patch record. |

---

### Anatomy of the Skill: `latex-preamble-doctor`

Following standard Agent Skill conventions, it would look like this:

#### 1. Inputs
- Target LaTeX source (or staged `master.tex`).
- Compiler transcript / log (`prepared.log` or Tectonic stdout/stderr).
- Local style files (`*.sty`) present in the manuscript bundle.

#### 2. The Diagnostic & Recipe Catalog (The Skill's Knowledge)

The skill would carry a curated catalog of standard TeX preamble failure patterns and their canonical, least-invasive remedies:

1. **Option Clash on Transitive Packages (`xcolor`, `geometry`, `natbib`)**
   - *Diagnostic:* `! LaTeX Error: Option clash for package <PKG>.`
   - *Cause:* Package $A$ (e.g. `iclr_conference` or `eso-pic`) loaded `<PKG>` with default options before the author explicitly called `\usepackage[opt]{<PKG>}`.
   - *Canonical Remedy:* Hoist `\PassOptionsToPackage{<opt>}{<PKG>}` to line 1, immediately *before* `\documentclass`. Never delete the author's options.

2. **Legacy Bitmap Font Traps (`bbm`, old METAFONT packages)**
   - *Diagnostic:* `xdvipdfmx:fatal: Cannot proceed without normal font: bbm12` or missing `.pk` bitmap font.
   - *Cause:* Author used a 1990s bitmap font package for a single glyph (e.g. `\mathbbm{1}` for indicator function).
   - *Canonical Remedy:* Inject a modern vector fallback in the preamble:
     ```latex
     % Injected by latex-preamble-doctor: modern vector fallback for bbm indicator
     \usepackage{dsfont}
     \let\mathbbm\mathds
     ```
     (or `\providecommand{\mathbbm}[1]{\mathbf{#1}}`).

3. **Package Ordering Collisions (`hyperref`, `amsmath`, `cleveref`)**
   - *Diagnostic:* `! Package amsmath Error: Erroneous nested display math` or `\ref undefined` quirks.
   - *Cause:* `hyperref` loaded before `amsmath`, or `cleveref` loaded before `hyperref`.
   - *Canonical Remedy:* Apply standard topological sort (move `hyperref` to bottom of preamble, keep `cleveref` after it).

4. **Engine / Catcode Incompatibilities in XeTeX / LuaTeX**
   - *Diagnostic:* `! Package inputenc Error: inputenc is not suitable for ...`
   - *Cause:* Legacy `\usepackage[utf8]{inputenc}` in an engine that is natively UTF-8.
   - *Canonical Remedy:* Safely comment out `inputenc` with an explanatory marker.

---

### Strict Skill Invariants (Preventing Agent Creep)

To prevent the agent from destroying author manuscripts, the skill must enforce four hard boundaries:

1. **Preamble Only (Zero Body Touching):**
   - The skill is forbidden from modifying any line below `\begin{document}`. If the body has a fatal author syntax error, the skill halts and reports `FATAL_BODY_DEFECT`.
2. **Explicit Patch & Provenance:**
   - Every change must emit a transparent diff or record in `provenance.json`:
     ```json
     {
       "remediations": [
         {
           "rule": "preamble_option_clash",
           "package": "xcolor",
           "remedy": "\\PassOptionsToPackage{table}{xcolor}",
           "line": 1
         }
       ]
     }
     ```
3. **Bounded Repair Loop (The Anti-Spin Lock):**
   - Attempt 1 $\rightarrow$ Compile. If failed $\rightarrow$ Attempt 2 $\rightarrow$ Compile.
   - If still failing after **2 iterations**, STOP. Emit an escalation report rather than making increasingly wild guesses.
4. **Relocation Qualification Check:**
   - The skill verifies the fix by invoking the qualification compiler (e.g. Tectonic) in an isolated sandbox. Only if compilation succeeds does it accept the patch.

---

### How This Fits Into PyTeXML's Ecosystem

With this skill:
1. **PyTeXML Engine** does the mechanical heavy lifting: file inlining, asset flattening, multi-database `.bib` resolution, and UTF-8 Mouth normalization.
2. If the qualification harness encounters an author-side baseline failure (like DeadSalmons's `xcolor` or FPCA's `bbm`), you invoke `/latex-preamble-doctor`.
3. The doctor applies the 1-line surgical patch, qualifications turn green (4/4 specimens passing to PDF), and your provenance ledger records exactly what was patched.