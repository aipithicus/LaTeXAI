The first review points to **duplicated ownership of knowledge and state** as the main source of future debt. Several behaviors already have good implementations, but callers repeatedly reconstruct their rules, record shapes, or lifecycle transitions.

I would organize the cleanup around these findings.

1. **Manifest records need one lifecycle owner.**

   Requirements, diagnostics, dependencies, and resources are dictionaries assembled and modified across several modules. Their shared fields—unit identity, activity, source coordinates, final locations—are repeatedly spelled out.

   This has already produced a concrete defect: [location finalization](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/locations.py:149) populates collections that [publication failure handling](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py:102) does not clear. An in-memory check confirmed that dependencies, candidate dependencies, resources, and source metadata can retain `mapped` locations after failure.

   Start by centralizing those transitions. Then introduce typed records where they enforce meaningful invariants, preserving the emitted JSON contract. There is no need to turn every dictionary into a class.

2. **The resource boundary should finish interpreting configuration before ordinary reading begins.**

   The catalog validates raw dictionaries, but the resolver repeatedly interprets their shapes and constructs effective profiles. Some YAML fields also imply control they do not exercise: `default_profile`, `profile_override`, and `unsupported_options_behavior` occur in bindings but have no runtime consumers. Meanwhile, [the resolver selects profile labels itself](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/bindings/resolver.py:348).

   We should inventory fields as executable configuration, descriptive metadata, or obsolete declarations. Executable fields must have a validated effect; misleading fields should be removed or clarified.

   This supports a clean division: **resources declare package facts and select behaviors; Python implements the reusable algorithms.** It does not require settling the eventual full binding language.

3. **Shared reader operations should be explicit interfaces.**

   Scanners currently call other scanners’ private methods, and preparation helpers reach into dispatcher internals. Also, [ReadingKnowledge](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/contracts.py:126) omits `source_command_syntax`, although callers discover it through `getattr`.

   These are indications that useful interfaces have emerged without being formalized. Define the small shared operations deliberately, including their cursor and state guarantees. Initialize state such as `_lexical_failure` explicitly.

   Execution routing should remain in the structural dispatcher. Making interfaces explicit should clarify that ownership.

4. **Preparation’s file boundaries are ahead of its ownership boundaries.**

   Helpers have been extracted into separate modules, but many still receive the entire session and manipulate its private observations, emissions, readers, and payload edits. [Deferred preparation](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/deferred.py:13) illustrates this.

   The useful next step is to identify the operations those helpers actually require: register an observation, emit a piece, record an omission, resolve a resource. Give those operations clear owners and arguments.

   Simply splitting the remaining large methods into more files would preserve the coupling. Conversely, introducing a service class for every branch would add machinery without resolving it.

5. **There are straightforward opportunities to remove code and improve legibility.**

   Concrete examples:

   - [`_merge`](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/bindings/resolver.py:18) and [`overlay`](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/mouth_profiles.py:11) implement the same recursive copying operation.
   - Policy defaults are repeated in dataclasses and again in the loader. Validated construction can use the dataclass defaults directly.
   - Implicit figures use mutable positional records such as `[command, False]`; a small named record would make updates intelligible.
   - [Separator emission](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/session.py:623) depends on an expanding list of command actions. First isolate and name the current rule; subsequently express the lexical boundary requirement directly.
   - The current [legacy line-ledger builder](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/provenance.py:118) has no callers in the active implementation or tests. Its removal can be considered separately from retaining the ability to inspect historical artifacts. The restored prototype has its own copy.

   These are opportunities for fewer lines through removing duplication and obsolete pathways. Other worthwhile changes, such as named records, may add lines while reducing complexity.

6. **The public preparation boundary and internal builder duplicate responsibilities.**

   [The pipeline](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/prepare/pipeline.py:17) repeats argument lists, path checks, and output handling between its wrapper and internal function. It forwards arguments using `dict(locals())`, while carrying legacy options that are always rejected.

   Validate the public request once, pass an explicit internal configuration, and let the internal builder operate on the supplied staging destination. Keep transaction ownership in the outer layer. This can simplify the code without changing supported behavior or error handling.

7. **Catalog lookup is a sensible efficiency target, after ownership is clear.**

   [Command resolution](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/bindings/resolver.py:143) repeatedly scans declarations; missing-command and inactive-provider lookup perform additional scans. Indexing declarations by name would avoid repeated work as the binding portfolio grows.

   Preserve activation precedence, shadowing, and provider ambiguity. Cache static declarations separately from occurrence-dependent options. Also, `frozen=True` does not make nested dictionaries immutable, so sharing cached profiles requires an explicit ownership decision.

   This is a source-observed opportunity, not a measured performance claim.

The cleanup sequence I recommend is:

| Batch | Scope | Check before continuing |
|---|---|---|
| 1 | Fix incomplete failure-location reset; centralize record traversal | Failure manifests contain no unpublished artifact addresses |
| 2 | Consolidate duplicate helpers/defaults; name positional state; formalize existing scanner APIs | Existing reader, scope, and emission behavior remains unchanged |
| 3 | Consolidate manifest record construction and transitions | IDs, activity, locations, and JSON contracts remain consistent |
| 4 | Reconcile YAML controls with consumers; compile/index current reading declarations | Configuration changes affect behavior as declared; precedence remains correct |
| 5 | Simplify pipeline/session interfaces | Multi-file preparation, rollback, cached reads, and specimen outputs remain equivalent |

Several existing boundaries are worth retaining: `reading` does not import `prepare`; source caching separates shared text from occurrence-specific readers; edit-aware spans already provide reusable machinery; and the logger’s sink/context/event primitives are independent of preparation. Downstream work can build on those foundations.

For these batches, use focused tests for each changed contract, followed by the full suite and specimen comparisons at the integration checkpoints. No source or configuration files were changed during this review, and I did not rerun the suite. Your audit-document move remains untouched.