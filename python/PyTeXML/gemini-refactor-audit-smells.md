# PyTeXML Refactoring & Architectural Smell Audit

## 1. Executive Summary & Anti-Pattern Hotspots

The PyTeXML codebase has an exceptionally strong, mathematically sound foundation (notably [`tex_reader.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/tex_reader.py)), but under pressure from rapid development it has accumulated several classic **Agent Anti-Patterns**. 

Applying the synthesized **Refactor + Karpathy Guardrails** ensures we target *accidental complexity* without lobotomizing in-flight, essential domain physics.

| Severity | Smell Category | Primary Location | Key Indicator & Karpathian Guardrail |
| :--- | :--- | :--- | :--- |
| **High** | **Long Method / Switch Statements** | [`dispatcher.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py#L198-L450) (`_next_item`) | 250+ line cascading `if/elif` ladder. **Guardrail:** Decompose internally; do *not* invent a 10-class polymorphic hierarchy or truncate Knuthian CatCode checks. |
| **High** | **Large Class / Divergent Change** | [`session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L64-L115) (`PreparationSession`) | 40+ instance attributes. **Guardrail:** Treat as an *Architectural Decision Point*. Distinguish accidental sprawl from *Anchored Seams* staged for Phase 2. |
| **High** | **Primitive Obsession (Dict Obsession)** | [`session.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py), [`locations.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/locations.py), [`manifest.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/manifest.py) | Pervasive stringly-typed `dict[str, Any]` and coordinate tuples. **Guardrail:** Introduce flat `@dataclass(slots=True)` models; avoid deep class hierarchies. |
| **Medium** | **Duplicate Code** | `src/reading/*_scanner.py` | Near-duplicate `_require()` assertion helpers re-emitted across 4+ scanner modules. Clean leaf extraction. |
| **Medium** | **Feature Envy / Inappropriate Intimacy** | [`bibliography.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/bibliography.py) | Standalone function reaching into session internals. **Guardrail:** Narrow the interface; do *not* move it back into `session.py` (which worsens the Large Class smell). |
| **Low** | **Long Parameter List & Dead Parameters** | [`pipeline.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py#L13-L29) (`preprocess_paper`) | 14 parameters, 5 of which throw `ValueError`. **Guardrail:** Check external callers first; these are active deprecation fences, not forgotten code. |

---

## 2. Detailed Findings & Calibrated Playbooks

### A. Bloaters

#### 1. Long Method & Nested Conditionals: `StructuralDispatcher._next_item()`
* **Location:** [`dispatcher.py:L198-450`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py#L198-L450)
* **Signals:** Method body exceeds 250 lines; mixed abstraction levels; 15+ cascading `if profile.family == "..."` branches.
* **Calibrated Treat:**
  1. **Decompose, Don't Truncate:** Break each `profile.family` branch into dedicated private helper methods on the dispatcher (e.g. `_handle_conditional_factory()`, `_handle_environment_definition()`, `_handle_source_command()`).
  2. **Internal Dispatch Table (Avoid Polymorphic Sprawl):** Do **not** invent an external `ProfileFamilyHandler` class hierarchy. Use an internal dictionary mapping (`_FAMILY_DISPATCH: dict[str, Callable]`) or private decomposition.
  3. **Anti-Lobotomy Invariant (Protect Essential Physics):** Do **not** simplify lines 201–212 (the reader/context state verification, scope depth, and catcode synchronization). Those checks protect Knuthian character physics; removing or shortening them breaks reader safety.

#### 2. Large Class: `PreparationSession` (Architectural Decision Point)
* **Location:** [`session.py:L64-115`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L64-L115)
* **Signals:** 40+ instance fields; multiple distinct axes of change (asset discovery, bibliography formatting, package options, source span emission).
* **Calibrated Treat:**
  1. **Do Not Refactor Autonomously:** This is the core engine of Phase 1. Splitting it carries a massive blast radius across `session.py`, `pipeline.py`, `locations.py`, and `bibliography.py`. It requires human alignment before execution.
  2. **Protect Anchored Seams:** Several fields (`self.manifest.reading_assumptions`, `self.manifest.candidate_dependencies`, `self.units`) may appear to be "speculative bloat" to a naive eye, but they are **staged architectural seams** communicating upstream reading state to downstream AST/emission consumers. They must not be pruned.
  3. **Surface Architectural Splits:** Outline clean options for the user:
     - *Option A (Functional Separation):* Extract an `AssetCoordinator` and `PackageOptionStore`.
     - *Option B (Pipeline Separation):* Group configuration into a `PreparationConfig` and emissions into an `EmissionJournal`.

#### 3. Primitive Obsession (Dictionary Obsession) & Data Clumps
* **Locations:**
  - Diagnostics & Requirements: [`session.py:L160-166, L176-184`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L160-L166)
  - Dependencies: [`session.py:L254-256`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L254-L256)
  - Occurrences: [`session.py:L142-147`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py#L142-L147)
  - Manifest container: [`manifest.py:L99-115`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/manifest.py#L99-L115)
* **Signals:** Stringly-typed dictionaries (`dict[str, Any]`) passed across boundaries, filtered by string keys (`r["source"]`, `r["start"]`), and mutated in-place.
* **Calibrated Treat:**
  1. **Flat Dataclasses (`@dataclass(slots=True)`):** Introduce simple, typed, immutable records (e.g. `RequirementRecord`, `DiagnosticRecord`, `DependencyEdge`, `InputOccurrenceRecord`).
  2. **Simplicity First:** Avoid deep class hierarchies (`BaseDiagnostic -> PrepDiagnostic -> SyntaxDiagnostic`).
  3. **Preserve Serialization:** Ensure dataclasses implement `.to_dict()` or serialize cleanly via `asdict()` to avoid breaking JSON output in `manifest.json`.

#### 4. Long Parameter List & Deprecation Traps: `preprocess_paper`
* **Location:** [`pipeline.py:L13-29, L42-45`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py#L13-L29)
* **Signals:** 14 parameters; 5 parameters (`execute_probe`, `drop_commands`, etc.) throw `ValueError` immediately.
* **Calibrated Treat:**
  1. **Verify Intent Before Deleting Seams:** Lines 42–45 explicitly raise `ValueError("Custom cleanup requires reading-aware policy contracts; regex cleanup is retired")`. This is an **intentional deprecation fence** against legacy callers from earlier regex prototypes.
  2. **Check Workspace Callers:** Check tests and external scripts before removing parameters. If external callers still pass them expecting the diagnostic, preserve the guard; only delete them if callers are migrated.
  3. **Introduce Parameter Object:** Package legitimate operational options (`output_dir`, `policy`, `convert_images_to_svg`) into a `PreparationConfig`.

---

### B. Couplers & Object-Orientation Abusers

#### 1. Feature Envy: `prepare_bibliography`
* **Location:** [`bibliography.py:L28-60`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/bibliography.py#L28-L60)
* **Signals:** Standalone function reaching into 6+ distinct attributes of `PreparationSession`.
* **Calibrated Treat:**
  1. **Do NOT Move Method Back to `PreparationSession`:** Moving 240 lines of bibliography logic back into `session.py` directly worsens the Large Class smell.
  2. **Narrow the Interface (Invert the Dependency):** Stop passing the mutable `session` God Object into `prepare_bibliography`. Change the signature to pass only explicit inputs:
     `prepare_bibliography(pieces, declarations, store_root, origin_dir, existing_bbl_path)`
     This preserves modular separation without bloating the session.

#### 2. Inappropriate Intimacy: Scanner Cross-Calls
* **Location:** [`environment_scanner.py:L44, L47`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/environment_scanner.py#L44)
* **Signals:** Cross-module private calls (`args._nonspace()`, `definitions._body()`).
* **Calibrated Treat:**
  1. **Promote to Public Interface:** If `nonspace()` and `body()` are shared scanning contracts across scanners, elevate them to intentional public methods on their respective scanner classes, or hoist `_nonspace` to `TexReader`.

---

### C. Dispensables

#### 1. Duplicate Code: Near-Duplicate `_require` Helpers
* **Locations:**
  - `dispatcher.py:L175-177`, `literal_scanner.py:L34-37`, `definition_scanner.py:L22-25`, `environment_scanner.py:L18-21`
* **Signals:** Identical assertion helpers re-emitted across 4 sibling files.
* **Calibrated Treat:**
  1. **Extract Shared Utility:** Move `require_reading(condition, reason, detail)` into [`contracts.py`](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/contracts.py) (where `require_resolved` already lives) and import it. This is a low-risk, mechanical leaf refactoring.

---

## 3. Pre-Flight Test Pinning Mandate

PyTeXML contains **35 test suites** in `tests/test_*.py`. Before initiating any refactoring pass:
1. **Pin Green Baseline:** Run `pytest` on the relevant test suite (e.g. `tests/test_structural_dispatcher.py` or `tests/test_preparation_traversal.py`) to confirm zero existing failures.
2. **Confined Blast Radius:** Do not refactor code in unverified or failing areas until a green test baseline is established.
