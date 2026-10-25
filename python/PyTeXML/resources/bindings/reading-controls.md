# Reading controls and retained knowledge

Batch 4 audit, 2026-10-24. This describes the current preparation reader, not a
final schema for expansion, XML construction, or asynchronous workers.

## Design anchors checked

- [Declarative bindings brief](../../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-declarative-bindings.md),
  sections 5.1–5.3 and 6: authored knowledge, compiled catalog, and document state
  have separate owners; operational fields need consumers; known source behavior
  must remain distinguishable from implemented support.
- [Source span brief](../../../../../aipithicus-issues/LaTeXAI/briefs/source-span-engine.md),
  section 4.1: compile resource knowledge once; profiles supply reading regimes,
  bindings supply construct grammar and option selection, and document registries
  supply activation and local declarations.
- [Earlier resource reconnaissance](../../issues/gemini-bindings-policy-profiles-etc.md):
  reading and later capture/projection were deliberately separated. Its proposed
  XML conventions are provisional, not a requirement on PyTeXML output.
- [Binding ontology brief](../../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-binding-ontology.md),
  section 3.8: the eventual authoring surface is reopened. Improving the current
  YAML consumer does not settle that choice.

No Phase 2 knowledge was deleted in this audit. The three previously inert option
fields are retained with the bounded contracts below. Repeated `profile: raw_block`
entries in fancyvrb/listings environments now use their binding's default.

## Current controls

| Authored field | Consumer and contract |
| --- | --- |
| `option_resolution.default_profile` | Catalog literal compilation uses it when the construct has no explicit `profile`. Explicit inline profiles still win. Missing or nonliteral profiles fail at load time. |
| `reading_affecting_keys.*.effect` | Resolver implements the supported character/delimiter/boolean operations. Unknown effect names are configuration errors, not deferred source interpretation. |
| `reading_affecting_keys.*.profile_override` | An enabled, resolved option selects additional mouth layers and their category/family. The option's concrete catcode assignments follow those layers. Disabled options (`none`, empty escapes, false math escape) select nothing. |
| `unsupported_options_behavior` | Validated invariant: only `report_unresolved` is supported. It is not an ignore/fallback switch. Unknown source options return an unresolved result. |
| `unsupported_action: report_unresolved` | An explicit support boundary for a known effect, including dynamic `codes`/`codes*` assignments. Preparation retains the source and reports remaining work. |
| `non_reading_options` | Values are copied as occurrence metadata; no formatting or language-driver execution is implied. Names cannot overlap reading keys. |
| `configuration` | Configuration state and dispatcher consume namespaces, scopes, exclusive keys, style references, and defaults. These are document-local recipes, not shared catalog mutations. |
| `metadata.effect_summary`, `reading.load_effects.summary` | Validated immutable write bounds; the dispatcher selectively invalidates complete supported effects. Missing/incomplete summaries retain conservative invalidation. See [effect summaries](effect-summaries.md). |
| `requires_unshadowed`, `meaning_copies` | Declared effects require the assumed meanings to remain established and install only their explicitly declared local copies. A complete summary must cover those copies. |
| `lexical_mode.character_classes`, `catcode_overrides`, `reader_parameters` | Compiled character layers and `ReaderContext`; regex membership and immediate assignments govern reading. Baseline `lexical_mode.default` initializes the category table. |
| `grammar`, `scope`, actions, conditional roles and predicates | Validated reading declarations selected by the dispatcher and its scanners; supported grammar remains bounded and non-expanding. |
| `terminator`, `terminator_pattern` | Compiled literal template and selected scanner. Physical-line handlers use the regex; token-sequence handlers require the appropriate exact-token contract. Exact and regex fields are not deduplicated. |
| `span_classification` | Literal templates and option profile selection produce reading categories and semantic roles; preparation policy separately controls emission. |

