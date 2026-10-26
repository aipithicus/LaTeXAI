I'll build a self-contained survey script—a TeX tokenizer plus a statement segmenter based on argument signatures—then test it on a few known packages before running it on the full set.

I found two issues to fix: expl3 syntax switches should only be counted at brace depth 0, since nicematrix toggles them inside stored code, and package-local definers like xypic's `\xydef@` and amsmath-style `\DN@` need definer-shaped call signatures. I'll check how these are defined next.

Still refining the classifier: the first full run surfaced noise sources (expl3 toggles inside stored code, local definers). Checking a few remaining stray-text spots before the final run.

Down to residual noise now. Verifying the unbalanced-file counts by column name (I was reading the wrong column), then building the report.

Classifier is stable; generating the final per-package table.

Since lib-ctan lacks math vocabulary packages (those are in lib-symb), I'll run the survey over lib-symb instead to test the "symbol packages are nearly all rows" prediction.

I found two issues from the lib-symb run: fontawesome5's mapping file needs to start in expl mode since it's expl3 code loaded under its parent's syntax, and bbding's zero-argument glyph `\newcommand`s are really table rows in disguise. I'm adding a `def:constant` category to handle the latter.

I ran the measurement on lib-ctan, plus the five notation packages in lib-symb for contrast, since lib-ctan has no math vocabulary packages. The prediction holds for notation packages. It does not hold for the rest of what papers load.

## Headline numbers

| Corpus | Units | Statements | Rows | Substitution defs | Program | Other |
|---|---:|---:|---:|---:|---:|---:|
| lib-symb (notation packages) | 5 | 5,502 | **83%** | 7% | 5% | 5% |
| lib-ctan | 72 | 38,118 | **19%** | 29% | 31% | 21% |

What the columns mean:
- **Rows:** table declarators, aliases, calls to a package's own declarator wrappers, and zero-argument macros whose body is just a glyph reference.
- **Substitution defs:** definitions whose body only substitutes arguments or parses optional arguments, plus calls to a package's own definer macros.
- **Program:** definitions with control flow, expansion control or assignments in their body, plus code that runs at the top level.
- **Other:** package-mechanism calls, configuration assignments, and calls I couldn't resolve.

`.fd` font-definition files are left out of both totals. They contain 2,020 and 3,573 statements, almost all `\DeclareFontShape`.

## What it says

- **Notation packages are table-shaped, but mostly through their own wrapper macros.** By package: bbding 97%, fontawesome5 94%, MnSymbol 92%, kpfonts 71%, tipa 67%.
  - 3,502 of the 4,588 rows go through package-local wrappers such as `\Decl@Mn@Char` (1,149 calls), `\re@DeclareMathSymbol` (679) and `\Decl@Mn@Alias` (160).
  - bbding writes each glyph as `\newcommand{\X}{\@chooseSymbol{'001}}`.
  - So table extraction has to recognise a package's own declarator wrappers. The survey does this automatically: it flags a macro whose body ends in a declarator, and propagates that through helper macros. That's the core of an lsymb-style extractor that works from source.
- **lib-ctan rows are mostly state allocation, not vocabulary.**
  - 2,532 rows are allocations (`\newif`, `\newdimen`, `\tl_new:N`, `\bool_new:N` …) against about 1,150 notation and encoding rows.
  - The notation rows sit in five encoding units: latex base (330), cyrillic (310), vntex (226), cjk (99), and graphics, whose 68 rows are dvipsnam named colours.
  - The expl3 packages look table-heavy (tabularray 41%, nicematrix 37%, siunitx 21%), but those "rows" are variables, messages and variant generation, not vocabulary.
