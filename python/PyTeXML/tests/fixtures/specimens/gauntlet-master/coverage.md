# Coverage map

This maps each case in the gauntlet inventory (`reports/gauntlet-master-inventory-20261027.md`
in the private issues workspace) to its place in this fixture.

- **Tags.** Each place carries a bracketed tag, such as `[T10]`, in a comment
  next to it. To find every place for a tag, run `rg -n '\[T10\]'`. Line numbers
  in the tables are as of 2026-10-27; the tags are the stable anchors.
- **Frequencies** come from the inventory. `Np` is a number of papers.
  **pkg** means the case was counted in local `.sty` or `.cls` files rather than
  in author `.tex` files.
- **Roots.** A is `master.tex` (natbib), B is `master-biblatex.tex`, C is
  `master-plain.tex` and D is `master-arxiv.tex`.

## Expected observations

Selected cases come with expected observations: what a correct reading of the
fixture shows. They are progress criteria for preparation runs. A case passes when the
prepared master and manifest agree with its observation, not merely when the run
reports no error at that place.

The TeX side of each observation was confirmed on 2026-10-27. A copy of the root was
compiled with Tectonic (XeTeX), and the `\typeout` probes and typeset text were
checked. Everything is in root A unless the entry names another root.

### Nested effects

- **N13** `gmstyle.cfg:3`, read from `gmtools.sty:5` and then again from `gmstyle.sty:5`:
  - **First read.** `\ifdefined\gm@cfgseen` is false, so lines 4–5 run.
  - **Second read.** The test is true. `\expandafter` closes the conditional
    before `\endinput` runs, so input ends after line 3.
  - **After both.** The conditional level is back to 0, `gmstyle.sty` continues
    at line 6, and `\gm@cfgversion` is `1` where `sections/tail.tex:4` uses it.
    No `\fi` is unmatched.
- **N15** `body/macros.tex:47–55`:
  - **`\let` targets.** `\gmnothing` is `\relax` and `\gmgone` is undefined.
  - **The chain.** It copies meanings, so `\gmtop` is `\textbf` and `\gmtop{bold}`
    at `sections/nesting.tex:5` is bold.
  - **Save-and-wrap.** `\gmoldparagraph` keeps the earlier `\paragraph`, which is
    distinct from the new one. `\paragraph{Wrapped}` at `sections/nesting.tex:7` runs the
    hook once, then the original sectioning, with no recursion.
- **N4, B6, B7** `master.tex:15–17`, `gmvenue.cls:22`, `body/paper.tex:72`: the wrapped
  `\bibliographystyle` discards its argument. `abbrvnat` is ignored, and the class's
  `plainnat` is the style written (`\bibstyle{plainnat}`).
- **N5** `master.tex:19–23`:
  - **When it fires.** The hooks are registered under the base name `math` and fire
    around `\input{sections/math}` at `body/paper.tex:62`. `gmtools: entering math`
    comes before the section and `left math` after it.
  - **Under flattening.** A master that inlines `sections/math.tex` no longer has
    that input, so the before and after code must still run exactly around the
    inlined section.
- **N6** `body/paper.tex:68`: the dead `\input` names a missing file. It is never
  opened and should not become a missing-file requirement.
- **N7** `body/paper.tex:69`: `\gmarxiv` is defined at `master.tex:7`, so `\ifdefined`
  is true and `sections/extras.tex` is read.
- **N20** `sections/figures.tex:19`: `drawing.pdf_tex` resolves to
  `figures/drawing.pdf_tex` through `\input@path`.

### Classes, packages and branches

- **D10** `gmvenue.cls:5–13`:
  - **Flags.** `\ExecuteOptions{final}` sets `\ifgm@final`, and `\ifgm@numeric`
    stays false.
  - **Unknown options.** The class passes `11pt` to article through
    `\DeclareOption*`, so the body size is 10.95pt.
- **P9** `gmstyle.sty:6`: the class has already loaded natbib with `authoryear,round`
  (`gmvenue.cls:21`). `\@ifpackageloaded` is true, the `[numbers]` load doesn't happen,
  and natbib's options stay `authoryear,round`.
