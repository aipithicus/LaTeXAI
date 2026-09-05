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

The resident library, when it exists, is a directory of individually vendored package sources with per-package provenance, added to the default search path. It replaces `kpsewhich` as the fallback. There is no bundle: each source is a row, so coverage stays itemized.

## 3. File requirements

A binding file:

1. Keeps upstream's header block shape and states, in the header comment, the package version and date emulated and what the binding was written from (the package documentation, a vendored source at a given path, or a `texscan` stub).
2. Declares `package LaTeXML::Package::Pool;` with `use strict; use warnings; use LaTeXML::Package;`.
3. Uses `RequirePackage` for what it depends on; a binding that needs `amsmath` says so rather than assuming the document loaded it.
4. Models new structural output on an existing binding and names the model in the header (`amscd.sty.ltxml` for diagrams, the AMS matrix family for arrays, `float.sty.ltxml` for floats).
5. Leaves a construct it does not implement **undefined**, so it surfaces as an error and as residue in the IR, rather than gobbling it silently. A construct may be defined as a no-op only when its absence does not change what the source means, and the comment says why. Furniture that is meaning-bearing to a reader (`\mathbf` against `\boldsymbol`, `\mathrm` around a unit or operator name, blackboard bold, thin spaces in math, `\left`/`\right` sizing) keeps a trace the IR retains, so the decision moves to the consumer. In doubt, keep the trace: a spurious attribute costs nothing, a dropped notational distinction costs the fidelity the engine exists for.
6. Ends with `1;`.

## 4. Definition of done

A binding is done when all of the following hold. None is a follow-up.

- The file meets section 3.
- A suite `t/<pkg>/` with a strict driver `t/8N_<pkg>.t` exists; its cases load the package and its constructs' dependencies, and between them exercise every construct the header claims, including the deliberately dropped ones.
- Every case has a golden written by `lgold`, with capture off, from a conversion that reported no errors, and read by a person before being committed.
- `ltst t/8N_<pkg>.t` passes, and so do the drivers for any layer the binding touched.
- A minimal document digested with `--capture` shows every `ltx:Math` the binding produces with `capture:provenance="source"` or a documented reason it is `callsite-only`.
- The emitted XML for the fixture appears in the commit message or the completion report.
- The manifest row for the package is updated.
- No parse that succeeds only by falling back to `parse_kludge` is counted as success.

## 5. Replacing an existing passthrough

Most packages a native binding is minted for already have a file: either a pure passthrough (`InputDefinitions('<pkg>', type => 'sty', noltxml => 1);` and nothing else) or a hybrid that wraps the raw package. The replacement is a deletion and a rewrite, not a layering.

**Before touching the file:**

1. Record the category the manifest currently assigns and what the file does. If it is hybrid, list every override it carries; each one is a claim about the raw package that the native binding must either honour or consciously drop.
2. Digest the intended fixture against the existing file and keep the output as `temp/bindings/<pkg>/before.xml`. On a machine without a TeX distribution or a resident copy of the source, the passthrough produces `route="missing"` and no definitions; that is still the baseline and it is the reason the replacement exists.
3. Note whether any other binding depends on the raw package being executed. `tikz-cd` is the precedent: upstream's stub delegated to the `tikz` hybrid, and the native binding severed that dependency entirely, so a document loading `tikz-cd` no longer pulls in TikZ. State the severed dependency in the header.

**In the replacement:**

4. Remove the `InputDefinitions` call. There is no dual path and no fallback to the raw package inside a native binding. If some part of the package genuinely must run as raw TeX, the binding is **hybrid**, is declared as such in the manifest, and the raw source lives in the resident library.
5. Keep the filename. Keep the header block and rewrite its content per section 3, naming the passthrough that was replaced.
6. Every control sequence the raw package defined and a document is likely to use is accounted for: implemented, defined as a no-op with a comment, or left undefined on purpose so it surfaces. Do not add a blanket gobbler that swallows unknown commands.
7. Other bindings that referenced the old behaviour by name (a `Let` of an original macro, an `IsDefined` guard) are updated in the same commit.

**After:**

8. Digest the fixture again to `temp/bindings/<pkg>/after.xml`, diff against `before.xml`, and confirm the diff is exactly the structure the binding intends to add and nothing it intends to keep has vanished.
9. The ledger route for the package flips from `raw` or `missing` to `binding`. The capture suite may assert this; the binding fixture does not.
10. Commit as `feat(Package): native binding for <pkg>, replacing passthrough`, with the fixture and the manifest row in the same commit. Nothing about the old passthrough survives as a compatibility shim.

A replacement that cannot satisfy step 6 without executing the raw package is not ready to be native. Leave the passthrough, file the gap, and mint the binding when the resident library holds the source.

## 6. Contribution

A native binding that meets sections 1 and 3 is a candidate for upstream. Contribution happens by porting the file and its fixture into a separate LaTeXML fork, never from this repository. Hybrid bindings and anything depending on a LaTeXAI engine change are not candidates.