- **Nearly half of all definitions are program.** Of 14,228 definitions, 46% have control flow or expansion control in their body, 33% are pure substitution, 15% are stateful, and 2% take optional or starred arguments with no other logic.
- **The program-heavy packages are the language-feature ones:** xifthen 72%, etoolbox 69%, makecell 63%, ifthen 62%, aliascnt 58%, xargs 50%, the kv* family around 38%, plus engines like forest, xcolor and fancyvrb at about 50%. That matches the ontology brief: these should become engine capabilities, not bindings.
- **A middle class: data through local factories.** 6,266 calls go to package-local definers, including:
  - xypic's `\xydef@` (2,206)
  - pmboxdraw's `\py@DRC` (816)
  - babel's `\BabelBeforeIni` (549, locale data)
  - siunitx's `\DeclareSIUnit` (361)
  - algorithm2e's `\SetKw*`

  These calls are row-shaped where they're made, even though what they produce is definitions.

## Per package, lib-ctan

| package | stmts | rows % | subst % | prog % | other % | expl3 % |
|---|---:|---:|---:|---:|---:|---:|
| graphics | 69 | 99 | 0 | 0 | 1 | 0 |
| cyrillic | 322 | 97 | 2 | 0 | 1 | 0 |
| latex | 404 | 83 | 12 | 4 | 1 | 0 |
| vntex | 297 | 77 | 1 | 1 | 21 | 0 |
| cleveref | 1810 | 59 | 16 | 18 | 7 | 0 |
| tabularray | 3522 | 41 | 9 | 29 | 21 | 100 |
| nicematrix | 1116 | 37 | 13 | 39 | 12 | 100 |
| footnotehyper | 74 | 31 | 11 | 45 | 14 | 0 |
| ncctools | 135 | 26 | 14 | 34 | 26 | 0 |
| datetime | 769 | 25 | 6 | 33 | 36 | 0 |
| tensor | 60 | 23 | 17 | 37 | 23 | 0 |
| scalerel | 38 | 21 | 34 | 34 | 11 | 0 |
| siunitx | 2631 | 21 | 29 | 40 | 10 | 99 |
| lineno | 507 | 21 | 16 | 28 | 35 | 0 |
| collectbox | 63 | 17 | 33 | 44 | 5 | 0 |
| rotfloat | 23 | 17 | 0 | 65 | 17 | 0 |
| tikz-qtree | 164 | 17 | 25 | 41 | 16 | 0 |
| textpos | 139 | 17 | 6 | 29 | 48 | 0 |
| abstract | 71 | 15 | 20 | 18 | 46 | 0 |
| tcolorbox | 1214 | 15 | 27 | 38 | 20 | 25 |
| titletoc | 130 | 15 | 35 | 35 | 14 | 0 |
| ltxcmds | 252 | 15 | 28 | 31 | 26 | 0 |
| mdframed | 353 | 15 | 15 | 28 | 42 | 20 |
| etoc | 549 | 14 | 29 | 46 | 11 | 0 |
| bookmark | 323 | 13 | 20 | 31 | 36 | 5 |
| algorithms | 113 | 13 | 42 | 13 | 31 | 0 |
| babel | 2979 | 13 | 27 | 40 | 19 | 8 |
| thmtools | 401 | 13 | 25 | 41 | 21 | 0 |
| newunicodechar | 32 | 12 | 6 | 50 | 31 | 0 |
| xargs | 113 | 12 | 33 | 50 | 4 | 0 |
| geometry | 402 | 12 | 36 | 33 | 18 | 0 |
| nowidow | 17 | 12 | 12 | 29 | 47 | 0 |
| cjk | 1658 | 11 | 70 | 10 | 8 | 0 |
| keyval | 19 | 11 | 16 | 42 | 32 | 0 |
| eso-pic | 147 | 10 | 41 | 27 | 21 | 0 |
| xypic | 4756 | 10 | 52 | 14 | 25 | 0 |
| forest | 1340 | 9 | 26 | 50 | 14 | 0 |
| xcolor | 882 | 9 | 20 | 50 | 21 | 0 |
| ifthen | 37 | 8 | 5 | 62 | 24 | 0 |
| algorithm2e | 1068 | 8 | 54 | 19 | 19 | 0 |
| etoolbox | 389 | 8 | 19 | 69 | 5 | 0 |
| fvextra | 1036 | 8 | 12 | 41 | 39 | 0 |
| listings | 1427 | 7 | 39 | 32 | 22 | 0 |
| csquotes | 780 | 6 | 35 | 29 | 30 | 0 |
| adjustbox | 696 | 6 | 34 | 31 | 30 | 0 |
| extpfeil | 18 | 6 | 28 | 33 | 33 | 0 |
| xurl | 19 | 5 | 11 | 16 | 68 | 0 |
| cprotect | 78 | 5 | 18 | 41 | 36 | 0 |
| makecell | 131 | 5 | 30 | 63 | 2 | 0 |
| pmboxdraw | 358 | 4 | 32 | 43 | 21 | 0 |
| tikz-cd | 45 | 4 | 20 | 27 | 49 | 0 |
| fancyvrb | 406 | 4 | 24 | 50 | 23 | 0 |
| lipsum | 584 | 4 | 2 | 6 | 88 | 12 |
| optidef | 80 | 4 | 20 | 51 | 25 | 0 |
| kvdefinekeys | 90 | 3 | 18 | 24 | 54 | 0 |
| algorithmicx | 737 | 3 | 31 | 12 | 55 | 0 |
| kvoptions | 236 | 3 | 24 | 37 | 36 | 0 |
| kvsetkeys | 153 | 2 | 21 | 39 | 38 | 0 |
| refcount | 123 | 2 | 28 | 27 | 43 | 0 |
| bitset | 308 | 1 | 39 | 35 | 26 | 0 |
| babel/locale | 1210 | 0 | 49 | 50 | 1 | 0 |
| aliascnt | 12 | 0 | 17 | 58 | 25 | 0 |
| doi | 7 | 0 | 29 | 29 | 43 | 0 |
| extarrows | 22 | 0 | 86 | 0 | 14 | 0 |
| forloop | 5 | 0 | 0 | 40 | 60 | 0 |
| gettitlestring | 103 | 0 | 21 | 28 | 50 | 0 |
| ifmtarg | 6 | 0 | 50 | 0 | 50 | 0 |
| needspace | 6 | 0 | 0 | 67 | 33 | 0 |
| stackrel | 11 | 0 | 18 | 45 | 36 | 0 |
| upquote | 11 | 0 | 18 | 27 | 55 | 0 |
| xifthen | 32 | 0 | 12 | 72 | 16 | 0 |

