# PyTeXML Refactoring & Architectural Shape Audit

## 1. Executive Summary: The Shape Gate vs. The Test Trap

The PyTeXML codebase has reached an extraordinary level of behavioral maturity: **687 tests pass across 45 test suites** (including relocation qualification, live rendering, transactional rollback, and checked repairs).

However, auditing PyTeXML through the updated lenses of **Facehugger Seam Gates**, **Beck’s Precedence**, and **C.U.P.I.D. Heuristics** reveals a critical architectural contrast between newly added modular subsystems and the two central orchestrators:

> **The Test Trap:** Tests check behavior, but audits check shape. PyTeXML's test suite is 100% green, yet the two central orchestrators have breached the >500 LOC **Architectural Decision Point**. New capabilities (diagnostics, relocation, transactional publishing, bounded linting) were authored with high modularity (<200 LOC each), but their glue hooks were routed through the two legacy God classes, inflating them further.

| Severity | Smell / Architectural Anti-Pattern | Primary Location | Key Indicator & Calibrated Invariant |
| :--- | :--- | :--- | :--- |
| **Critical** | **Escaped Seam (Facehugger)** | [`dispatcher.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py) (930 LOC)<br>[`session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py) (816 LOC) | Both central connectors have breached the >500 LOC architectural decision point. `dispatcher.py` coordinates 6 scanners and lexical lint hooks; `session.py` coordinates 40+ lifecycle fields. |
| **High** | **Accumulated Post-Turn Micro-Damage** | [`session.py:L623-628`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L623-L628) | Compound `if` clause with 3 `or` branches checking raw metadata for synthetic separator emission. (*Note: Astra cleanly pruned the earlier line 545 micro-tax in commit `6d57264`*). |
| **High** | **Primitive / Dict Obsession** | [`session.py:L164-175`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L164-L175), [`manifest.py:L99-115`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/manifest.py#L99-L115) | Core execution traces, candidate dependencies, and diagnostics use untyped `dict[str, Any]` and coordinate tuples `(r["source"], r["start"], r["end"])`. |
| **Medium** | **Inverted Coupler (Feature Envy)** | [`bibliography.py:L28-60`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/bibliography.py#L28-L60) | `prepare_bibliography` reaches directly into 6 internal session fields (`session.manifest`, `session.store`, `session.commands`, `session.bibliography_pieces`, etc.). |
| **Medium** | **Scanner Cross-Calls (Inappropriate Intimacy)** | [`environment_scanner.py:L44, L47`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/environment_scanner.py#L44) | Direct calls into private methods of foreign scanners (`args._nonspace()`, `definitions._body()`). |
| **Low** | **Deprecation Fence Parameters** | [`pipeline.py:L15-30`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py#L15-L30) | 5 retired parameters that throw `ValueError` immediately. Confirmed as intentional caller fences, not forgotten dead code. |

---

## 2. C.U.P.I.D. Subsystem Scorecard

Evaluating PyTeXML against Dan North’s C.U.P.I.D. properties (*Composable, Unix “fits in my head”, Predictable, Idiomatic, Domain-based*):

| Subsystem | C.U.P.I.D. Evaluation | Verdict |
| :--- | :--- | :--- |
| **[`tex_reader.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/tex_reader.py)** (577 LOC) | **Gold Standard.** Fits in head (Knuth's 3 states N/M/S), strictly predictable, idiomatic Python with `@dataclass(frozen=True, slots=True)`, rich domain language (*CatCodes, ReadEvents*). | **Preserve untouched.** |
| **[`validation/assessment.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/validation/assessment.py)** (90 LOC) | **Gold Standard.** Composable, Unix (pure projections over evidence), strictly predictable, zero mutable state. | **Preserve untouched.** |
| **[`validation/relocation.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/validation/relocation.py)** (136 LOC) | **High.** Clean sandbox boundary; audits Tectonic Makefile dependency receipts with zero leak tolerance. | **Preserve untouched.** |
| **[`prepare/publication.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/publication.py)** (117 LOC) | **High.** Fits in head (`OutputTransaction`), bounded Windows sharing lock retries, exception-safe rollback. | **Preserve untouched.** |
| **[`prepare/lint.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/lint.py)** (193 LOC) | **High.** Declarative YAML catalog, explicit user policy gating, mathematically bounded token-equivalence proof. | **Preserve untouched.** |
| **[`prepare/assets.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/assets.py)** (186 LOC) | **Good.** Extracted cleanly from `session.py`; handles multi-page `page=N` PDF extraction and rollback filtering. | **Preserve untouched.** |
| **[`reading/context.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/context.py)** (317 LOC) | **Passes Beck's Tie-Breaker.** Explicit scoped journal stacks. Readable and predictable. | **Do NOT over-DRY into a generic metaclass.** |
| **[`reading/dispatcher.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py)** (930 LOC) | **Fails Unix & Composable.** Breached the 500 LOC gate. Coordinates 6 scanners, token replays, conditionals, and lexical lint recovery. | **Decompose internally; re-cut seam.** |
| **[`prepare/session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py)** (816 LOC) | **Fails Unix & Predictable.** Breached the 500 LOC gate. 40+ instance fields; multi-phase lifecycle container. | **Architectural Decision Point (split plan).** |

---

## 3. Detailed Findings & Calibrated Playbooks

### A. The Escaped Seams (Facehuggers)

#### 1. `StructuralDispatcher`: From Lexical Delimiter to Virtual Machine
* **Location:** [`dispatcher.py:L67-590`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py#L67-L590) (930 lines)
* **The Diagnosis:**
  `StructuralDispatcher` was conceived as a narrow, temporary reading seam between the lexical mouth (`TexReader`) and Phase 1 preparation. Over successive iterations, it has accumulated:
  - Boolean register evaluation (`\newif`, `\iftrue`, `\iffalse`)
  - Macro parameter capture and storage (`\newcommand`, `stored_definition`)
  - Token replay through `TokenCursor`
  - Lexical failure checkpoints and character discard recovery for `lint.py` ([`dispatcher.py:L207-224`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py#L207-L224))
* **The Seam Litmus Test:**
  > *"Does this code merely connect two components, or has it started making domain decisions and coordinating their internals?"*
  `dispatcher.py` coordinates the internals of `LiteralScanner`, `DefinitionScanner`, `EnvironmentScanner`, and `AssignmentScanner`, and mediates error recovery.
* **Calibrated Treat (Re-cut Seam):**
  1. **Do NOT build a polymorphic hierarchy:** That replaces a bloated seam with an enterprise class explosion.
  2. **Decompose internally:** Break the monolithic item loop into private handler delegates (`_handle_conditional`, `_handle_definition`, `_handle_environment`).
  3. **Anti-Lobotomy Invariant:** Do **not** simplify lines 201–212 (reader state verification and CatCode table identity). Those checks preserve Knuthian TeX character physics.

#### 2. `PreparationSession`: The God Orchestrator
* **Location:** [`session.py:L64-125`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L64-L125) (816 lines)
* **The Diagnosis:**
  A 40-field class that acts as the container for all unresolved preparation state. While Astra did excellent work factoring out `assets.py`, `lint.py`, and `publication.py`, `PreparationSession` still owns:
  - Input frames and file stack traversal
  - Inlined source piece emission and synthetic separators
  - Diagnostic and requirement ledgers
  - Document coverage mapping
  - Forwarded package options and class loading order
* **Calibrated Treat (Surface Architectural Splits):**
  1. **Do not refactor autonomously:** Splitting this class touches the entire `src/prepare/` pipeline.
  2. **Protect Anchored Seams:** Fields like `self.manifest.reading_assumptions`, `self.manifest.candidate_dependencies`, and `self.units` are **staged architectural contracts** for downstream Phase 2 consumers. They are essential scaffolding.
  3. **Present the split options:**
     - *Option 1 (Domain Coordinators):* Extract `PackageOptionStore` and `EmissionJournal`.
     - *Option 2 (Configuration vs State):* Group configuration into `PreparationConfig` and let `PreparationSession` hold only the active traversal cursor.

---

### B. Accumulated Post-Turn Micro-Damage

#### 1. Compound Conditional Sprawl: `session.py:L623-628`
* **Location:** [`session.py:L623-628`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L623-L628)
* **The Code:**
  ```python
  # No-argument commands need a lexical separator after a control word.
  if (not command.arguments and action in {"opaque", "biblatex_print", "reading_noop", "process_options"}
          or action == "boolean_declaration" and command.metadata["unbraced"]
          or action == "conditional_test" and command.metadata["trailing_control_word"]):
      self._emit(command.span.basis.span(command.span.end, command.span.end), " ", operation="SYNTHETIC_SEPARATOR")
  ```
* **The Diagnosis:**
  Classic agent micro-damage: each prompt that introduced a new command family patched another `or` clause onto the emission check to pass a test case.
* **Calibrated Treat:**
  - **Extract Query Method:** Extract to a helper `command.requires_synthetic_separator()` or define a declarative property on `SourceCommand`.

---

### C. Primitive Obsession (Dictionary Obsession)

#### 1. Untyped Domain Records in Manifest & Session
* **Locations:**
  - Diagnostics: [`session.py:L164-175`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L164-L175)
  - Requirements: [`session.py:L186-196`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L186-L196)
  - Dependencies: [`dependencies.py:L60-68`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dependencies.py#L60-L68)
  - Manifest container: [`manifest.py:L99-115`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/manifest.py#L99-L115)
* **The Diagnosis:**
  While peripheral models (`BibliographyInfo`, `PackageUsage`, `AssetUse`) use `@dataclass`, the core execution trace is managed with untyped `dict[str, Any]` and coordinate tuples `(r["source"], r["start"], r["end"])`.
* **Calibrated Treat (Idiomatic Python):**
  1. Define flat, immutable `@dataclass(slots=True)` models: `DiagnosticRecord`, `RequirementRecord`, `DependencyEdge`.
  2. Implement clean `.to_dict()` methods on each to ensure seamless `manifest.json` serialization.
  3. Avoid deep inheritance trees (no `AbstractDiagnosticBase`).

---

### D. Couplers & Inappropriate Intimacy

#### 1. Inverted Boundary: `prepare_bibliography`
* **Location:** [`bibliography.py:L28-60`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/bibliography.py#L28-L60)
* **The Diagnosis:** `prepare_bibliography(pieces, session, output_dir)` reaches into 6 internal session attributes (`session.manifest`, `session.store`, `session.commands`, `session.bibliography_pieces`, `session.root`).
* **Calibrated Treat (Narrow the Interface):**
  - **Do NOT move it back into `session.py`** (that worsens the Large Class Facehugger).
  - Invert the dependency by passing only what it needs:
    `prepare_bibliography(pieces, declarations, store_root, origin_dir, existing_bbl_path)`

#### 2. Scanner Cross-Calls
* **Location:** [`environment_scanner.py:L44, L47`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/environment_scanner.py#L44)
* **The Diagnosis:** Calling private methods of foreign scanners (`args._nonspace()`, `definitions._body()`).
* **Calibrated Treat:**
  - Promote `nonspace()` to a public method on `ArgumentScanner` or hoist it to `TexReader`.

---

### E. Beck's Precedence Applied: What NOT to Refactor

#### 1. Token Equivalence Proof in `lint.py:L63-93`
* **Location:** [`lint.py:L63-93`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/lint.py#L63-L93)
* **Observation:** `checked_character_deletion` contains 30 lines of detailed token and character boundary checks.
* **Anti-Lobotomy Invariant:**
  - An agent might be tempted to simplify this into a simple `str.replace()` or regex.
  - **Verdict: PRESERVE UNTOUCHED.** This function is a mathematically bounded proof that dropping a specific catcode-15 invalid character reproduces TeX's exact mouth state. Simplifying it destroys verification rigor.

#### 2. Scoped Journals in `context.py:L58-65`
* **Location:** [`context.py:L58-65`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/context.py#L58-L65)
* **Observation:** Three journal stacks (`_meaning_scopes`, `_environment_scopes`, `_capture_setting_scopes`) follow similar push/pop logic.
* **Beck's Tie-Breaker (`Understandability > DRY`):**
  - Leave them explicit. The code is understandable, predictable, and maps 1-to-1 to TeX's distinct lexical namespaces. Deduplicating them into a generic meta-class reduces readability.

#### 3. Deprecation Fences in `preprocess_paper`
* **Location:** [`pipeline.py:L47-51`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py#L47-L51)
* **Observation:** Parameters `execute_probe`, `drop_commands`, etc., throw `ValueError`.
* **Verdict:** These are intentional deprecation fences protecting callers from silent failures. Verify caller migration before deleting.

---

## 4. Pre-Flight Test Pinning & Refactoring Sequence

PyTeXML now contains **687 tests across 45 test suites**. The regression test net is rock solid.

### Prioritized Remediation Roadmap:
```
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 1: LEAF-LEVEL CLEANUP (Zero Blast Radius)                        │
│ • Extract `command.requires_synthetic_separator` from session.py:623.  │
│ • Narrow `prepare_bibliography` interface (decouple from session).     │
│ • Promote `nonspace()` in argument_scanner.py to public.               │
├────────────────────────────────────────────────────────────────────────┤
│ STEP 2: TYPED MODELS (Primitive Obsession Relief)                      │
│ • Replace untyped dicts in `diagnose()` and `require()` with           │
│   `@dataclass(frozen=True, slots=True)` records + `.to_dict()`.        │
├────────────────────────────────────────────────────────────────────────┤
│ STEP 3: SEAM PURIFICATION (Facehugger Relief)                          │
│ • Decompose `StructuralDispatcher._next_item()` into private handlers.│
│ • Extract `PackageOptionStore` from `PreparationSession`.              │
│ • Declare Phase 1 complete; transition to Phase 2 Interpretation.      │
└────────────────────────────────────────────────────────────────────────┘
```
