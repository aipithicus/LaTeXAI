The four configuration folders in [PyTeXML](file:///d:/aipithicus/LaTeXAI/python/PyTeXML) represent four distinct stages of the compilation pipeline, maintaining a strict separation between **lexical physics**, **syntactic reading**, **pipeline operations**, and **output representation**:

```
                       TeX Source Stream
                              │
                              ▼
1. profiles/mouth/ ──► Character-level reading regimes (CatCodes, regex runs, reader state)
                              │
                              ▼
2. bindings/       ──► Syntactic comprehension (Environments, commands, delimiters, roles)
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
3. policy/ (Phase 1)                4. capture/ (Phase 2)
   Operational Pipeline Intent         Downstream Representation
   • eliminate draft comments          • <ltx:verbatim font="...">
   • preserve code listings            • <ltx:listing>
   • emit clean master.tex             • emit canonical XML / AST
```

---

### 1. `bindings/` vs. `capture/`: Why Both Have YAML Files

The directory mirroring between [bindings/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/bindings/) and [capture/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/capture/) is deliberate:

| Directory | Core Question | Responsibilities | Target Consumer |
| :--- | :--- | :--- | :--- |
| [bindings/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/bindings/) | **"How is this read?"** | Catcode overrides, boundary matchers, argument arities, delimiter syntax, and span category. | [tex_reader.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/tex_reader.py) & [binding_resolver.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/binding_resolver.py) |
| [capture/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/capture/) | **"How is this represented?"** | Target XML element tags, element attributes, semantic roles in downstream IR trees. | Phase 2 XML/AST emitter (e.g. LaTeXML XML / JSON AST) |

#### Concrete Example: `verbatim`

In [bindings/engine/verbatim.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/bindings/engine/verbatim.yaml#L37-L40):
```yaml
# bindings/engine/verbatim.yaml -> Syntactic & Lexical Reading
environments:
  - name: verbatim
    family: block_verbatim
    profile: raw_block    # Points to profiles/mouth/raw_block.yaml
```
It instructs the reader to switch catcodes to `raw_block` and look for `\end{verbatim}`. It knows **nothing** about XML tags.

In [capture/engine/verbatim.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/capture/engine/verbatim.yaml#L18-L23):
```yaml
# capture/engine/verbatim.yaml -> Output Projection
projections:
  environments:
    verbatim:
      xml_element: "ltx:verbatim"
      attributes:
        font: "typewriter"
      semantic_role: "code_listing"
```
It instructs the downstream emitter to map that slice into `<ltx:verbatim font="typewriter">`.

#### Another Example: `comment.sty`
* [bindings/packages/comment.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/bindings/packages/comment.yaml#L29-L37): Teaches the reader that `\end{comment}` must be column-anchored (`^\\end\{comment\}$`) and consume trailing newlines.
* [capture/packages/comment.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/capture/packages/comment.yaml#L16-L19): Sets `xml_element: null` because comment blocks emit zero downstream XML nodes.

---

### 2. What `profiles/` Does

Located in [profiles/mouth/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/profiles/mouth/):
* **Answers**: *"What are the character-level physics of the TeX Mouth?"*
* Configures raw character categories (0–15), regex character classes (`catcode_run`), and reader parameters like `endlinechar`.
* Defines reusable, named reading regimes that bindings point to:
  * [latex_ascii.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/profiles/mouth/latex_ascii.yaml): Default LaTeX 2e ASCII baseline (`%` is 14, `\` is 0, `@` is 12).
  * [raw_block.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/profiles/mouth/raw_block.yaml): Demotes all special punctuation to CatCode 12 (Other) and keeps spaces literal for standard `verbatim`.
  * [semi_verbatim_block.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/profiles/mouth/semi_verbatim_block.yaml): For `alltt`, where `\` and `{}` remain active while punctuation is literal.
  * [discard_block.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/profiles/mouth/discard_block.yaml): For comment exclusions.

---

### 3. What `policy/` Does

Located in [policy/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/policy/):
* **Answers**: *"What should the preprocessor DO with this construct?"*
* Decouples semantic roles from operational transformations (`eliminate`, `preserve`, `strip_payload`, `unwrap`, `inline`, `route_to_sidecar`).
* Selects behavior depending on the target use-case:
  * [preflight.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/policy/preflight.yaml): For producing a clean, buildable `master.tex` (strips `%` comments, eliminates `\begin{comment}`, inlines `\input`, preserves code listings).
  * [lossless.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/policy/lossless.yaml): For fidelity checks and archival roundtripping (preserves raw comments or routes them to a sidecar).
  * [prose_extraction.yaml](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/policy/prose_extraction.yaml): For LLM/RAG text ingestion (unwraps formatting containers like `\textbf` to expose clean prose).

---

### Summary Checklist for Directory Clean-Up

| Directory | Lifecycle Phase | Keep / Refactor Recommendation |
| :--- | :---: | :--- |
| [bindings/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/bindings/) | **Phase 1** (Active) | **Keep**. Authoritative comprehension layer used by [binding_resolver.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/binding_resolver.py). |
| [profiles/mouth/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/profiles/mouth/) | **Phase 1** (Active) | **Keep**. Loaded by [mouth_profiles.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/mouth_profiles.py) to configure [tex_reader.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/tex_reader.py). |
| [policy/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/policy/) | **Phase 1** (Active) | **Keep**. Loaded by [policy_loader.py](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/src/policy_loader.py) to control rewrite/emission actions. |
| [capture/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/capture/) | **Phase 2** (Deferred) | **Keep, but isolate**. It belongs to downstream XML/AST generation. If your current focus is purely Phase 1 (`master.tex` preparation), `capture/` can sit quietly until the XML generator is connected. |
| [profiles/gullet/](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/profiles/gullet/) | **Phase 2** (Deferred) | Currently empty. Either add a 3-line `README.md` noting that macro-expansion profiles live here in Phase 2, or prune it until needed. |