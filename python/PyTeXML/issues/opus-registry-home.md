# registry for code vs data and how to do the split

The split is mostly already there. It's just missing one layer.

**What already exists:**
- **The operation catalog** (`build_catalog`) maps each operation identity to its handler. That's code.
- **`COMMON_PRIMITIVES` and `EXTENSIONS`** map each spelling to an operation plus an operand. That's code too, and it should stay code. Its operands are typed values (`ConditionalRule(...)`, `DefinitionSpec(...)`). In YAML you'd need a small constructor language for them, which is the same road the old bindings went down. Your inspectability argument applies most strongly here. A mistake in this mapping changes behaviour, so you want go-to-definition, the type checks that run on import, and the handler one click away.
- **Profile YAML** chooses among those code entries by key (`extensions: [expanded, pdfoutput]`). Data that names code is a good pattern.

**What's missing** is the inventory: which names exist in which engine release, and where each comes from. That's a different kind of thing. It isn't behaviour; it's facts about upstream sources. You'd want to diff it when pdfTeX or l3kernel changes, and ideally extract it rather than write it by hand. Every primitive is created by a `primitive("…")` call in `tex.web`, `etex.ch` or `pdftex.web`, so an extracted inventory gets its provenance for free.

So here's the criterion I'd offer in place of "data versus code" in general:
- **Code** for anything that carries behaviour or typed structure.
- **Data** for facts that come from outside and get regenerated. If the inventory ends up hand-maintained instead, a Python `frozenset` with source comments is just as good, and keeps everything in one inspectable language.

**Validation where the two meet:**
- Every inventoried name with no code entry automatically becomes present-but-unsupported. The loader creates the unsupported meaning and keeps the primitive's identity, so `\ifx` and `\meaning` stay exact (finding 4). `globaldefs` would then need no hand-written entry.
- Every code entry has to appear in at least one inventory, which catches typos and invented primitives.
- Absence becomes the complement of the selected inventories rather than a list (finding 3). The format layer would still be added on top later.

One open question is whether the inventory should be extracted now or hand-written until the bootstrap needs it. Given your no-scaffolding rule, I'd write by hand only the families slice 1 actually touches. Extraction can wait until the widened default needs the full e-TeX and utility set.

---

That's a fair reason to do it now. With agents, a precedent isn't neutral. If the inventory stays a hand-grown Python dict, the next agent adds a name to the dict. An `absent:` list just gets longer. Each copy makes the pattern harder to remove. Your no-scaffolding rule is about not building ahead of understanding. A wrong pattern that agents keep repeating is a different risk, and here it argues for doing the split now. The question is whether the abstraction is clear enough, and I think most of it is.

**Three registries, three questions:**
- **Inventory: what exists.** Data covering which names each upstream source defines at a given release, with provenance. Ideally it's extracted from the `primitive("…")` calls, not written by hand. A partial hand-written inventory is itself the pattern you're worried about: "add the name when you need it" is exactly the brief's "unlabelled collection of whichever operations happened to be needed".
- **Operation registry: what it does.** Code: spelling → `PrimitiveMeaning(operation, operand)`, with typed operands, plus the catalog of handlers. This is what's in `profiles.py` today. Two spellings can share one operation (`\pdfstrcmp` and `\strcmp`). If a spelling ever behaves differently between engines, it gets an entry qualified by component then, not before.
- **Profile: what's selected.** Data choosing inventory components and extensions, plus initial configuration and the oracle. That's the YAML you have now.

Resolution joins the three and checks them:
- A selected name with no code entry becomes present-but-unsupported automatically.
- A code entry that's in no inventory is an error.
- Absence is the complement of the selected inventories.

**Some current rules get simpler under this model,** which suggests the model is right:
- `globaldefs` no longer needs a hand-written unsupported entry.
- The `absent:` list goes away.
- The capture rule ("requires an explicitly absent integer parameter") becomes "a name that's in a known inventory but not in the selected one". That's just what "foreign setup" means.

**Stopping the wrong pattern from spreading** doesn't take much. Two things:
- The validation fails loudly. Adding a primitive to code without inventory evidence breaks at import.
- One sentence in the module docstring states the criterion: code for behaviour and typed structure, data for upstream facts and selections.

Agents copy whatever is easiest to extend, so the correct extension has to be the easy one.

**The part that's still unclear** is the inventory's unit. My suggestion is one upstream source at a pinned release (`tex.web`, `etex.ch`, `pdftex.web`). Curated subsets, like the widened default's utility set, would be selections in the profile, not inventories of their own. That keeps the inventory to pure facts and leaves the still-moving composition question in the file that's cheap to change. Does that match how you're picturing it, or do you see the widened default's utility set as a component in its own right?

Agreed. This also answers the question about what the inventory's unit should be. If the inventory is parsed, its unit is whatever the parser reads, and that turns out to be a bit more than "one WEB file".

**A built engine is several sources.** pdfTeX in TeX Live is `pdftex.web` plus web2c's change files, and some primitives come only from those, such as `\synctex` (synctex's change file) and MLTeX's `\charsubdef`. e-TeX itself is a change file applied to `tex.web`. So the natural unit is one source at a pinned release, and an engine is an ordered list of them. That ordered list is a selection, so it belongs in the profile, which keeps the inventory to plain facts. LuaTeX needs a different extractor, because its primitives are defined in C tables, not by `primitive(...)` calls. That can wait until the LuaTeX profile does.

**Parsing gives you more than names.** Each `primitive("name", cmd, chr)` call carries TeX's own command class:
- **Expandability:** a command class above `max_command` is expandable. That's what `ExecutableOperation.unexpandable` currently tracks by hand, and getting it wrong by hand is how the `\let`-inside-`\edef` bug happened.
- **Operation family:** `assign_int` with `pdf_output_code` says "integer parameter" mechanically. That's the exact fact the capture rule needs for "a foreign integer parameter".
- **Validation:** the code registry's operation family and expandability must agree with the upstream command class. That catches a whole kind of mistake when the module is imported.

**"Only when things change"** fits a store you generate and commit, rather than parsing when the module is imported:
- **The record:** one line per primitive, with its source, release, command class and code, and provenance (file and WEB section).
- **The receipt:** the hashes of the source files and the extractor's version.
- **Staleness check:** a test that fails if the pinned source hashes no longer match the receipt, so drift breaks a test without the extractor running every time.
- **Review:** when a pin changes, the diff shows exactly which primitives appeared or disappeared.
- **Exposure:** a native binary checks each name it's expected to have, which is the brief's "probe actual exposure". The parse covers the full set of names; the binary confirms which ones it actually exposes.

**One dependency:** the WEB sources and change files need vendoring and pinning, so the extractor depends on the vendoring brief's acquisition and receipt work. A lighter route would be to read them from a TeX Live source checkout at a recorded revision for now.

I don't know the details of your codex-scientiae stores. Do they already follow this shape (an extractor, a committed JSONL file, a receipt with source hashes, and a staleness check)? If so, that's a good precedent to point agents at, rather than inventing a second convention.

---
