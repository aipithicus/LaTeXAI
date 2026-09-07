# Bindings

A binding is the file the engine loads in place of a LaTeX package or class: `lib/LaTeXML/Package/<pkg>.sty.ltxml` or `<pkg>.cls.ltxml`. This document states what a binding must be, how coverage is itemized, what counts as done, and what happens when a proper binding replaces an existing passthrough.

## 1. Dialect

Bindings are written in the upstream LaTeXML dialect and nothing else: they declare into `LaTeXML::Package::Pool`, use the `LaTeXML::Package` API (`DefMacro`, `DefConstructor`, `DefMathI`, `DefEnvironment`, `DefKeyVal`, the `\lx@gen@matrix@bindings` and `\lx@ams@matrix` family), and emit elements in the `ltx` namespace only. A binding never touches the capture namespace; the engine adds provenance around whatever the binding emits.

This is what keeps a binding mechanically conformant and therefore portable to a contribution fork. Engine changes in LaTeXAI may diverge from upstream freely; the binding-author surface is held steady on purpose.

## 2. Coverage categories

Every package the engine can be asked for falls into exactly one category. The category is declared in the coverage manifest, not inferred from the file.

| Category | Meaning | Runtime cost | Needs raw source |
| :--- | :--- | :--- | :--- |
| **native** | the binding defines the package's surface itself and executes no raw TeX | low | no |
| **hybrid** | the binding loads the raw package through `InputDefinitions` and overrides or wraps parts of it | high | yes |
| **passthrough** | the binding is only an `InputDefinitions` call; the raw package is executed unchanged | high | yes |
| **ignored** | the binding deliberately defines its constructs as no-ops because their absence does not change what the source means (page geometry, running-text font swaps, float placement); the header argues this per construct | none | no |
| **raw-only** | no binding; the raw source is interpreted from the resident library | high | yes |
| **missing** | no binding and no source; the request is recorded in the ledger as `route="missing"` | none | — |

Upstream's tree as inherited holds 414 `.sty`/`.cls` bindings, of which about 104 execute raw TeX and about 148 are near-empty. Those are the starting rows of the manifest. Until the manifest exists, the category is what the file does, and `tools/texscan --all` is the walk that reads it.

The resident library is `lib-ctan/`: individually vendored package sources with per-package provenance. It answers the engine's `kpsewhich` fallback through the texmf index rather than sitting on the search path, so bindings keep precedence over raw sources at every step ([`architecture.md`](../architecture.md) sections 5 and 8). There is no bundle: each source is a row, so coverage stays itemized. Notation vocabularies, the KaTeX reference, and parked packages live in reference roots the engine never reads.

### 2.1 Binding classes

The category says how a package is executed. The class says what the binding does to the source's meaning, and it is the bar a binding is judged against before any local convenience. A native binding declares its class in the header comment.

| Class | When | The binding must | The binding must not |
| :--- | :--- | :--- | :--- |
| **structural** | the package contributes manuscript objects: diagrams, trees, algorithm listings, theorem-like boxes, cross-references, tables with spans and rules | emit an element per object with its identity intact: the `\label` attached to that element, spans and rules as attributes, references resolvable, the number taken from the counter the package uses | flatten an object into styled text; drop a label because the container has no id; invent an element the schema lacks (a schema question goes to a discussion first) |
| **containment** | the package's value is canvas execution (TikZ, PGF) and only the discrete structure inside is worth keeping | read the body as tokens and harvest nodes, labels, and math into `ltx:picture` and `ltx:g`; leave unknown drawing macros unexpanded so they surface | execute geometry, run `\foreach`, or expand what it does not understand to nothing |
| **shim** | the package exists to stabilize loading: options, aliases, key-value plumbing, a command surface with no semantic content (`kvoptions`, `xurl`) | mirror the public surface with the real signatures and forward what the package forwards | define anything that changes what a document means |
| **ignored** | see the category above | argue per construct in the header | |

The rule across classes: **lift discrete structure, do not run the canvas.** Objecthood, labels, references, spans, arrows, rows, blocks, and theorem identity are preserved. Visual fidelity is not chased when the consumer needs semantic carriers plus evidence.

**Deferral.** Parser and IR debt is paid only when the IR demonstrably loses a distinction a consumer needs, never because an input looks incomplete. A construct whose right shape is unsettled stays as residue (`ltx_math_unparsed`, an undefined macro, an explicit error) and is recorded in a discussion note in the issues workspace; it is not smoothed over in the binding. The scalerel one-sided delimiters and the dense tikz-cd edges are the precedents.

## 3. File requirements

A binding file:

1. Keeps upstream's header block shape and states, in the header comment, the package version and date emulated and what the binding was written from (the package documentation, a vendored source at a given path, or a `texscan` stub).
2. Declares `package LaTeXML::Package::Pool;` with `use strict; use warnings; use LaTeXML::Package;`.
3. Uses `RequirePackage` for what it depends on; a binding that needs `amsmath` says so rather than assuming the document loaded it.
4. Models new structural output on an existing binding and names the model in the header (`amscd.sty.ltxml` for diagrams, the AMS matrix family for arrays, `float.sty.ltxml` for floats).
5. Leaves a construct it does not implement **undefined**, so it surfaces as an error and as residue in the IR, rather than gobbling it silently. A construct may be defined as a no-op only when its absence does not change what the source means, and the comment says why. Furniture that is meaning-bearing to a reader (`\mathbf` against `\boldsymbol`, `\mathrm` around a unit or operator name, blackboard bold, thin spaces in math, `\left`/`\right` sizing) keeps a trace the IR retains, so the decision moves to the consumer. In doubt, keep the trace: a spurious attribute costs nothing, a dropped notational distinction costs the fidelity the engine exists for. A no-op consumes the construct's real signature: a stub with the wrong arity eats the wrong tokens and leaks the rest as text, which is worse than leaving the construct undefined. Commands whose job is to define other commands (`\algdef`, `\algnewcommand`, `\SetKwProg`, `\newtcolorbox`, `\crefname`) are never no-ops: they define, or they stay undefined.
6. Is written from the vendored source, construct by construct, not from the documentation alone and never from memory. Where memory and source disagree the source wins. algorithm2e's `\tcp` is the `//` comment and `\tcc` the `/* */` one, and its `\;` is guarded in math by `\@mathsemicolon`; both shipped the other way round because they were written from memory. Package options use `DeclareOption(undef, ...)` for the wildcard handler; `DeclareOption('*', ...)` declares an option literally named `*`.
7. Ends with `1;`.