babel-english has no code files, and lipsum's 88% "other" is the paragraph text in its data files.

## Caveats

- **This counts implementation, not binding effort.** A program-bodied internal like keyval's `\KV@do` is code a binding replaces with an engine capability. The better next measure is the user-level surface per package (exported names without `@`, `_` or `:`) and how those bodies split.
- **The method is heuristic.** It uses a small tokenizer with fixed catcodes and tracks expl3 syntax. 7 of 915 files have unbalanced braces from verbatim-style catcode tricks, so they're partly misread. That's 3 in xypic and 1 each in babel, datetime, lineno and listings.
- **Body classes only look at the body itself.** A "substitution" body may call program macros.
- **Wrapper detection can over-count.** A macro that reaches a declarator helper only in one branch still counts as a declarator wrapper.
- **22% of statements sit inside containers** (option bodies, hooks, conditional branches) and are included in the counts.
- **lib-ctan leans towards layout and infrastructure packages.** The math vocabulary in amssymb and friends isn't vendored there.

Everything is in the session scratchpad, not in the repo:
- Script: C:\Users\azrie\AppData\Local\Temp\claude\D--aipithicus-LaTeXAI\f97cfc24-f880-4178-a120-af3117559c14\scratchpad\declarator_survey.py
- lib-ctan results: C:\Users\azrie\AppData\Local\Temp\claude\D--aipithicus-LaTeXAI\f97cfc24-f880-4178-a120-af3117559c14\scratchpad\declarator-survey\report.md
- lib-symb results: C:\Users\azrie\AppData\Local\Temp\claude\D--aipithicus-LaTeXAI\f97cfc24-f880-4178-a120-af3117559c14\scratchpad\declarator-survey-symb\report.md

Each results folder also has `per_package.tsv` (every category per unit), `statements.tsv` (every statement with file, line, head, category and context) and `heads.tsv`.