Literal composition order is base profile (including inherited layers), binding,
construct, enabled option profiles in **binding declaration order**, then concrete
option catcodes. Repeated selected profiles are applied once. The last selected
profile supplies the category/family. Existing rejection of combined interpolation
modes remains in force. Option profiles overlay lexical parameters and retained
mechanics/capture metadata; they do not replace the construct's argument grammar,
terminator, or semantic role.

This additive rule matters for `commandchars=![]`: the base raw profile keeps
backslash and braces ordinary, while only `![]` gain command/group categories.
Selecting the semi-verbatim profile must not implicitly restore the usual TeX
delimiters. A profile selection is reading data, not evidence that the dispatcher
implements every interpretation behavior associated with that profile.

## Descriptive and deferred fields

The following status labels are documentation, not new executable YAML switches.
Changing descriptive fields alone does not change tokenization. Deferred facts
remain in the resources and, where already carried, the resolved records.

| Fields / knowledge | Status and boundary |
| --- | --- |
| Option-rule `syntax` | `descriptive`: human-readable notation. The named effect's bounded parser is authoritative; this is not an executable signature language. |
| Profile `family`, `comment_char`, `escape_char`, `group_delimiters` | `descriptive`: summaries of a regime. Actual categories come from lexical layers and option assignments. The resolved family is the selected profile identity. |
| Profile `has_star_variant`, `interpolations_allowed`, `interpolation_mode` | `descriptive`: capability summaries. Binding grammar supplies actual star handling; resolved interpolation rules supply actual delimiter plans. |
| `preserve_whitespace`, `source_capture.preserve_raw_slice`, `preserve_indentation` | `descriptive_invariant`: literal capture retains authored source and indentation. These are not permission to normalize a literal region. Emission policy is separate. |
| `tex_mechanics.trailing_spaces_stripped_by_input_ln` | `descriptive_invariant`: the mouth's physical-line algorithm does this independently of a flag. Raw source slices remain available. |
| Literal `tex_mechanics.active_endlinechar_obeylines`, `active_space_obeyspaces`, `first_paragraph_suppressed`; alltt `obey_lines`, `active_space` | `deferred_phase2`: active-token meanings, paragraph construction, and layout interpretation. Preparation captures source and categories; it does not execute these semantics or delete a first newline. |
| Formatting values retained through `non_reading_options` | `deferred_phase2`: later interpretation/projection may use them. Current acceptance does not establish package language-driver or typography support. |
| Remaining unimplemented factory sketches and dynamic code effects | `deferred_phase2`: retained package knowledge with explicit unresolved runtime results, not empty successful profiles. Future bounded support may move a particular operation earlier. |
| Experimental capture/projection resources | `deferred_phase2`: retained separately under `resources/experimental`; neither executable preparation controls nor the settled XML schema. |

`EffectiveReadingProfile.tex_mechanics` also carries currently consumed command
metadata (for example definition and option recipes). The deferred status above
applies to the listed **literal mechanics**, not to that entire Python field.

## Catalog ownership and indexes

Catalog loading validates resources, snapshots reading declarations, indexes
commands/environments by name and provider, indexes group actions by category,
and composes static literal templates. Occurrence resolution performs no YAML I/O,
rebuilding of static literal defaults, or declaration-list scan. Lookup still walks the document's
activation order; no speedup claim depends on a timing benchmark.

Precedence remains later first-time package activation, then engine load order;
within one provider, override/command section order is unchanged. A nonconditional
command can shadow a conditional. Inactive syntax inspection retains *all* package
declarations for a name, so multiple providers or duplicate meanings across
sections remain ambiguous. It never activates a provider.

The catalog owns nested declaration/template dictionaries and treats them as
read-only; frozen records alone do not freeze nested objects. Resolved occurrences
copy mutable metadata and share only immutable lexical/terminator records. Raw
loaded resources are inspection data, not a hot-reload API. Tests that alter an
authored declaration serialize and reload it before resolution, exercising the
same validation and indexing boundary as production.
