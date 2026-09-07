# Minting a binding

Executable recipe for producing a binding that meets [`docs/specification/bindings.md`](../specification/bindings.md). Commands run from the repository root through the `pwsh_exec` profile, which provides `lxml`, `lmath`, and `ltst`. Every intermediate file goes under `temp/bindings/<pkg>/`; nothing in this recipe writes to the repository root or to `lib/` until the final step.

The recipe has one entry and one exit and three tiers in between. Most bindings finish at tier 1 or 2. Tier 3 is where the work is, and it is also where the process most needs to be followed rather than improvised.

```
census + idioms + expectations ─► tier 1: mechanical stub ─► tier 2: semantic surface ─► tier 3: structural constructors ─► fixture ─► read the golden ─► done
```

Two of those boxes exist because their absence was expensive. Five suites minted in September 2026 passed strict while their goldens were wrong: the fixtures were written from the binding's feature list rather than from how documents use the package, and the goldens were read against the binding's claims rather than against the package. The expectations step and the golden-reading step are the correction; skipping them produces a suite that covers the binding and not the package.

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

**Harvest the idioms.** The fixture has to contain the forms real documents use, not the forms the binding finds convenient. Search the gauntlet corpus for documents that load the package and count the constructs and option forms they use:

```powershell
$papers = Get-ChildItem -Recurse -Filter *.tex D:\aghado01\codex-scientiae\supellex\gauntlet |
  Select-String -List '\\usepackage(\[[^\]]*\])?\{[^}]*\b<pkg>\b' | ForEach-Object Path
$papers | ForEach-Object { Select-String -Path $_ -Pattern '\\usepackage\[[^\]]*\]\{<pkg>\}|\\(<cmd1>|<cmd2>|…)\b' -AllMatches } |
  ForEach-Object { $_.Matches.Value } | Group-Object | Sort-Object Count -Descending |
  Out-File temp\bindings\<pkg>\idioms.txt
```

Take the command list from the census signature. Every form with a nonzero count appears verbatim in a fixture case, option lists included. The algorithmicx suite was minted without this step: `\algnewcommand\cs{…}` and `\algdef{S}[FOR]…`, used by four gauntlet papers, never reached a fixture, and the one-argument stubs that ate them passed strict.

**Write the expectations.** Before any code, write `temp/bindings/<pkg>/expectations.md` from the vendored source and the package documentation: one line per construct that will be implemented, giving a source input and the observable the IR must show. Observables are concrete. The element and its class; the attribute and its value (`colspan="2"`, `border="t"`); the element the `\label` must land on; the text a keyword produces and where the math that follows it sits; the counter a number comes from. Write it from what the package does, not from what the binding is about to do. The point is to hold something the binding did not generate when the golden is read. A tier 3 constructor extends this into a full `target.xml`.

## 2. Tier 1: mechanical stub

With a source available, `texscan` drafts the file:

```powershell
perl tools/texscan --stub --base=article.cls,amsmath.sty --path=lib-ctan/<pkg>/tex/latex/<pkg> <pkg>.sty
Move-Item <pkg>.sty.ltxml temp\bindings\<pkg>\stub.sty.ltxml
```

The stub is a skeleton: package requirements, base inclusions, and a commented-out line per control sequence. It is written to the current directory, hence the move. Without a source, write the skeleton by hand from the census; it is a dozen lines.

Bindings whose whole job is to accept a package and do nothing (page layout, running-text font selection) finish here: uncomment nothing, add a header comment arguing per construct that its absence does not change what the source means, declare the category **ignored**, and go to the fixture. If any construct is meaning-bearing to a reader, it is not furniture; it gets a trace at tier 2 (specification section 3, item 5).

## 3. Tier 2: semantic surface

Fill in the constructs that map onto things the engine already knows how to say. This is the **semantic** class in [`bindings.md`](../specification/bindings.md) section 2.1. This is the median binding, about twenty lines.

| Construct kind | Definition | Model to copy |
| :--- | :--- | :--- |
| pure expansion | `DefMacro('\cmd{}', '...')` | any |
| math symbol or operator | `DefMathI('\cmd', undef, "\x{...}", role => '...', meaning => '...')` | `extarrows.sty.ltxml` |
| stretchy arrow with `[under]{over}` | `DefMathI(... stretchy => 'true')` wrapped by `\lx@long@arrow` | `extarrows.sty.ltxml`, `extpfeil.sty.ltxml` |
| stacking over a relation or operator | `\stackrel`-style constructors | `stackrel.sty.ltxml` |
| matrix variant with delimiters | `\lx@ams@matrix{name=...,datameaning=matrix,left=...,right=...}` | `nicematrix.sty.ltxml` |
| float variant | `DefEnvironment` to `ltx:table` or `ltx:figure` | `rotfloat.sty.ltxml` |
| keyval options | `DefKeyVal('<pkg>', 'key', '')` and `OptionalKeyVals:<pkg>` in the prototype | `nicematrix.sty.ltxml` |
| package options | `DeclareOption('name', sub {…})` per option; `DeclareOption(undef, sub {…})` for the wildcard. `DeclareOption('*', …)` declares an option literally named `*` | `xurl.sty.ltxml` |
| commands that define commands | `DefMacroI(T_CS("\\$name"), convertLaTeXArgs($nargs, $default), $body)` from the real signature; never a no-op | `tcolorbox.sty.ltxml` (`\newtcolorbox`), `algorithmicx.sty.ltxml` (`\algdef`) |
| furniture inside a real package | `DefMacro('\cmd<real signature>', '')` with a comment; the signature matches the source so the stub consumes exactly what the command would | any |

