The brief's core distinctions are right, and they match the code at 9e46619:
- presence, implementation and current meaning are separate questions;
- a profile composes several components instead of being one switch;
- coverage claims name what they observe.

`profiles.py` already has one present-but-unsupported primitive (`globaldefs` → `execution.unsupported`), and the `\pdfoutput=1` capture matches the "read but keep undefined" option we discussed. My main concerns are three interactions with the default profile that the brief treats as separate.

## Main findings

**1. The default profile can't run a modern kernel, so §6 decides the §11 question.**
- Since 2020-02, the LaTeX format loads expl3. expl3 needs more than `\expanded`: it also needs string comparison, file and time utilities, and random numbers. §6 says this itself.
- So no current kernel release targets "e-TeX + `\expanded`". Slice 3, the pinned bootstrap, will force the default's extension set to grow into an identity the kernel recognises.
- §11 frames "which utilities join the default" as something to revisit later. In practice, choosing the bootstrap target answers it.
- My suggestion: run the first bootstrap under the pdftex profile. It's an identity the kernel supports and the engine arXiv used. That also removes the mixed-identity worry, because a complete pdfTeX identity defines `\pdfoutput` consistently.
- If you want the default to stay free of any output backend, I believe l3kernel's supported engines include Prote, which is exactly e-TeX plus the utilities expl3 needs. I'm going from memory there; check it before relying on it.

**2. Byte input is a problem for the default, not just for pdfTeX.**
- §7 lists byte input under pdfTeX, but e-TeX is also an 8-bit engine. Once the format runs, an 8-bit identity takes the `utf8.def` path, which makes the codes 128–255 active as UTF-8 byte handlers.
- With today's codepoint mouth, `é` (U+00E9 = 0xE9) is taken as the first byte of a three-byte sequence, so it swallows the next two tokens.
- This is hidden today because the format seed and bindings never run `utf8.def`. It goes live with the bootstrap, or as soon as inputenc runs as raw source.
- So slice 2 must finish before slice 3 under the default, and slice 3's gate should check that the input model matches the identity the format detects.
- There's an upside for the lexical IR: `utf8.def`'s mapping tables are lexical evidence, and source coordinates keep the original character.

**3. Whether a name is absent depends on the format, not only on the engine.**
- `absent: [pdfoutput, …]` sits in the engine profile, but `\ifdefined` sees the environment after initialization. Format and config files can define names the engine lacks; LuaLaTeX's pdfTeX compatibility names are the usual case.
- Once the inventory is complete, engine-level absence is simply "not in the inventory". The real "undefined" fact is that complement, minus what the format defines.
- Until a format is bootstrapped, the explicit list stands in for two assumptions: what the engine lacks and what the format would have defined. §3's table should say so.

## Smaller findings

**4. `\ifx` and `\meaning` can be exact for unsupported primitives.** §3 warns against inventing `\meaning` output or `\ifx` equality. For a primitive, though, `\meaning` prints its canonical name and `\ifx` compares its identity. Neither needs execution support, and these are exactly what engine probes use (`\ifx\pdfoutput\relax`). Slice 1 can make them exact for every inventoried name. The caution applies only when the current meaning itself isn't established.

**5. Interpretation needs the same capture rule.** `capture_integer_setup` applies only to preparation. In a real e-TeX run, `\pdfoutput=1` is an undefined control sequence followed by the text "=1". When the engine produces the IR, it needs the same rule (keep the line as setup residue). §5 should say so in one line.

**6. Scope and decision logs.**
- §6, the kernel bootstrap, is the biggest change in the brief: it reopens E1 and postpones bindings. It's recorded only as an entry in the L2 engine-identity log. By your convention it deserves its own decision file, and the content probably belongs in semantic-engine §6, with a pointer from this brief. §5 restates language core §§3.11–3.12.
- The bootstrap also brings lexical interception forward. Running `fontmath.ltx` as raw source turns `\DeclareMathSymbol` into bare `\mathchardef` meanings at format time. So L10/L11 and Q6 (overlay or replace) must be settled before the bootstrap reaches the math setup, not "after engine responsibilities are established".
- §8's "Reserve interfaces for these needs" is the speculative scaffolding your no-scaffolding rule rejects. I'd cut §8 down to its list of hazards plus a revisit trigger.

**7. Style.** Much of the text guards against claims nobody is making: "does not commission a page builder", "does not revive YAML bindings…", "Do not assume a native binary `.fmt`…". That dilutes the real commitments. I'd keep the guards that address a live temptation:
- no invented metrics;
- no XeTeX table derived by stripping `pdf` prefixes;
- an inventory isn't execution.

A few concrete examples, like the `é` case, would do more than the general cautions.

## Loose ends
- **Output mode has no initial value.** §2 puts output mode under initial configuration, but `pdftex.yaml` has no initial-value block; PDF appears only in `oracle.output`. Since parameter cells start with no value, `\ifnum\pdfoutput>0` under pdftex is uncertain until something assigns it.
- **The inventory has no settled home.** §3's inventory record is data, but `COMMON_PRIMITIVES` is a Python dictionary in [profiles.py](python/PyTeXML/src/engine/profiles.py). Slice 1 should decide whether the mapping from names to operations moves into data.
- **Two points from the source discussion were dropped:**
  - why pdfTeX comes first (it's what most of the corpus was compiled with);
  - inverting inputenc's UTF-8 definition files to get an LICR → Unicode table, which matters directly for the lexical IR.

---

Findings 1 and 2 are really one topic.

**What widening the default involves.** expl3 finds its utilities by name: either the pdfTeX spellings (`\pdfstrcmp`, `\pdffilesize`, …) or XeTeX's (`\strcmp`, …). So widening isn't only deciding which capabilities to add. It also decides which spellings to expose, and packages draw conclusions from those spellings.
- Exposing `\pdfstrcmp` without `\pdftexversion` is a smaller version of the mixed identity we discussed with `\pdfoutput`.
- It's probably milder, though. Utility names are mostly checked by feature tests ("is there a string compare?"). Engine identity tests look at `\pdftexversion`, `\XeTeXversion` and so on.
- If I remember correctly, Prote made exactly this choice: pdfTeX-spelled utilities without being pdfTeX. That's why it's worth checking as a precedent and a possible inventory source.
- Widening also keeps the output backend out, which fits the `\pdfoutput` capture you just implemented.
- The cost is that no installed engine matches the default exactly. Qualification stays capability-scoped, which it already is.

**Why input comes up immediately.** Any e-TeX-family default is 8-bit. Once the format runs on it, LaTeX takes its `utf8.def` path, and that path conflicts with today's codepoint mouth. I see three ways through:
- **A byte mouth.** This is faithful to the engine. Source coordinates still give you the original character, so the IR loses nothing. You also get `\DeclareUnicodeCharacter` behaving the way authors relied on.
- **Keep codepoints and never run `utf8.def`/inputenc as raw source.** This is a deliberate deviation. It's simpler now, but it carves holes in the bootstrap, and author code that sets catcodes 128–255 gets incoherent results.
- **Make the default Unicode-native.** This pulls it toward XeTeX, which works against widening an e-TeX identity.

**My lean.** The codepoint mouth is tempting for the lexical IR, because it hands you Unicode directly. But the byte route gives the same Unicode back through source coordinates and `utf8.def`'s mapping tables. So the IR's appetite for Unicode doesn't have to decide the input model, and I'd lean toward the byte mouth.

What's your read? On widening in particular, does the spelling question change how it looks to you?