## 4. Definition of done

A binding is done when all of the following hold. None is a follow-up.

- The file meets section 3.
- An expectations list, `temp/bindings/<pkg>/expectations.md`, was written from the vendored source and the package documentation before any golden existed: per construct, a source input and the observable the IR must show. The golden is read against this list, not against the binding.
- A suite `t/<pkg>/` with a strict driver `t/8N_<pkg>.t` exists; its cases load the package and its constructs' dependencies, and between them exercise every construct the header claims, including the deliberately dropped ones, and the idioms real documents use: the forms found in the gauntlet corpus for the package appear verbatim in a case, and for a replacement so does every override the old hybrid carried.
- Every case has a golden written by `lgold`, with capture off, from a conversion that reported no errors and passed the golden lint (no dangling `labelref`, no engine-internal `\lx@` control sequence leaked into the document), and checked by a person against the expectations list before being committed.
- `ltst t/8N_<pkg>.t` passes, and so do the drivers for any layer the binding touched.
- A minimal document digested with `--capture` shows every `ltx:Math` the binding produces with `capture:provenance="source"` or a documented reason it is `callsite-only`.
- The completion report carries the emitted XML for the fixture, a claims table (one row per construct the header claims, with the fixture line that exercises it and the golden fragment that shows the observable), the census residue (what the source defines that the binding leaves undefined), and the idiom coverage. A claim without a golden fragment is not made.
- The manifest row for the package is updated.
- No parse that succeeds only by falling back to `parse_kludge` is counted as success.

A strict suite proves that the conversion was clean and that the output has not changed since the golden was written. It proves nothing about whether the golden was right. Five suites minted in September 2026 passed strict while their goldens carried a missing colspan, dangling references, math absorbed into a bold keyword, a mixed-type reference list rendered as one type, and a preamble definition leaked into the body; each golden had been read, but only against the binding's own claims.

## 5. Replacing an existing passthrough

Most packages a native binding is minted for already have a file: either a pure passthrough (`InputDefinitions('<pkg>', type => 'sty', noltxml => 1);` and nothing else) or a hybrid that wraps the raw package. The replacement is a deletion and a rewrite, not a layering.

**Before touching the file:**

1. Record the category the manifest currently assigns and what the file does. If it is hybrid, list every override it carries; each one is a claim about the raw package that the native binding must either honour or consciously drop.
2. Digest the intended fixture against the existing file and keep the output as `temp/bindings/<pkg>/before.xml`. On a machine without a TeX distribution or a resident copy of the source, the passthrough produces `route="missing"` and no definitions; that is still the baseline and it is the reason the replacement exists.
3. Note whether any other binding depends on the raw package being executed. `tikz-cd` is the precedent: upstream's stub delegated to the `tikz` hybrid, and the native binding severed that dependency entirely, so a document loading `tikz-cd` no longer pulls in TikZ. State the severed dependency in the header.

**In the replacement:**

4. Remove the `InputDefinitions` call. There is no dual path and no fallback to the raw package inside a native binding. If some part of the package genuinely must run as raw TeX, the binding is **hybrid**, is declared as such in the manifest, and the raw source lives in the resident library.
5. Keep the filename. Keep the header block and rewrite its content per section 3, naming the passthrough that was replaced.
6. Every control sequence the raw package defined and a document is likely to use is accounted for: implemented, defined as a no-op with a comment, or left undefined on purpose so it surfaces. Do not add a blanket gobbler that swallows unknown commands. The `texscan --diff` census is the checklist; what it still lists after the rewrite is the residue, and the residue is named in the header and the completion report. A hybrid replaced by a native binding that defines fewer of the package's commands than the raw source did is a regression until the residue is justified line by line.
7. Other bindings that referenced the old behaviour by name (a `Let` of an original macro, an `IsDefined` guard) are updated in the same commit.

**After:**

8. Digest the fixture again to `temp/bindings/<pkg>/after.xml`, diff against `before.xml`, and confirm the diff is exactly the structure the binding intends to add and nothing it intends to keep has vanished.
9. The ledger route for the package flips from `raw` or `missing` to `binding`. The capture suite may assert this; the binding fixture does not.
10. Commit as `feat(Package): native binding for <pkg>, replacing passthrough`, with the fixture and the manifest row in the same commit. Nothing about the old passthrough survives as a compatibility shim.

A replacement that cannot satisfy step 6 without executing the raw package is not ready to be native. Leave the passthrough, file the gap, and mint the binding when the resident library holds the source.

## 6. Contribution

A native binding that meets sections 1 and 3 is a candidate for upstream. Contribution happens by porting the file and its fixture into a separate LaTeXML fork, never from this repository. Hybrid bindings and anything depending on a LaTeXAI engine change are not candidates.
