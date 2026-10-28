I've reviewed both notes, and now I'll outline each module's classes and functions with the first docstring line—giving a sense of the reader's structure without loading all 280 KB of source.

I've reviewed the reader's contracts, context, and the dispatcher's main loop. Next, I'll check how preparation uses the dispatcher's output and what binding knowledge the reader relies on before writing the consolidation.

Here's what the reader turns out to be, and how I'd fold the engine into it.

## The reader is already half an engine

| TeX engine part | Reader today |
| --- | --- |
| Mouth | `TexReader`: complete, sharing its catcode table with the context |
| Meaning table with TeX scoping | `ReaderContext`: a journal of changes per group, plus invalidation that respects `\global` |
| Input stack | Three separate mechanisms: `_parents` (files), `TokenCursor` (captured arguments, option bodies, branch tests) and `_replays` (transparent blocks) |
| Group and conditional stacks | `_groups`, `_conditionals` |
| TeX's scanning states | `ExecutionMode`: active, argument scanning, stored definition, skipped branch (TeX's `pass_text`) |
| Primitives | A YAML `family` on each binding profile, dispatched by a roughly 360-line if-chain in `_next_item` |
| Marked unknowns | `UncertainMeaning`, `ConditionalRegion`, `DeferredRegion` with effect summaries, `ReadingBoundary`, `InputRecovery` |

**What's missing is the other half:**
- **Expansion.** `StoredDefinition` is a capture, not a compiled macro; its docstring already anticipates "a later compiler". Preparation therefore defers every use of an author macro as `stored_macro`.
- **One kind of meaning.** Today there are five special classes plus YAML lookups, and no primitive, macro or register kinds.
- **Conditionals that decide anything** beyond constants, established booleans and character comparisons.
- **Prefixes and quantities.** `\global`, `\long` and `\protected` stop reading as `assignment_prefix`, and only literal integers can be scanned.

## Proposal: one core, two drivers

The core is the mouth, input stack, meaning table, primitives and expansion. Two drivers use it.

**Driver 1, sequential (today's dispatcher).**
- It walks the document once, runs whatever establishes context, publishes context revisions and emits source-preserving items for `master.tex`.
- It uses expansion only to probe:
  1. take a checkpoint;
  2. run the expansion;
  3. keep the result only if every lookup was established;
  4. otherwise roll back and defer as it does today, keeping today's estimated effects.
- So the reader's discipline (never invent a truth value) carries over unchanged; expansion is just another way to establish things. `reader.checkpoint()`, `context.copy()` and `InputRecovery` already provide the mechanics.

**Driver 2, unit evaluator.**
- It evaluates a deferred unit against its context snapshot, plus fold state, using the same core in a sandbox and recording what it reads. That's the hermetic evaluation in your Gemini notes.
- The reader already has the other pieces:
  - its deferred regions are the units;
  - effect summaries are the static closures;
  - context invalidation is the context threading.

## Changes, in order

1. **Separate the language from the knowledge.**
   - TeX-language families now in YAML become Python primitives in a registry: `stored_definition`, `meaning_assignment`, `catcode_assignment`, `parameter_assignment`, `assignment_prefix`, `conditional`, `conditional_factory` and grouping.
   - Kernel commands that create definitions, like `\newcommand` and `\newif`, join them as the kernel interface.
   - YAML keeps package knowledge. Source commands alone account for 76 of the 129 profiles, alongside the verbatim grammars, structural environments and package-mechanism configuration.
   - `_next_item`'s if-chain becomes dispatch through the registry, with each branch becoming a handler.
   - Gate: this is a pure refactor, so specimen output must be byte-identical.
2. **One kind of meaning:** primitive, macro, binding, register, character or unknown.
   - Today's classes map onto these directly: `StoredDefinition` becomes the macro's source, `BooleanMeaning` becomes a true/false conditional and its setter, and `UncertainMeaning` becomes unknown.
   - `\let` then copies any meaning the same way.
3. **One input stack** of file levels and token-list levels, with TeX's `back_input`, replacing the three mechanisms above.
   - **This is the one place the span model has to grow.** `TokenCursor` requires every token to sit inside one contiguous source window, but expansion output mixes body tokens (written at the definition) with argument tokens (written at the call).
   - Tokens already carry the span where they were written. A token-list level adds the call site, so an item produced by expansion is located at the call, with each token's own spelling kept.
4. **Expansion, with probe and commit.**
   - It covers macro calls, delimited parameters, `\expandafter`, `\noexpand`, `\csname`, `\string`, `\number` and `\the`.
   - Gate: whether Fractal loads `lineno` follows from running `neurips_2024.sty`'s option code.
5. **Conditionals that decide:** `\ifx` on meanings, `\ifnum`, `\if`, `\ifcat`, `\ifdefined`, `\ifcsname`. Anything undecidable falls back to `ConditionalRegion`.
6. **Quantity scanners and prefixes**, generalized from `AssignmentScanner`'s literal integers. Dimensions are delimited and kept as text, never computed.
7. **The unit evaluator.**
   - It needs copy-on-write context versions, because `context.copy()` copies whole dictionaries.
   - That's fine for preparation's occasional recovery snapshots, but too slow for one snapshot per unit.

## On your two notes

- **`engine-primitives.md`:** its line "partial expansion is exactly `\edef` with the lexicon treated as `\protected`" is the most precise definition of where expansion stops that we have; I'd adopt it in engine brief §7. Its suggestion to reuse LaTeXML's `Base_ParameterTypes` as the vocabulary of argument types also fits §7.
- **`gemini-engine-primitives.md`:**
  - Its staged model (slicing, context threading, closures, hermetic evaluation) is driver 2 plus what the reader already does.
  - Its loop sketch is the core.
  - Two parts are superseded: running package code makes its "classify package patches statically" unnecessary (engine brief §5), and engine brief §6 covers kernel internals.

Want me to write this into the engine brief as a section on consolidating the reader, replacing its §13 sequence with these seven steps?