- **P10** `gmstyle.sty:7–10`: after the `\edef`, `\gm@load` is
  `\RequirePackage{xspace}`, so xspace is loaded.
- **P11** `master.tex:14`, `body/paper.tex:4`: `\ver@gmfake.sty` is defined, so
  `\usepackage{gmfake}` reads no file. No binding or file requirement should name gmfake.
- **D2** `body/paper.tex:5–11`, `sections/branches.tex:3`:
  - **Reading.** `\ifPDFTeX`, `\ifXeTeX` and `\ifLuaTeX` are conditionals whose value
    depends on the compiling engine, and their `\else` and `\fi` must be read as theirs.
    Which branch the master keeps is not fixed here.
  - **Under Tectonic.** The fontspec branch runs, and `sections/branches.tex` prints
    "Engine: XeTeX."

### Catcodes

- **T3** `body/paper.tex:70` → `sections/tail.tex`: `@` is still a letter (11) when
  `tail.tex` starts. Its `\gm@…` names are single control sequences.
- **T7** `sections/catcodes.tex:15`: inside the group, the assignment applies to the
  rest of the line, so `x^y` prints a literal `^`. After the `}`, `^` is superscript
  again in `$x^y$`.
- **T10** `gmvenue.cls:44–49`, `sections/catcodes.tex:6`: `\gmcolumncase` runs
  `\makeatletter` before its arguments are read. `\gm@one` is one control sequence
  and gives "one-column text", and `@` is other (12) again afterwards.
- **T13** `gmstyle.sty:12–16`:
  - **The definition.** The `\gdef` survives its group.
  - **The catcode.** The assignment is restored: `_` is 8 again after the group.
  - **The captured token.** The underscore token keeps its definition-time catcode 12,
    so `\gmunderscore` at `sections/catcodes.tex:20` prints `_` rather than starting
    a subscript.
- **T14** `gmstyle.sty:18–23`, `sections/catcodes.tex:13`: `\gmlbrace` and `\gmrbrace`
  each hold one brace of catcode 12. `\gmlbrace x\gmrbrace` prints `{x}` and opens no
  group. After the group `{` is 1 and `(` is 12 again.
- **T15** `gmstyle.sty:25–31`, `sections/catcodes.tex:8–9`:
  - **Inside the groups.** `\gmdqon` makes `"` active, giving "Müller, Schöne" and "König".
  - **Outside.** `"` is other (12) outside the groups.
  - **After `\gmdqoff`.** `"` is other again in the rest of the second group,
    because a catcode applies to characters not yet read.
- **T16** `gmstyle.sty:33–37`, `sections/catcodes.tex:11`: the active `|`, defined at
  package level through `\lccode` and `\lowercase`, means `\ensuremath{\vert}`.
  `\gmbaron` makes `|` active only inside its group.
- **T18** `gmstyle.sty:43–48`: `\gmjoined` is `joinedacross lines`. Under
  `\endlinechar=-1` the line end adds no space, and the next line's indentation is skipped.
- **T19** `gmstyle.sty:50–52`: `\gmifletter{a}` gives "letter" and `\gmifletter{1}`
  gives "not a letter". `\gmplainties{no~tie}` gives a plain space.

### Bibliography

- **B9** `master-biblatex.tex:5–6` (root B): the backend is bibtex, from `backend=bibtex`,
  and the data source is `refs.bib`, from `\addbibresource`.
- **B11** `master-arxiv.tex:10` (root D): the shipped `master-arxiv.bbl` supplies
  all 8 entries. The missing `arxiv-stripped.bib` is not an error for preparation.

