Before recommending a sequence, I'll check what has landed since my last look, so I don't propose work that's already done.

I see several updates since yesterday: four new commits (geometry pinning, write-set bounding, and inlining/preservation fixes), a fifth specimen (2608.28281v2), and new planning notes in `issues/`. I'll check the latest batch's status and skim those notes so my plan builds on them instead of duplicating work.

Found another planning note, `opus-planning-interp-engine.md`, whose "Why TeX primitives are the wrong layer" section may conflict with my §7 from yesterday. I'll read it alongside the symbol notes' relation priorities and the lib-ctan survey numbers.

You've got more agreement than it might feel like, so this is mostly a sequencing question. One check first: the other session's interpretation-engine note doesn't conflict with what I put in the staged brief's §7. Its "partial expansion = `\edef` with the stop set protected" is the same idea as my binding floor. It adds two useful pieces my version didn't have: declarators as the semantic layer, and quantity scanners in the engine core.

**Where things stand.** The latest run, `20261025-contextual-inlining`, covers five specimens:
- **Complete:** Bayesian MARS and FPCA.
- **Partial:** Fractal, DeadSalmons, and the new LoopArena.

Every location and coverage check is clean, and the master files shrank slightly. The write-set increment and geometry pinning have landed. The remaining blockers in Fractal and DeadSalmons are inside local style files, and I haven't looked at LoopArena's yet.

**My recommendation: finish `master.tex` v1 before starting downstream work, and do the binding refactor only as far as a real consumer needs it.**

**Phase 1: close out preparation**
1. **Vendoring (a parallel chip, mechanical):**
   - kernel `.dtx` files: `ltclass`, `ltcounts`, `ltxref`, `ltsect`, `fontdef`
   - natbib, fancyhdr, amsmath, amsthm, amsfonts, unicode-math
   - the specimens' `.bst` files: plainnat, agsm, apalike

   Nearly everything after this needs pinned sources.
2. **R0 consumption map (a parallel chip):** map every YAML key and selector string to the code that reads it, and delete what's dead. It's cheap, the gate is byte-identical specimen output, and it de-risks everything after.
3. **Local-style identification (ontology §3.9), on the main line:** this is the first real consumer of the refactor's canonical records (step R1 in the other session's plan), so design the package-level facet here: identity, version range, options and the loads they select, write sets, fingerprints. Gate: Fractal and DeadSalmons reach complete-under-assumptions, and LoopArena's remaining blocker gets assessed.
4. **Canonical bibliography, steps 1–4,** in shadow mode and then cut over. Bibliography identification reuses that same package-level facet. All four witnesses are already in place: cases A and B each have two specimens.
5. **v1 closeout:** stable ids, and give `parent_id`'s ownership meaning its own name.

**Phase 2: the handoff and the interpretation foundation**

6. **The prepared-payload read and master index** (span §9.6, staged increments 2–3): a containment tree derived from spans, text-run leaves, the context table, and units in master coordinates.
7. **Declarator extraction over lib-ctan and lib-symb** (research, can run in parallel): it produces lexicon and table data and sizes the leftover program-like code. The survey already found 83% table-shaped rows in notation packages but only 19% in lib-ctan, so the size of that leftover is the real open question.
8. **The authoring-surface bake-off together with staged increment 5,** since their witness sets nearly match: fancyvrb, `\newtheorem`, amssymb, `\citep`. Its outcome decides the rest of the refactor (capability registry, signature strings, templates).
9. **The first relation slice plus the counter fold,** following your stated priorities: citations, theorem and section references, figures and captions. Symbol-level links stay out of scope; lexical invariance carries that load.

**Three decisions that are yours:**
- **Finish v1 first?** I'd say yes. It's close, and the bibliography change alters what `master.tex` contains, so downstream work started now would be built on a moving target.
- **Refactor up front, or driven by consumers?** I'd do R0 now, R1 scoped to the package-level facet, and the rest after the bake-off. The other session's note flagged the same doubt about doing the refactor first.
- **Chips:** vendoring and R0 can run in parallel while the main line takes §3.9. I won't dispatch anything without your go-ahead.

**Housekeeping:** the working tree has uncommitted planning documents:
- my additions to the handoff
- the modified Gemini notes
- the untracked `opus-*` notes
- the new LoopArena specimen and the edited `catalog.yaml`

A docs-only commit before the next implementation round would keep the record clean.

Should I write this sequence into the handoff, or into the `planning/00-current-work.md` ledger, and draft briefs for the two chips?