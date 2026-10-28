Waiting makes sense. Once the engine can run package code natively, much of what bindings were meant to describe will simply execute, and whatever's left is what bindings actually need to be. A few guardrails keep that boundary from emerging somewhere messy.

**Keep package names out of the engine core.** The risk with an emergent boundary is that it shows up as scattered special cases: `if package == "natbib"` in the dispatcher, or a hand-patched kernel macro inside a primitive. Route every package-specific behavior through one narrow seam, the binding-kind meaning from L6, even if what sits behind it for now is just a Python function registered in a dict. The authoring surface can stay undecided, but the seam can't, or you'll be untangling it later.

**Record every place you wanted a binding.** Whenever the engine reaches something it shouldn't or can't execute, log it with its context. Examples:

- a floor breach
- a measurement-dependent branch whose outcomes differ in content
- typesetting machinery that's expensive to run just to discard
- a construct where you want an IR object rather than its expansion

That log is the empirical record the boundary will emerge from. It tells you what bindings must be able to express, so you're not guessing.

**Expect bindings to get much smaller.** My guess is they shrink from "describe the package" to overrides at a few specific points:

- **Content constructors:** sectioning, theorems, floats and captions, citations and references, where you want IR objects instead of the kernel's typesetting path.
- **Declarator interception:** `\DeclareMathSymbol` and its relatives, feeding the lexicon.
- **Grammar-level sinks:** TikZ paths and similar, where running the real code costs a lot only to be thrown away.
- **Shortcuts:** heavy machinery like pgfkeys, where an override is worth it purely for performance.

L6's observation contract applies to all of them. Treat this as a hypothesis to check against the log, not a plan.

**Write interim bindings so they can migrate later.** Plain Python registered through one decorator is fine for now. What keeps your options open is that each registration also produces a canonical record (name, signature, kind, evidence), as your ontology brief separated canonical form from authoring surface. Whatever authoring surface you choose later then compiles to records you already have, rather than requiring a rewrite.