## Classes and packages

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| C1 | Local class | 23p | `master.tex:5` → `gmvenue.cls` |
| C2 | Local class over `\LoadClass`, with a trailing date | 13p; 1p dated | `gmvenue.cls:14` |
| C3 | `\pdfoutput=1` before `\documentclass` | 6p | `master.tex:1–4` |
| C4 | `\documentclass` after a comment header, with a trailing comment | 2p | `master-plain.tex:4` |
| P1 | Several packages in one call | 97p | `body/paper.tex:12` |
| P2 | A call that spans lines, with `%` inside the list | 16p | `body/paper.tex:13–14` |
| P3 | Trailing date option | 3p (pkg) | `body/paper.tex:16` |
| P4 | `\RequirePackage` before `\documentclass` | 11p | `master.tex:4` |
| P5 | Package option chosen under an engine test | 5p | `body/paper.tex:26–28` |
| P8 | Package choice inside a class option flag | 15p (pkg) | `gmvenue.cls:16` |
| P9 | Load guarded by `\@ifpackageloaded` | 1p (pkg) | `gmstyle.sty:6` |
| P10 | Package name computed by `\edef` | 1p (pkg) | `gmstyle.sty:7` |
| P11 | Package marked loaded with `\csname ver@x.sty\endcsname`, so `\usepackage{gmfake}` reads no file | 1p | `master.tex:13`, `body/paper.tex:4` |
| P12 | geometry with `margin=1in`; microtype | 82p (21p that option); 53p | `body/paper.tex:17–18` |

