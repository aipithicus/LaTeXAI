# PyTeXML Refactoring & Architectural Shape Audit
*Post-Batch-5 Verification & Scorecard*

## 1. Executive Summary: The Refactoring Harvest

Following the execution of Batches 1 through 5B (commits `cd468c5..0aac97c`), PyTeXML has undergone a comprehensive internal architectural consolidation:
* **780 tests pass across 46 test suites** (0 failures, 0 errors, 2 skipped).
* All 4 benchmark specimens ([`2306.01911v1`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/specimen-runs/20261024-packaging-final/2306.01911v1), [`2405.15943v3`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/specimen-runs/20261024-packaging-final/2405.15943v3), [`2412.11340v4`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/specimen-runs/20261024-packaging-final/2412.11340v4), [`2512.18792v1`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/temp/specimen-runs/20261024-packaging-final/2512.18792v1)) match their qualification baselines with byte-identical payload and provenance files.
* **4 of the 6 major smells identified in the earlier audit have been systematically resolved.**

### Audit Delta: Smells Cleared vs. Smells Remaining

| Smell / Anti-Pattern | Status Post-Batch-5 | Resolution Mechanism & Verification |
| :--- | :---: | :--- |
| **Failure-Location Leak (Functional Defect)** |  **CLEARED** | [`manifest.mark_failed()`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/manifest.py#L201-L211) resets all locations on publication failure. Failure manifests can never claim unpublished artifact coordinates. |
| **Primitive / Dict Obsession** |  **CLEARED** | Extracted [`src/prepare/records.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/records.py) with `TypedDict` models (`SourceReference`, `LocationRecord`, `WorkRecord`, `RequirementRecord`) and centralized factory constructors (`work_record`, `assign_locations`). |
| **Inverted Couplers & Feature Envy** |  **CLEARED** | Decoupled helpers in Batch 5B. [`test_preparation_ownership.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/test_preparation_ownership.py) verifies asset parsing/rewriting and citation discovery execute on plain data without requiring a `session` instance. |
| **Public Pipeline Parameter Duplication** |  **CLEARED** | Introduced immutable [`_PreparationRequest`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py#L18-L29). Deleted `dict(locals())` and centralized argument/path validation in the outer transaction wrapper. |
| **Scanner Cross-Calls (Inappropriate Intimacy)** |  **CLEARED** | Added [`source_command_syntax`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/contracts.py#L132) to formal `ReadingKnowledge` protocol; removed `getattr` probing. |
| **The Escaped Seams (Facehuggers)** | ⚠️ **CONTAINED / OPEN** | `StructuralDispatcher` (934 LOC) and `PreparationSession` (858 LOC) remain >500 LOC. While helper logic was pushed to satellite modules, the central routing and traversal loops remain large monolithic classes. |
| **Accumulated Post-Turn Micro-Damage** | ⚠️ **RESIDUAL** | Line 545 package-asset smell was deleted. Line 668 compound separator check remains: 3 `or` branches checking raw command metadata. |

---

## 2. Updated C.U.P.I.D. Subsystem Scorecard

Evaluating PyTeXML's revised architecture against Dan North’s C.U.P.I.D. properties (*Composable, Unix “fits in my head”, Predictable, Idiomatic, Domain-based*):

| Subsystem | LOC | C.U.P.I.D. Rating | Architectural Assessment |
| :--- | :---: | :--- | :--- |
| **[`tex_reader.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/tex_reader.py)** | 577 | **Gold Standard** | Knuthian 3-state mouth physics; immutable dataclasses with slots; strictly predictable. |
| **[`validation/assessment.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/validation/assessment.py)** | 90 | **Gold Standard** | Pure function; zero mutable state; derives top-level qualification status strictly from witnessed checks. |
| **[`prepare/publication.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/publication.py)** | 117 | **High** | Fits in one head (`OutputTransaction`); bounded Windows lock retries (`winerror` 5, 32, 33); exception-safe rollback. |
| **[`validation/relocation.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/validation/relocation.py)** | 136 | **High** | Strips environment search paths; audits Makefile dependency receipts with zero leak tolerance. |
| **[`prepare/records.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/records.py)** | 90 | **High** | Idiomatic Python `TypedDict` shapes; unifies manifest record builders; keeps reader units as identity authority. |
| **[`prepare/lint.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/lint.py)** | 185 | **High** | Declarative YAML catalog; explicit user policy gating; mathematically bounded proof of token equivalence. |
| **[`prepare/assets.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/assets.py)** | 172 | **High** | Extracted cleanly from `session.py`; handles multi-page `page=N` PDF extraction and pure-data rollback filtering. |
| **[`prepare/pipeline.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py)** | 231 | **High** | Clear division of labor: outer wrapper owns transaction, public API, and rollback; inner builder receives typed `_PreparationRequest`. |
| **[`reading/context.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/context.py)** | 317 | **Passes Beck's Tie-Breaker** | 3 journal stacks. High understandability over "Clever DRY". Protected by Beck's Rule #2. |
| **[`reading/dispatcher.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py)** | 934 | **Fails Unix & Composable** | Monolithic router (breached 500 LOC gate). Coordinates 6 scanners, token replays, conditionals, and lexical error handoffs. |
| **[`prepare/session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py)** | 858 | **Fails Unix & Predictable** | Traversal coordinator (breached 500 LOC gate). Coordinates file frames, emissions, coverage, tombstones, and option lifecycle. |

---

## 3. Deep Dive into Remaining Debt & Emerging Surfaces

### A. The Two Persistent Facehuggers (>500 LOC)

#### 1. `StructuralDispatcher` (934 LOC)
* **Location:** [`dispatcher.py:L67-590`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py#L67-L590)
* **The Diagnosis:**
  `StructuralDispatcher` is the single largest class in the repository. It has successfully avoided macro-expansion creep (opaque commands and declarations are cleanly YAML-driven), but its internal `_next_item` loop remains a dense, multi-way branch coordinating:
  - Scanners: `LiteralScanner`, `DefinitionScanner`, `EnvironmentScanner`, `AssignmentScanner`, `ConditionalScanner`, `DeferredScanner`
  - Conditionals and alternative evaluation (`_conditionals`, `_active_branches`)
  - Branch token replay (`_branch_replays`)
  - Lexical failure checkpoints for lint recovery (`_lexical_failure`)
* **Calibrated Next Step:**
  Do **not** perform an enterprise OOP rewrite. When reading extensions (such as bounded `\let` capture) are added, extract private handler methods (`_handle_assignment`, `_handle_conditional`) to prevent the primary method from exceeding mental chunk limits.

#### 2. `PreparationSession` (858 LOC)
* **Location:** [`session.py:L64-125`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L64-L125)
* **The Diagnosis:**
  Batch 5B made massive progress: helper functions no longer reach inside `session` to mutate private collections. However, `PreparationSession` itself remains an 858-line coordinator housing:
  - Input frame stack and replacement tracking
  - Emitted `SourcePiece` assembly and synthetic separator injection
  - Document coverage mapping (`self.coverage`)
  - Package option state (`loaded_packages`, `package_options`, `forwarded_options`)
* **Calibrated Next Step:**
  Now that helpers operate on plain data, the session's internal state can naturally decompose:
  - *Extract Option Store:* Group `loaded_packages`, `package_options`, and `forwarded_options` into a dedicated `PackageOptionStore`.
  - *Extract Emission Stream:* Group `pieces`, `tombstones`, and separator injection into an `EmissionStream` or `PieceAccumulator`.

---

### B. Residual Micro-Tax: Synthetic Separator Sprawl

* **Location:** [`session.py:L668-671`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L668-L671)
* **The Code:**
  ```python
  # No-argument commands need a lexical separator after a control word.
  if (not command.arguments and action in {"opaque", "biblatex_print", "reading_noop", "process_options"}
          or action == "boolean_declaration" and command.metadata["unbraced"]
          or action == "conditional_test" and command.metadata["trailing_control_word"]):
      self.emit(command.span.basis.span(command.span.end, command.span.end), " ", operation="SYNTHETIC_SEPARATOR")
  ```
* **The Diagnosis:**
  A classic post-turn compound conditional: each time an agent added an action family (`opaque`, `boolean_declaration`, `conditional_test`), another `or` clause was bolted onto the emission check.
* **Calibrated Treat:**
  Extract a query method `command.requires_synthetic_separator()` on `SourceCommand` or formalize the property declaratively in the binding grammar.

---

### C. Beck's Precedence Applied: What to Protect Against Lobotomy

1. **Protect [`checked_character_deletion`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/lint.py#L63-L93) in `lint.py`:**
   Contains 30 lines of detailed token and character boundary checks. It is a formal proof ensuring that dropping an invalid character between alphanumerics reproduces TeX's exact mouth state. **Never simplify this into a regex.**
2. **Protect [`context.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/context.py) Scoped Journals:**
   Three journal stacks map 1-to-1 to TeX's distinct lexical namespaces. Beck's Rule #2 (*Understandable*) trumps Rule #3 (*DRY*).
3. **Protect Catalog Command Indexing in [`catalog.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/bindings/catalog.py):**
   Batch 4 indexed declarations by name. This protects runtime resolution from quadratic scans as the binding portfolio expands.

---

## 4. Architectural Guidance for Upcoming Increments

Astra’s handoff ([`astra-cleanup-handoff.md`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/issues/astra-cleanup-handoff.md)) outlines the next technical milestones:
1. **Bounded `\let` capture and scoped meaning assignment** (to resolve `natbib.sty:210`).
2. **Structured dependency observation beyond reading barriers** (to observe `\InputIfFileExists{natbib.cfg}`).

### The Essential Guardrail for `\let` Capture:
* **The Trap:** Attempting to implement general macro expansion or register arithmetic during `\let`.
* **The Clean Boundary:** Treat `\let\dst=\src` strictly as an **alias assignment within `ReaderContext`**. If `\src` is an established reading command (e.g. `\iffalse`), copy the meaning reference to `\dst`. If `\src` is unknown/stored, copy the unknown reference. **Do not execute macro bodies or evaluate TeX expansion.**
