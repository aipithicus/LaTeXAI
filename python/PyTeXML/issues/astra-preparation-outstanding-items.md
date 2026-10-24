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