## Comments

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| K1–K4 | Whole-line comment; trailing comment; bare `%` joining lines; `%%` banner | 137p, 126p, 115p, 105p | `sections/comments.tex:2–6` |
| (K5) | Lone `%` line (it can't carry a tag) | 85p | `sections/comments.tex:7` |
| K6 | Escaped `\%` | 90p | `sections/comments.tex:8` |
| K7 | Commented-out `\usepackage`, `\input`, `\begin`/`\end`, `\bibliography`, `\end{document}` | 96p, 25p, 78p, 12p, 4p | `sections/comments.tex:9–13` |
| K8 | Multi-line `\iffalse` block holding an unbalanced `\begin`, a missing input and `\iff` | 6p | `sections/comments.tex:14–22` |
| K9 | Inline `\iffalse … \fi` | 6p | `sections/comments.tex:23` |
| K10 | Numeric false test used as a comment | | `sections/comments.tex:24` |
| K11 | `comment` environment | 5p | `sections/comments.tex:25–28` |
| K12 | `\excludecomment` and `\includecomment` | 1p (pkg) | `body/macros.tex:84–86`; `sections/comments.tex:29–34` |
| K13 | Macro that discards its argument | 15p | `sections/comments.tex:35` |
| K14 | Note shown or hidden by a `\newif` flag | 2p | `sections/comments.tex:36–37` |
| K15 | Text after `\endinput` | 13p (pkg) | `gmstyle.sty:56` |
| K16 | Text after `\end{document}` | 11p | `body/paper.tex:75` |

## Dead branches, engine and format probes, flags

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| D1 | `\ifx\pdfoutput\undefined` and `\ifx\pdfoutput\relax` | 4p (pkg) | `gmvenue.cls:25–29`; also at author level in `sections/branches.tex:4` |
| D2 | iftex names (`\ifPDFTeX`, `\ifXeTeX`, `\ifLuaTeX`) choosing packages and text | 3p, 2p | `body/paper.tex:5`; `sections/branches.tex:2` |
| D4 | Flag by definedness across files | 5p | defined at `master.tex:7`, tested at `sections/branches.tex:6` and `body/paper.tex:69` |
| D5 | `\IfFileExists` on an absent file | 20p (pkg) | `gmvenue.cls:32` |
| D6 | `\newif` flag set true, and one never set | 20p, 13p | `body/paper.tex:38–39` |
| D7 | ifthen boolean; etoolbox toggle | 10p (pkg); 1p | `body/paper.tex:40–41`; `sections/branches.tex:8–9` |
| D8 | Parametric `\ifcsname` over a name built by a macro | 1p | `sections/branches.tex:11` |
| D9 | Emptiness test, `\ifmmode` in a macro, `\loop … \repeat`, `\ifcase`, `\unless` | 1p, 5p, 1p | `sections/branches.tex:13–18` |
| D10 | Option flags set by `\DeclareOption` | 57p | `gmvenue.cls:5–13` |
| D11 | Hand-made flag `\let\ifX\iffalse` | 7p (pkg) | `gmvenue.cls:7` |
| D12 | `\iff`, which starts like a conditional (live text, and inside K8's dead text) | 6p | `sections/branches.tex:20`; `sections/comments.tex:19` |
| D13 | `\ifdim` inside a TikZ option, with `\foreach` pairs | 1p | `sections/figures.tex:20–25` |

## Verbatim

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| V1 | `\verb` with the delimiters `\|`, `!` and `+`; `\verb*`; a payload holding `\` and `%` | 4p, 1p, 1p | `sections/verbatim.tex:2–3` |
| V2 | `\lstinline` in brace form, in delimiter form, and with `%` in the payload | 1p | `sections/verbatim.tex:4–5` |
| V3 | `\verb` in `\caption`, made safe by `\cprotect` | 1p | `sections/verbatim.tex:6–10` |
| V4 | `verbatim` inside a group, with a payload that looks like structure | 8p | `sections/verbatim.tex:11–16` |
| V5 | `lstlisting` with `escapeinside` and `mathescape` | 13p; 3p, 1p | `sections/verbatim.tex:17–21` |
| V6 | `\lstnewenvironment` with an optional argument | 2p | `body/paper.tex:42`; `sections/verbatim.tex:22–25` |
| V7 | `\newtcblisting` | 2p | `body/paper.tex:43`; `sections/verbatim.tex:26–29` |
| V8 | `\DefineVerbatimEnvironment` with `commandchars` | 1p | `body/paper.tex:44`; `sections/verbatim.tex:30–33` |
| V9 | `\VerbatimInput`; `\lstinputlisting` through a parametric macro | 2p; 3p | `sections/verbatim.tex:34–36` |
| V10 | `\path`, `\url` with `%` and `#`, `\nolinkurl`, `\detokenize` | 10p, 58p, 4p, 1p | `sections/verbatim.tex:37–39` |
| V11 | Payload text before `\end{verbatim}` on the closing line | 1p | `sections/verbatim.tex:40–43` |

## Catcode mutations

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| T1 | `\makeatletter` pair, in the body | 40p; 3p in the body | `sections/catcodes.tex:2–3` |
| T3 | `\makeatletter` left open, with the next `\input` read under @-letter | 4p | `body/paper.tex:70` → `sections/tail.tex` |
| T5 | Active UTF-8 characters: `\newunicodechar`, and `\DeclareUnicodeCharacter` under `\ifPDFTeX` | 1p; 4p | `body/paper.tex:8`, `:33–34`; `sections/catcodes.tex:21–22` |
| T6 | Catcode saved in a `\chardef`, set with an explicit `\catcode`, then restored | 2p (pkg) | `body/macros.tex:2–3`, `:87` |
| T7 | `\catcode` change partway through a line, inside a group | (language-core brief §10) | `sections/catcodes.tex:14–15` |
| T8 | `\obeylines` in a group | 1p | `sections/catcodes.tex:16–18` |
| T9 | `\uppercase\expandafter{\romannumeral …}` | 1p | `body/macros.tex:26`; `sections/catcodes.tex:23–24` |
| T10 | `\makeatletter` run by a macro before it reads its arguments | 1p (pkg) | `gmvenue.cls:44–49`; `sections/catcodes.tex:4–6` |
| T12 | `\ExplSyntaxOn … \ExplSyntaxOff` with `\seq_…` and `\cs_new…` | 1p (pkg) | `gmvenue.cls:34–41`; used at `body/paper.tex:48` |
| T13 | Catcode change in a group, with the definition escaping through `\gdef` | 9p (pkg) | `gmstyle.sty:12–16` |
| T14 | Brace remapping: `(` and `)` as group delimiters, `{` and `}` as other | 1p (pkg) | `gmstyle.sty:18–23`; `sections/catcodes.tex:12–13` |
| T15 | Active `"` shorthand, switched on by a macro inside a group and switched off again by another | 2p (pkg) | `gmstyle.sty:25–31`; `sections/catcodes.tex:7–9` |
| T16 | Active character defined through `\lccode` and `\lowercase` | 1p (pkg) | `gmstyle.sty:33–37`; `sections/catcodes.tex:10–11` |
| T17 | `\makeatletter` and `\makeatother` run by macros the author calls | 1p (pkg) | `gmstyle.sty:39–41`; `body/paper.tex:35–37` |
| T18 | `\endlinechar=-1` for the lines that follow the assignment | 16p (pkg) | `gmstyle.sty:43–48` |
| T19 | Catcode read with `\ifnum\catcode…`; active `~` rebound in a group | 9p, 10p (pkg) | `gmstyle.sty:50–51` |
| T20 | `^^J` in a message | 28p (pkg) | `gmstyle.sty:54` |

## Nested effects

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| N1, N2 | Wrapper main: `\documentclass` neutralised; the inner file has its own preamble and `\begin{document}` | 1p | `master.tex:11–12` → `body/paper.tex:1–3` |
| N3 | `\input` with an explicit `.tex` extension | 25p | `body/paper.tex:32` |
| N4 | Save-and-wrap `\bibliographystyle` | 1p | `master.tex:15–17` |
| N5 | File hooks set up inside a macro, named by base name though the input has a directory | 1p | `master.tex:19–23` (see the quirks section of `README.md`) |
| N6 | Dead input of a missing file | | `body/paper.tex:68` |
| N7 | Input inside a live conditional | 9p | `body/paper.tex:69` |
| N8 | Parametric input paths | 15p | `body/paper.tex:45–46` |
| N9–N12 | Local package → local package → configuration file, read twice | 63p local `.sty` | `master.tex:6`; `gmstyle.sty:4–5`; `gmtools.sty:5` |
| N13 | `\expandafter\endinput\fi` on one line | (language-core brief §10) | `gmstyle.cfg:2–3` |
| N14 | Definitions that define: `##` parameters, macros built with `\csname`, `\@namedef` | 29p, 2p, 4p, 1p | `body/macros.tex:36–46` |
| N15 | `\let` to `\relax` and `\undefined`, a `\let` chain, save-and-wrap of `\paragraph` | 70p, 11p, 5p, 2p | `body/macros.tex:47–55` |
| N16 | `\@ifstar`, `\@ifnextchar`, and a patch of an optional-argument internal through `\csname\string` | 3p, 1p, 1p | `body/macros.tex:56–61` |
| N17 | Bare `\input name` with a directory and an extension | 4p | `sections/nesting.tex:2–3` |
| N18 | Input depth 4 | 1p (35p reach depth 2) | `sections/nested/deeper.tex:3` |
| N19 | Explicit `\input` of a `.bbl` fragment | 1p | `master-plain.tex:46` |
| N20 | A name that resolves only through `\input@path` | 2p | `master.tex:9–10`; `sections/figures.tex:17–19` |

## Author macros

Every macro the fixture defines is also used, so parameter matching and body
expansion run, not only definition scanning.

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| M1 | Symbol aliases, and control-symbol names (`\1`) | 101p; 33p | `body/macros.tex:5–8` |
| M2 | `\DeclareMathOperator(*)`, `\DeclarePairedDelimiter(X)`, delimiter wrapper | 66p; 7p; 38p | `body/macros.tex:11–16` |
| M3 | xspace, annotation and `\providecommand` text macros | 24p, 91p, 18p | `body/macros.tex:17–21`; called at `sections/nesting.tex:9–12` |
| M4, M5 | Default for an optional argument; seven parameters, called with braced and single-token arguments | 21p; 2p | `body/macros.tex:20`, `:22`; called at `sections/nesting.tex:9–12` |
| M6 | Conditional and expansion control in bodies | 23p, 9p | `body/macros.tex:23–26` |
| M7 | Delimited parameters; a `#{` parameter | 9p; 1p | `body/macros.tex:27–30` |
| M8 | Comment macros (see K13 and K14) | | `body/macros.tex:31–34` |
| M9 | `\newenvironment`, `\newcolumntype`, theorems (shared counter, within section, starred) | 18p, 21p, 91p | `body/macros.tex:64–71`; `gmpacked` used at `sections/structure.tex:15` |
| M10 | `\renewcommand*` | 6p | `body/macros.tex:72` |
| M11 | The same name defined again | 54p | `body/macros.tex:76` |
| M12 | Definitions after `\begin{document}`, then used | 28p, 12p | `sections/math.tex:41–42` |
| M13 | Unbraced body | 7p | `body/macros.tex:9` |
| M14 | xparse `\NewDocumentCommand` with `s O{} m`, called starred with the optional argument and unstarred without it | 2p | `body/macros.tex:62`; `sections/nesting.tex:8` |
| M15 | Renewing a kernel control symbol (`\>`) | 6p | `body/macros.tex:10`; used at `sections/math.tex:34` |
| M18 | `\protected\def` | 1p (pkg) | `gmstyle.sty:53`; called at `sections/nesting.tex:9–12` |

## Math

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| X1 | `$…$`, `\(…\)`, `\[…\]`, `$$…$$` | 75p, 36p, 48p | `sections/math.tex:2–4` |
| X2 | equation, align(*), gather, split, subequations, multline, eqnarray, cases, dcases, pmatrix, bmatrix, array, `\newcolumntype` | see inventory §9 | `sections/math.tex:5–26` |
| X3 | `\choose`, `\over`, double subscript brace | 4p, 4p | `sections/math.tex:27–28` |
| X4 | Math alphabets (including mathrsfs `\mathscr`), operators, `\stackrel`, `\overset`, `\substack`, `\middle`, `\eqref`, `\text` | inventory §9 | `sections/math.tex:29–34` |
| X5 | UTF-8 quotes, dashes and × in the source | 45p, 35p, 5p | `sections/math.tex:39–40` |
| X7 | `\DeclareMathAlphabet` and `\SetMathAlphabet` | 13p | `body/macros.tex:73–75` |
| X8 | Accents (`\hat`, `\bar`, `\tilde`, `\vec`, `\dot`, `\widehat`, `\widetilde`, `\overline`, `\underline`); `\bigl`/`\Bigl` sizing; an unbalanced `\left.` … `\right\vert` | not counted; universal | `sections/math.tex:35–38` |
| X9 | `aligned` inside `equation`; `\intertext` inside `align` | 23p; 3p | `sections/math.tex:11`, `:14` |

## Document structure

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| S1 | Lists: enumitem labels (`(\roman*)`, `\textbf{\arabic*.}`), `leftmargin=*`, nesting, an `\item[…]` label, inline `enumerate*`, `description`, `\setlist` | enumerate 87p, itemize 77p, enumitem 71p, description 9p, `\setlist` 11p, `inline` 3p | `body/macros.tex:82`; `sections/structure.tex:2–15` |
| S2 | `table*` float with booktabs rules, `\multicolumn`, `\cmidrule(lr)`, `\multirow`, `\rowcolor` (xcolor `table` option), inside `\resizebox` | table 90p, table* 27p, booktabs 79p, `\cmidrule` 29p, `\multirow` 32p, xcolor `table` 23p, `\resizebox` 35p | `body/paper.tex:15`; `sections/structure.tex:16–31` |
| S3 | `algorithm` float with algpseudocode; renamed `\algorithmicrequire`; `\algnewcommand` | algorithm 76p, algpseudocode 40p; 17p; 5p | `body/macros.tex:77–80`; `sections/structure.tex:32–45` |
| S4 | Cross-references: `\label`, `\ref`, `\pageref`, `\cref`, `\Cref`, `\autoref`, `\hyperref[…]`, `\href`, `\texorpdfstring` in a title, `\phantomsection`, `\crefname`; cleveref after hyperref | cleveref 25p (`\cref` 16p, `\Cref` 10p, `\crefname` 8p), `\href` 29p, `\autoref` 4p, `\texorpdfstring` 3p, `\phantomsection` 3p | `body/paper.tex:30`; `body/macros.tex:81`; `sections/structure.tex:46–51` |
| S5 | Numbered `\footnote` inside a list item | universal | `sections/structure.tex:8` |
| S6 | `\appendix`: later sections are lettered | 80p | `body/paper.tex:67` |
| S7 | `\includegraphics` through `\graphicspath`, with and without an extension; `[H]` (float); subfigures (subcaption); `\captionsetup` | `\includegraphics` 126p, `\graphicspath` 12p, float 69p, subcaption 69p, `subfigure` 32p, `\captionsetup` 12p | `body/paper.tex:31`; `body/macros.tex:83`; `sections/figures.tex:2–13` |
| S8 | The upper-case `algorithmic` dialect (`\STATE`, `\FOR`), which can't share a document with algpseudocode | algorithmic 38p (`\STATE` 18p) | `master-plain.tex:7`, `:18–23` (C) |

## Bibliography

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| B1 | Kernel `\cite` forms shared by every dialect | 117p | `sections/cite-shared.tex`, read by every root |
| B2 | natbib `\citet`, `\citep[pre][post]`, `\citealp`, `\citeauthor`, `\citeyearpar`, `\nocite`; `\natexlab` year suffixes | 101p; 24p | `sections/cite-natbib.tex` (A and D) |
| B6, B7 | `\bibliographystyle` chosen by a class flag and rebound by the wrapper | 18p | `gmvenue.cls:22`; `body/paper.tex:72` (A) |
| — | `.bib` plus jobname `.bbl` (plainnat form: `\natexlab`, braced labels, `urlstyle` header) | 45p | `refs.bib` + `master.bbl` (A) |
| B8 | `.bib` data: `@string` with `#`, `@preamble`, `@comment`, `crossref`, month macro, quoted values, upper-case type, `{{…}}`, corporate author, `and others`, accents, math, key with `:` and `/`, non-ASCII, `@software` with `date` | see inventory §10 | `refs.bib` |
| B9 | biblatex with `\addbibresource{x.bib}`; `\entry`-record `.bbl` | 4p | `master-biblatex.tex:5–6` + `master-biblatex.bbl` (B) |
| B10 | `\textcite`, `\parencite[…]`, `\autocite`, `\citeauthor` | | `master-biblatex.tex:9–13` (B) |
| B3 | `cite` package over kernel `\cite` | 12p | `master-plain.tex:5` (C) |
| B4 | Inline `thebibliography`: numeric and alpha labels, `{\em}`, `\newblock`, `\url`, a macro defined in the list, a commented-out entry | 6p; 2p alpha | `master-plain.tex:24–47` (C) |
| B5 | Pasted `dcu.bst` `\harvarditem` entries, with kernel stand-ins | 16p | `master-plain.tex:8–13`; `bib/pasted-dcu.bbl` (C) |
| B11 | The arXiv pattern: `\bibliography` names a stripped database and only the jobname `.bbl` ships | 41p | `master-arxiv.tex:10` + `master-arxiv.bbl` (D; see `README.md` for how it is checked) |

## Encoding and generated inputs

| Tag | Case | Gauntlet | Fixture |
| --- | --- | --- | --- |
| E1 | CRLF line endings | 7p | `sections/nested/deepest.tex` (see `.gitattributes`) |
| E2 | matplotlib `.pgf`: `\catcode` of `^` and `%` changed inside a `\pgftext` box body | 4p | `figures/plot.pgf:23`; `sections/figures.tex:14–16` |
| E3 | Inkscape `.pdf_tex`: `\providecommand\color` that refers to itself, `\global\let\svgwidth\undefined` | 1p | `figures/drawing.pdf_tex`; `sections/figures.tex:17–19` |

## Not exercised

| Case | Gauntlet | Why |
| --- | --- | --- |
| `.bbl` under a name other than the jobname; several `.bbl` files | 1p, 2p | The `.bbl` would be inert, and nothing reads it |
| apacite | 4p | It would be a fifth root; left out as proposed |
| `\input` that resolves only case-insensitively, or only relative to the including file | 1p, 1p | TeX fails on these on a case-sensitive file system, or anywhere for the second |
| `\include`, `\subfile`, `\import` | 0p | Never used in the gauntlet |
| `\scantokens`, `\ExplSyntaxOn` in author files, babel shorthands | 0p | Never used in the gauntlet |
| `\usepackage` while `\makeatletter` is in force | 2p | T3 covers `@`-letter reading across an `\input`; a preamble variant would add little |
| Duplicate `.bib` keys | 11p | BibTeX treats a repeated entry as an error |
| The `twocolumn` class option | most venue styles | A layout mode with no source-level effect beyond `\if@twocolumn`, whose branch is decided by the option; S2's `table*` covers the starred-float syntax |
| Packages used only for their layout or fonts (fancyhdr 37p, authblk 43p, setspace 28p, times 29p, lmodern 10p and similar) | | No source-level behaviour beyond a load and an option list, which P1–P3 and P12 already cover |
