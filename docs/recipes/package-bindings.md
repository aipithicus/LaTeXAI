# Minting a binding

Executable recipe for producing a binding that meets [`docs/specification/bindings.md`](../specification/bindings.md). Commands run from the repository root through the `pwsh_exec` profile, which provides `lxml`, `lmath`, and `ltst`. Every intermediate file goes under `temp/bindings/<pkg>/`; nothing in this recipe writes to the repository root or to `lib/` until the final step.

The recipe has one entry and one exit and three tiers in between. Most bindings finish at tier 1 or 2. Tier 3 is where the work is, and it is also where the process most needs to be followed rather than improvised.

```
census ─► tier 1: mechanical stub ─► tier 2: semantic surface ─► tier 3: structural constructors ─► fixture ─► done
```

## 0. Set up

```powershell
Set-Location D:\aipithicus\LaTeXAI
New-Item -ItemType Directory -Force temp\bindings\<pkg> | Out-Null
```

Decide the category the binding will land in (native, hybrid, ignored) and check the manifest row and the existing file, if any. If a file exists, follow section 5 of the specification before continuing: record what it does and capture the before-output.

```powershell
lxml --nocomments --log=temp\logs\<pkg>-before.latexml.log --destination=temp\bindings\<pkg>\before.xml temp\bindings\<pkg>\probe.tex
```

## 1. Census the surface

The census answers one question: which control sequences and environments does the package expose, and which of them appear in real documents.

**With a vendored source** (the normal case). Vendor the package first; `lctan <pkg>` puts its runfiles under `lib-ctan/<pkg>/tex/latex/<pkg>/` with provenance (see `docs/recipes/fetch-ctan.md`). `texscan` then scans the raw `.sty` and reports what it defines that no binding implements. It resolves sources through `kpsewhich` first, which does not exist on this machine, so the directory must be given explicitly. It also reads existing bindings from `blib/lib/LaTeXML/Package/`, not `lib/`, so pass the `Package/` and `Engine/` directories under `lib/` as search paths or the diff will report everything as missing and warn about `TeX.pool`.

```powershell
lctan <pkg>
perl tools/texscan --diff --path=lib-ctan/<pkg>/tex/latex/<pkg> --path=lib/LaTeXML/Package --path=lib/LaTeXML/Engine <pkg>.sty > temp\bindings\<pkg>\census-diff.txt
perl tools/texscan --signature --path=lib-ctan/<pkg>/tex/latex/<pkg> <pkg>.sty > temp\bindings\<pkg>\census-signature.txt
```

The header comment cites `lib-ctan/<pkg>/provenance.json` (CTAN version and TeX Live revision) as what the binding was written from.

**Without a vendored source** (the package is not in TeX Live, or the decision is to work from documentation only). Use the package documentation and, for the packages it covers, the re-hosted signature record in TeXdig's registry. Write the census by hand as `temp/bindings/<pkg>/census.md`: one line per construct, its argument shape, and whether it is structural, semantic, or furniture. The header comment will cite this as what the binding was written from.

Either way, mark each construct with its demand if known (the gauntlet paper counts in the TeXdig inventory) so the fixture exercises the common ones first.

## 2. Tier 1: mechanical stub

With a source available, `texscan` drafts the file:

```powershell
perl tools/texscan --stub --base=article.cls,amsmath.sty --path=lib-ctan/<pkg>/tex/latex/<pkg> <pkg>.sty
Move-Item <pkg>.sty.ltxml temp\bindings\<pkg>\stub.sty.ltxml
```

The stub is a skeleton: package requirements, base inclusions, and a commented-out line per control sequence. It is written to the current directory, hence the move. Without a source, write the skeleton by hand from the census; it is a dozen lines.

Bindings whose whole job is to accept a package and do nothing (page layout, running-text font selection) finish here: uncomment nothing, add a header comment arguing per construct that its absence does not change what the source means, declare the category **ignored**, and go to the fixture. If any construct is meaning-bearing to a reader, it is not furniture; it gets a trace at tier 2 (specification section 3, item 5).

## 3. Tier 2: semantic surface

Fill in the constructs that map onto things the engine already knows how to say. This is the median binding, about twenty lines.

| Construct kind | Definition | Model to copy |
| :--- | :--- | :--- |
| pure expansion | `DefMacro('\cmd{}', '...')` | any |
| math symbol or operator | `DefMathI('\cmd', undef, "\x{...}", role => '...', meaning => '...')` | `extarrows.sty.ltxml` |
| stretchy arrow with `[under]{over}` | `DefMathI(... stretchy => 'true')` wrapped by `\lx@long@arrow` | `extarrows.sty.ltxml`, `extpfeil.sty.ltxml` |
| stacking over a relation or operator | `\stackrel`-style constructors | `stackrel.sty.ltxml` |
| matrix variant with delimiters | `\lx@ams@matrix{name=...,datameaning=matrix,left=...,right=...}` | `nicematrix.sty.ltxml` |
| float variant | `DefEnvironment` to `ltx:table` or `ltx:figure` | `rotfloat.sty.ltxml` |
| keyval options | `DefKeyVal('<pkg>', 'key', '')` and `OptionalKeyVals:<pkg>` in the prototype | `nicematrix.sty.ltxml` |
| furniture inside a real package | `DefMacro('\cmd{}', '')` with a comment | any |

