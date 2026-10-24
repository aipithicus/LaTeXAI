# PyTeXML Refactoring & Architectural Shape Audit

## 1. Executive Summary: The Shape Gate vs. The Test Trap

The PyTeXML codebase has an exceptionally sound mathematical core in [`tex_reader.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/tex_reader.py), and **all 35 test suites pass**.

However, evaluating PyTeXML through the synthesized lenses of **Facehugger Seam Gates**, **Beck’s Precedence**, and **C.U.P.I.D. Heuristics** reveals a critical architectural diagnosis:

> **The Test Trap:** Tests check behavior, but audits must check shape. PyTeXML's tests are 100% green *because* the agent progressively implemented a mini-TeX execution engine inside temporary reading seams to prevent tests from failing.

| Severity | Smell / Architectural Anti-Pattern | Primary Location | Key Indicator & Calibrated Invariant |
| :--- | :--- | :--- | :--- |
| **Critical** | **Escaped Seam (Facehugger)** | [`dispatcher.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py) (797 LOC)<br>[`session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py) (728 LOC) | Both connectors have blown past the 100 LOC seam warning and 300 LOC review threshold. A lexical router has absorbed boolean registers, macro parsing, and option execution. |
| **High** | **Accumulated Post-Turn Micro-Damage** | [`session.py:L545-550`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L545-L550) | Multi-turn compound `if` clauses patched across successive prompts to pass individual test cases without paying the post-turn refactoring tax. |
| **High** | **Primitive / Dict Obsession** | [`session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py), [`locations.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/locations.py), [`manifest.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/manifest.py) | Pervasive stringly-typed `dict[str, Any]` and coordinate tuples. **C.U.P.I.D. Fix:** Introduce flat, idiomatic `@dataclass(slots=True)` models. |
| **Medium** | **Feature Envy & Inappropriate Intimacy** | [`bibliography.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/bibliography.py), [`environment_scanner.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/environment_scanner.py) | Standalone function mutating 6+ session attributes; scanner reaching into private `args._nonspace()`. |
| **Low** | **Deprecation Fence Parameters** | [`pipeline.py:L13-29`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py#L13-L29) | 5 retired parameters that immediately throw `ValueError`. Verified as intentional caller fences, not forgotten dead code. |

---

## 2. C.U.P.I.D. Subsystem Scorecard

Evaluating PyTeXML against Dan North’s C.U.P.I.D. properties (*Composable, Unix “fits in my head”, Predictable, Idiomatic, Domain-based*):

| Subsystem | C.U.P.I.D. Evaluation | Verdict |
| :--- | :--- | :--- |
| **[`tex_reader.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/tex_reader.py)** | **Gold Standard.** Fits in head (Knuth's 3 states N/M/S), strictly predictable, idiomatic Python with `@dataclass(frozen=True, slots=True)`, rich domain language (*CatCodes, ReadEvents*). | **Preserve untouched.** |
| **[`dispatcher.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py)** | **Fails Unix & Composable.** Cannot fit in one mental frame (250-line `_next_item` with 15 profile families). Coordinates the internals of 6 scanners instead of delegating. | **Decompose internally; re-cut seam.** |
| **[`session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py)** | **Fails Unix & Predictable.** 40 instance fields; owns rollback checkpoints, asset rasterization, biblio inlining, line counting, and emissions simultaneously. | **Architectural Decision Point (split plan).** |
| **[`context.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/context.py)** | **Passes Beck's Tie-Breaker.** Has 3 journal stacks (`_meaning_scopes`, `_environment_scopes`, `_capture_setting_scopes`). Explicit and readable. | **Do NOT over-DRY into a generic metaclass.** |

---

## 3. Detailed Findings & Calibrated Playbooks

### A. The Escaped Seams (Facehuggers)

#### 1. `StructuralDispatcher`: From Lexical Delimiter to Virtual Machine
* **Location:** [`dispatcher.py:L67-450`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py#L67-L450) (797 lines)
* **The Diagnosis:**
  `StructuralDispatcher` was conceived as a narrow, temporary reading seam between the lexical mouth (`TexReader`) and Phase 1 preparation. But because the downstream Phase 2 binding framework was undecided, the seam absorbed:
  - Boolean register evaluation (`\newif`, `\iftrue`, `\iffalse`)
  - Macro parameter capture and storage (`\newcommand`, `stored_definition`)
  - Key-value configuration parsing (`\lstset`)
  - Token replay through `TokenCursor`
* **The Seam Litmus Test:**
  > *"Does this code merely connect two components, or has it started making domain decisions and coordinating their internals?"*
  `dispatcher.py` sequences the internals of `LiteralScanner`, `DefinitionScanner`, `EnvironmentScanner`, and `AssignmentScanner`, and decides semantic truth.
* **Calibrated Treat (Re-cut Seam):**
  1. **Do NOT build a 10-class polymorphic hierarchy:** That replaces a bloated seam with an enterprise OOP explosion.
  2. **Decompose internally:** Break the 250-line `_next_item()` into private handler methods (`_handle_conditional`, `_handle_source_command`).
  3. **Anti-Lobotomy Invariant:** Do **not** simplify lines 201–212 (reader state verification and CatCode table identity). Those checks preserve TeX character physics.

#### 2. `PreparationSession`: The God Orchestrator
* **Location:** [`session.py:L64-115`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L64-L115) (728 lines)
* **The Diagnosis:**
  A 40-field class that acts as the container for all unresolved preparation state. It blown past the 300-line seam limit and owns asset subprocesses, bibliography parsing, and emission tracking.
* **Calibrated Treat (Surface Architectural Splits):**
  1. **Do not refactor autonomously:** Splitting this class touches the entire `src/prepare/` pipeline.
  2. **Protect Anchored Seams:** Fields like `self.manifest.reading_assumptions`, `self.manifest.candidate_dependencies`, and `self.units` are **staged architectural contracts** for downstream Phase 2 consumers. They look like bloat to an agent, but are essential scaffolding.
  3. **Present the split options:**
     - *Option 1 (Coordinators):* Extract `AssetCoordinator` and `PackageOptionStore`.
     - *Option 2 (Pipeline Separation):* Group configuration into `PreparationConfig` and emissions into `EmissionJournal`.

---

### B. Accumulated Post-Turn Micro-Damage

#### 1. Compound Conditional Sprawl: `session.py:L545-550`
* **Location:** [`session.py:L545-550`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L545-L550)
* **The Diagnosis:**
  ```python
  if (not command.arguments and action in {"opaque", "biblatex_print", "reading_noop", "process_options"}
          or action == "boolean_declaration" and command.metadata["unbraced"]
          or action == "conditional_test" and command.metadata["trailing_control_word"]):
      self._emit(command.span.basis.span(command.span.end, command.span.end), " ", operation="SYNTHETIC_SEPARATOR")
  ```
  This is classic agent micro-damage: each prompt that added a feature patched another `or` clause onto the emission check to pass a test case.
* **Calibrated Treat:**
  - **Extract Query Method:** Extract to `command.requires_synthetic_separator()` or define a declarative property on the command contract rather than growing compound boolean checks inside the traversal loop.

---

### C. Primitive Obsession (Dictionary Obsession)

#### 1. Untyped Domain Records in Manifest & Session
* **Locations:**
  - Diagnostics: [`session.py:L160-166`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L160-L166)
  - Requirements: [`session.py:L176-184`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L176-L184)
  - Dependencies: [`session.py:L254-256`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L254-L256)
  - Manifest container: [`manifest.py:L99-115`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/manifest.py#L99-L115)
* **The Diagnosis:**
  While peripheral models (`BibliographyInfo`, `PackageUsage`) use `@dataclass`, the core execution trace is managed with untyped `dict[str, Any]` and coordinate tuples `(r["source"], r["start"], r["end"])`.
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

#### 1. Scoped Journals in `context.py:L58-65`
* **Location:** [`context.py:L58-65`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/context.py#L58-L65)
* **Observation:** Three journal stacks (`_meaning_scopes`, `_environment_scopes`, `_capture_setting_scopes`) follow similar push/pop logic.
* **Beck's Tie-Breaker (`Understandability > DRY`):**
  - An agent might be tempted to build a generic `ScopedJournal[T]` abstraction.
  - **Verdict: Leave them explicit.** The code is understandable, predictable, and maps 1-to-1 to TeX's distinct lexical namespaces. Deduplicating them into a generic meta-class reduces readability.

#### 2. Deprecation Fences in `preprocess_paper`
* **Location:** [`pipeline.py:L42-45`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py#L42-L45)
* **Observation:** Parameters `execute_probe`, `drop_commands`, etc., throw `ValueError`.
* **Verdict:** These are intentional deprecation fences protecting callers from silent failures. Verify caller migration before deleting.

---

## 4. Pre-Flight Test Pinning Mandate

PyTeXML contains **35 test suites** in `tests/test_*.py`. Before commissioning any refactoring pass:
1. **Pin Green Baseline:** Run `pytest` on the targeted suite to ensure zero existing regressions.
2. **Confined Blast Radius:** Keep refactorings strictly confined to the targeted leaf method or scanner; do not perform drive-by edits across the seam.