Write each construct with the vendored `.sty` open at its definition. Memory is where the errors came from: `\tcp` and `\tcc` were swapped, `\;` lost its `\@mathsemicolon` guard and broke every math cell in an algorithm, a `\multicolumn`-style span was written as a property assignment the engine overwrites. When the source and your recollection differ, the source is right.

A no-op with the wrong arity is worse than no definition: `DefMacro('\algnewcommand{}', '')` reads the control sequence and leaks the body as running text, which then opens a paragraph inside the listing and pushes the float into it. Match the signature or leave the command undefined.

Keyword macros that end in `\textbf{word}` get a trailing `\space`, as `\SetKw` already produces. A macro-produced bold run followed directly by `$` absorbs the math into the bold text; that is an engine defect in the document builder, recorded separately, and the binding does not depend on it being fixed.

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
7. **Do not set what the engine recomputes.** Alignment cells, floats, and lists carry properties the engine fills in during a later phase. `extractAlignmentColumn` in `TeX_Tables.pool.ltxml` overwrites `colspan` at cell end, so writing it from a cell macro is a silent no-op that a strict suite cannot see. Lower to the construct the engine already understands (`\multicolumn`, `\multirow`, `\caption`, `\label`) instead of poking the object. If nothing lowers, the change belongs in `Engine/`, is named in the header, and takes the binding off the contribution track.
8. **Return what you digest in a hook.** `Digest(…)` inside `afterDigestBegin` or `properties` produces boxes that reach the document only if the hook returns them. A `\label` digested and dropped attaches to nothing and every `\ref` to it dangles; tcolorbox's first golden shipped with two of those and the strict suite passed.
9. **Slice tokens, do not stringify them.** A caption, a title, or a label read from a key-value list keeps its tokens. `ToString` followed by `Explode` turns `\alpha` into five characters of catcode other and `$` into a literal dollar sign, and the caption with any macro in it disappears.

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

Each case `t/<pkg>/<construct>.tex` is a complete document that loads the package and everything its constructs depend on (`\mathbb` needs `amssymb`, not `amsmath`); between them the cases exercise every construct the header claims, including deliberately dropped ones, every idiom in `idioms.txt` verbatim, and for a replacement every override the old file carried. A small binding may need only one case. Write each golden with `lgold`, which digests with the driver's own configuration, refuses if the engine counted errors, and refuses if the golden lint finds a dangling `labelref` or an engine-internal `\lx@` token in the document:

```powershell
lgold t\<pkg>\<construct>.tex
ltst t/8N_<pkg>.t
```

Do not write goldens with `lxml`: the CLI emits a search-path processing instruction the driver suppresses, and the comparison fails at line 1. The suite is strict, so a case whose conversion reports errors fails regardless of its golden; the diagnostic names the undefined macro or missing package. `lgold --lenient` bypasses the lint for a case that exercises the failure on purpose, and `lgold --check` lints without writing, for re-checking an existing suite.

For a replacement, digest the same fixture to `temp/bindings/<pkg>/after.xml` and diff against `before.xml` from step 0. The diff must be exactly what the binding intends.

**Read the golden against the expectations, not against the binding.** `lgold` guarantees the golden is what the driver will see, that the conversion was clean, and that the lint passed. It cannot know whether the structure is right. That is the reading, and the reading is done against `expectations.md`: for each line there, find the fragment in the golden that shows it, and write the fragment down for the claims table. Then walk the cases that have failed before:

- every `\label` in the case appears in a `labels=` attribute on the element it belongs to, and every `\ref` resolves to one;
- every span the source declares (`\multicolumn`, `\SetCell[c=2]`, `\multirow`) is a `colspan` or `rowspan` attribute, and every rule (`\hline`, `hlines`, `\toprule`) is a `border`;
- no `ltx:Math` sits inside an `ltx:text` with a font unless the source put it there;
- keywords, comments, and separators produce the text the package produces (`//` for algorithm2e's `\tcp`, `{…}` for algorithmic's `\COMMENT`) and break lines where the package breaks them;
- a numbered object is numbered from the counter the package uses, and a reference to it shows that number;
- a multi-target reference names the type of each target, not the first target's type for all of them;
- nothing in a `tex=` attribute is a control sequence the document did not write.

A golden that reads well against the binding's own claims and badly against this list is the case this step exists for. Each check above has a golden that was committed with it failing: tcolorbox the first, tabularray the second, algorithm2e the third and fourth, cleveref the sixth, algorithmicx the seventh by way of a leaked preamble.

## 6. Done

Walk section 4 of the specification. Then:

```powershell
ltst t/8N_<pkg>.t t/40_math.t t/45_capture.t
```

The completion report, in the commit body or the walkthrough, carries three things, and a binding without them is not reported as done:

1. **A claims table.** One row per construct the header claims: the construct, the fixture line that exercises it, the golden fragment that shows the observable from `expectations.md`. A construct with no fragment is removed from the header, not from the table. "Supports `hlines`" is a claim; a golden with no `border` attributes is the evidence against it.
2. **The census residue.** What `texscan --diff` still lists as undefined after the rewrite, one word each: on purpose, or not yet. A replacement whose residue is longer than the hybrid's override list has regressed.
3. **The idiom coverage.** Each line of `idioms.txt` with the case that contains it.

Commit the binding, the fixture pair, and the manifest row together:

```
feat(Package): native binding for <pkg>
```

or, for a replacement:

```
feat(Package): native binding for <pkg>, replacing passthrough
```

with the fixture's emitted XML in the message body. Delete `temp/bindings/<pkg>/` or leave it; nothing references it.