Probe as you go. `lmath` is the fastest loop for math constructs; `lxml` over a literal for anything structural:

```powershell
lmath '\xmapsto[a]{b}' -Preload <pkg>
lxml --preload=<pkg> --log=temp\logs\<pkg>-probe.latexml.log --destination=temp\bindings\<pkg>\probe-out.xml literal:'\documentclass{article}\usepackage{<pkg>}\begin{document}...\end{document}'
```

The engine loads the binding from `lib/` on every run; there is no build step between an edit and a probe. Work on the file in place at `temp/bindings/<pkg>/<pkg>.sty.ltxml` and pass `--path=temp/bindings/<pkg>` until it is ready to move into `lib/`.

Leave undefined anything you have not implemented. A probe that errors on an undefined control sequence is telling you the census is incomplete, which is the point.

## 4. Tier 3: structural constructors

A construct that must emit structure the engine has no existing vocabulary for (a diagram, a pseudocode block, a grid with semantics) needs a constructor, and a constructor is where a binding stops being mechanical.

1. **Choose the target shape first.** Write the intended `ltx` output for the fixture by hand, as XML, into `temp/bindings/<pkg>/target.xml`. Check it against the RelaxNG schema under `lib/LaTeXML/resources/RelaxNG/`. If the shape needs an element or attribute the schema does not have, stop: that is a schema decision, not a binding decision, and it goes to a discussion in the issues workspace before any code.
2. **Find the nearest existing constructor** and read it whole. `amscd.sty.ltxml` for anything arranged on a grid with arrows; the `\lx@gen@matrix@bindings` family for anything array-like; `algorithmic.sty.ltxml` for line-structured blocks.
3. **Build the grid or block from the existing helpers**, then the per-cell or per-line constructs on top. `tikz-cd.sty.ltxml` shows the full pattern: the environment expands to the generic matrix bindings with a `datameaning`, and each `\arrow[...]` is parsed by an undigested options reader into an `XMApp` with `role="ARROW"` and Unicode content, with labels as scripts.
4. **Parse options yourself when the package's option language is not keyval.** Read the token list undigested, classify each option, and reject what you do not understand loudly. Do not expand to nothing.
5. **Probe against `target.xml`** until the diff is empty except for attributes the engine adds.
6. **Check parsing, not just structure.** Every math cell the constructor produces must parse without `ltx_math_unparsed` residue. A cell that fails is allowed to fail alone, but the fixture must then show it failing, and the header must say why.

If a package needs its raw source executed for part of its surface, the binding is **hybrid**: keep `InputDefinitions` for exactly that part, wrap or override the rest, declare the category, and make sure the source is in the resident library so the binding is reproducible.

## 5. Fixture

Move the binding into place and write the case:

```powershell
Move-Item temp\bindings\<pkg>\<pkg>.sty.ltxml lib\LaTeXML\Package\<pkg>.sty.ltxml
```

Create the suite directory `t/<pkg>/` and its driver `t/8N_<pkg>.t`, picking the next free number in the 80s:

```perl
use LaTeXML::Util::Test;
latexml_tests("t/<pkg>", strict => 1);
```

Each case `t/<pkg>/<construct>.tex` is a complete document that loads the package and everything its constructs depend on (`\mathbb` needs `amssymb`, not `amsmath`); between them the cases exercise every construct the header claims, including deliberately dropped ones. A small binding may need only one case. Write each golden with `lgold`, which digests with the driver's own configuration and refuses if the engine counted errors, then read it before committing:

```powershell
lgold t\<pkg>\<construct>.tex
ltst t/8N_<pkg>.t
```

Do not write goldens with `lxml`: the CLI emits a search-path processing instruction the driver suppresses, and the comparison fails at line 1. The suite is strict, so a case whose conversion reports errors fails regardless of its golden; the diagnostic names the undefined macro or missing package.

For a replacement, digest the same fixture to `temp/bindings/<pkg>/after.xml` and diff against `before.xml` from step 0. The diff must be exactly what the binding intends.

## 6. Done

Walk section 4 of the specification. Then:

```powershell
ltst t/8N_<pkg>.t t/40_math.t t/45_capture.t
```

Commit the binding, the fixture pair, and the manifest row together:

```
feat(Package): native binding for <pkg>
```

or, for a replacement:

```
feat(Package): native binding for <pkg>, replacing passthrough
```

with the fixture's emitted XML in the message body. Delete `temp/bindings/<pkg>/` or leave it; nothing references it.
