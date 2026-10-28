> **Moved, 2026-10-27.** The fixture is now `tests/fixtures/specimens/gauntlet-master/`;
> the links in the review below point to its old location.
>
> **Status, 2026-10-27 (Claude).** Addressed in the fixture by LaTeXAI `df434f8`, the commit that
> follows `a7051a9`. Every root still compiles clean with Tectonic 0.16.9.
> - **Accepted.** §2 A–E: added `sections/structure.tex` (S1–S5) with lists,
>   a `table*` with booktabs, multirow and `\rowcolor`, an algpseudocode
>   algorithm, cross-references and a numbered footnote; math accents, sizing,
>   `aligned` and `\intertext` (X8, X9). §3: every listed macro is now called.
>   The `\gmstarred` call was wrong, as you said (`[y]` was left as text); it is
>   now `\gmstarred*[y]{x}`, plus an unstarred call. §4.1: added root D,
>   `master-arxiv.tex`. §4.3: `\appendix` before the extras and the tail (S6).
> - **Added beyond the review.**
>   - `\gmdqoff`, `\>` and `\gmlate` were also never used.
>   - There was no live `\includegraphics` (126p). S7 adds one, through
>     `\graphicspath`, with an `[H]` float and subfigures.
>   - geometry (82p) and microtype (53p) are now loaded (P12).
>   - The upper-case `algorithmic` dialect is in root C (S8), because it can't
>     share root A with algpseudocode.
> - **Not taken.** The `twocolumn` option is a layout mode with no source-level
>   effect beyond the option-decided `\if@twocolumn`; `table*` covers the
>   starred-float syntax.
> - **Corrections to the counts.** The inventory has figure* in 35 papers and
>   table* in 27, not 78; `\appendix` is in 80, not 100+. There is no Tectonic
>   oracle for root D as committed: even `--reruns` reruns BibTeX. It is checked
>   by restoring the stripped `.bib` in a staged copy (fixture README).

Listed directory gauntlet-master
Listed directory gauntlet
Viewed README.md:1-68
Searched for "gauntlet-master-inventory"
Searched for "gauntlet-master-inventory"
Viewed coverage.md:1-193
Searched for "gauntlet-master-inventory"
Viewed inventory.jsonl:1-20
Listed directory issues
Listed directory LaTeXAI
Ran command: `Get-ChildItem -Path D:\ -Filter "*gauntlet-master-inventory*" -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName`
Listed directory aghado01-issues
Listed directory TeXDig
Searched for "gauntlet"
Searched for "gauntlet-master-inventory"
Viewed gauntlet-master-inventory-20261027.md:1-250
Viewed gauntlet-master-inventory-20261027.md:251-450
Viewed gauntlet-master-inventory-20261027.md:451-565
Viewed gauntlet-package-obligations-20261027.md:1-100
Listed directory body
Listed directory sections
Listed directory nested
Listed directory figures
Listed directory listings
Listed directory bib
Viewed master.tex:1-25
Viewed paper.tex:1-68
Viewed macros.tex:1-82
Viewed gmvenue.cls:1-52
Viewed gmstyle.sty:1-57
Viewed gmtools.sty:1-8
Viewed gmstyle.cfg:1-6
Viewed comments.tex:1-38
Viewed branches.tex:1-22
Viewed verbatim.tex:1-44
Viewed catcodes.tex:1-24
Viewed nesting.tex:1-10
Viewed deeper.tex:1-4
Viewed deepest.tex:1-3
Viewed figures.tex:1-14
Viewed math.tex:1-41
Viewed cite-shared.tex:1-6
Viewed cite-natbib.tex:1-7
Viewed tail.tex:1-6
Viewed extras.tex:1-4
Viewed master-biblatex.tex:1-16
Viewed master-plain.tex:1-42
Viewed refs.bib:1-78
Viewed plot.pgf:1-30
Searched for "tabular"
Searched for "booktabs"
Searched for "figure"
Searched for "includegraphics"
Searched for "algorithm"
Searched for "enumerate"
Searched for "gmpacked"
Searched for "texorpdfstring"
Searched for "widehat"
Searched for "\\hat"
Searched for "gmfix"
Searched for "gmname"
Searched for "gmseven"
Searched for "gmcard"
Searched for "gmrobust"
Listed directory gauntlet-master-inventory-20261027
Viewed gauntlet_scan.py:1-120
Viewed summ.py:1-46
Ran command: `python -c "import json; f = json.load(open('features.json', encoding='utf-8')); print(list(f.keys()))"`
Viewed gauntlet_scan.py:121-260
Viewed gauntlet_scan.py:261-450
Viewed gauntlet_scan.py:451-600
Searched for "def "
Viewed gauntlet_scan.py:601-750
Viewed gauntlet_scan.py:751-900
Viewed gauntlet_scan.py:901-1050
Viewed gauntlet_scan.py:1051-1200
Viewed gauntlet_scan.py:1201-1350

An analysis of [gauntlet-master](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master) against the 147 paper source trees in [supellex-private/gauntlet](file:///d:/aghado01/codex-scientiae/supellex-private/gauntlet), cross-referenced with the survey data in [gauntlet-master-inventory-20261027.md](file:///d:/aipithicus/aipithicus-issues/LaTeXAI/reports/gauntlet-master-inventory-20261027.md) and [coverage.md](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/coverage.md), reveals several key gaps.

---

### 1. Architectural Assessment

`gauntlet-master` delivers **coverage of low-level TeX stressors**:
- Catcode trickery (`\catcode` remappings in groups, PGF `\pgftext` active `%`/`^`, `\lccode` lowercase tricks, `\ExplSyntaxOn`).
- Macro and definition edge cases (`##` parameters, delimited parameter scanning `#{`, `\let` chains, `\csname` definition and testing).
- Multi-tier nested inputs (depth 4, bare `\input name`, wrapper main neutralising inner mains, CRLF handling).
- The three-root bibliography split for `natbib`, `biblatex`, and inline `thebibliography` + `dcu` harvard items.

However, there is an **asymmetry between micro-TeX hacks and the structural workhorses of scientific papers**. The fixture currently exercises low-level tokenization stressors heavily, but omits or under-represents several common constructs found across the 147 gauntlet papers (e.g., complex tables, algorithms, list structures, cross-referencing, and math accents).

---

### 2. Major Functional Gaps

#### A. Tables & Tabular Machinery (Massive Corpus Gap)
In the gauntlet corpus, tables are among the top causes of AST and layout failures:
- **Corpus Frequency**: `booktabs` (79p), `multirow` (70p), `array` (49p), `\midrule` (65p), `\toprule` (63p), `\bottomrule` (63p), `\cmidrule` (29p), `\multirow` (32p), `\newcolumntype` (21p), `\resizebox` wrapping tabulars (35p), `xcolor` cell/row coloring (23p).
- **Current Fixture State**: Only a single inline math array appears in [math.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/math.tex#L24) (`\begin{tabular}{CC} \alpha & \beta \end{tabular}`). There is **no `table` float, no `booktabs` rules, no `\multicolumn`, no `\multirow`, and no `\cmidrule(lr){c1-c2}`**.
- **Integration**: Add a compact 3-row table inside a `\begin{table}[t]` float that exercises:
  ```latex
  \begin{table}[t]
  \centering\small
  \begin{tabular}{l c r}
    \toprule
    \multicolumn{2}{c}{\textbf{Span Header}} & \textbf{Value} \\
    \cmidrule(lr){1-2}\cmidrule(lr){3-3}
    \multirow{2}{*}{Group} & Item A & 10.5 \\
                           & Item B & 20.0 \\
    \bottomrule
  \end{tabular}
  \caption{Benchmark comparison.}\label{tab:sample}
  \end{table}
  ```

#### B. Algorithms & Pseudocode (Completely Absent)
- **Corpus Frequency**: 76 papers use `algorithm` / `algorithmic` / `algpseudocode` / `algorithm2e`. `\State` (23p), `\STATE` (18p), `\renewcommand\algorithmicrequire` (17p).
- **Current Fixture State**: **0 occurrences** across all roots.
- **Why this stresses engines**: Algorithms create custom floating blocks, redefine `\\`, alter indentation/counter state, and mix math with pseudo-code tokens.
- **Integration**: Load `algorithm` and `algpseudocode` (or define a minimal compliant mock block if avoiding CTAN bloat) with a 4-line algorithm exercising `\Require`, `\For`, `\State`, and `\EndFor`.

#### C. Lists & Enumerations (Defined but Unexecuted)
- **Corpus Frequency**: `enumitem` (71p) with label formatting (`[label=(\roman*)]`, `[label=\textbf{\arabic*.}]`, `[leftmargin=*]`).
- **Current Fixture State**: [macros.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L65) defines `\newenvironment{gmpacked}{\begin{itemize}...}{...}`, but **neither `gmpacked`, `itemize`, `enumerate`, nor `description` is ever invoked in live text** (the only `\begin{itemize}` is inside a dead `\iffalse` block in [comments.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/comments.tex#L19)).
- **Integration**: Instantiate a live nested list with custom `\item[...]` and roman numerals in `sections/nesting.tex` or `sections/extras.tex`.

#### D. Cross-Referencing & Anchors
- **Corpus Frequency**: `\ref` and `\pageref` (universal); `cleveref` (16p: `\cref`, `\Cref`); `hyperref` (58p: `\autoref`, `\phantomsection`, `\href{url}{text}`).
- **Current Fixture State**: Only `\eqref{eq:one}` in [math.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/math.tex#L32).
- **Missing Stressor**: `\ref{sec:...}`, `\pageref{...}`, `\href{https://...}{link text}` (only bare `\url` is tested in verbatim), and section headings containing math requiring `\texorpdfstring{$X$}{X}` to suppress hyperref bookmark warnings.

#### E. Math Accents & Delimiter Sizing
- **Corpus Frequency**: Estimators, sample means, and vector accents are standard across STEM papers (`\hat`, `\bar`, `\tilde`, `\vec`, `\widehat`, `\widetilde`, `\overline`). Delimiter sizing like `\bigl( \dots \bigr)` and unbalanced delimiters (`\left. \dots \right\vert`).
- **Current Fixture State**: [math.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/math.tex) has **zero math accents**, no `aligned` nested inside `equation` (23p in gauntlet), no `\intertext` (breaks display math columns with text paragraphs), and no `\left. \dots \right\vert`.
- **Integration**: Add $\hat{\theta}$, $\bar{X}$, $\vec{v}$, $\left. \frac{\partial f}{\partial x} \right\vert_{x=0}$, and an `\intertext{and for all }` clause inside `align`.

---

### 3. "Declared-but-Uncalled" Inventory Anchors

Several tags listed in [coverage.md](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/coverage.md) point to definitions in [macros.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex) or [gmstyle.sty](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/gmstyle.sty), but are **never invoked in document bodies**. A parser or macro expansion engine will parse their definition signatures, but never evaluate parameter matching or body expansion during document processing:

| Tag | Case | Defined at | Status |
| --- | --- | --- | --- |
| **M4** | Optional argument default | [macros.tex:20](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L20) (`\gmcard`) | **Never called** in any `.tex` body |
| **M5** | Seven parameters | [macros.tex:22](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L22) (`\gmseven`) | **Never called** in any `.tex` body |
| **M3** | xspace macro | [macros.tex:18](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L18) (`\gmname`) | **Never called** in any `.tex` body |
| **M3** | Margin note / annotation | [macros.tex:19](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L19) (`\gmfix`) | **Never called** in any `.tex` body |
| **M3** | `\providecommand` | [macros.tex:21](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L21) (`\gmagent`) | **Never called** in any `.tex` body |
| **M9** | `\newenvironment` | [macros.tex:65](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L65) (`\begin{gmpacked}`) | **Never called** in any `.tex` body |
| **M18**| `\protected\def` | [gmstyle.sty:53](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/gmstyle.sty#L53) (`\gmrobust`) | **Never called** in any `.tex` body |
| **M14**| xparse `\gmstarred` | [macros.tex:62](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/macros.tex#L62) | Signature is `s O{} m`. Invocation in [nesting.tex:8](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/nesting.tex#L8) is `\gmstarred*{x}[y]`; because `{x}` precedes `[y]`, it assigns `#3=x`, leaving `#2` default empty and trailing `[y]` unparsed. |
| — | Standard `\footnote` | — | Only unnumbered `\gmblfootnote` is called. Standard numbered footnotes are absent. |

---

### 4. Corpus Stressors Excluded in "Not Exercised"

In [coverage.md:181-193](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/coverage.md#L181-L193), several real-world patterns were categorized as "Not exercised" due to Tectonic constraints:

1. **The 41-Paper arXiv Pattern (Missing `.bib` with Shipped `.bbl`)**:
   - In arXiv tarballs, `.bib` files are often dropped/stripped while the generated `.bbl` is shipped. Authors keep `\bibliography{refs}` in their LaTeX source.
   - `coverage.md` omitted this because Tectonic attempts to rerun BibTeX and fails when the `.bib` database is missing.
   - *Recommendation*: Keep this out of Root A/B/C so Tectonic remains green as the oracle, but add a companion root `master-arxived-bbl.tex` (Root D) or an engine test specifically verifying that PyTeXML resolves citations directly from the local `.bbl` when `.bib` is absent.
2. **Two-Column Layout & Starred Floats**:
   - Most venue styles in the gauntlet use two-column layouts. [gmvenue.cls:48](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/gmvenue.cls#L48) implements `\gm@twocoltest`, but `master.tex` passes `11pt` without `twocolumn`. Consequently, the `\if@twocolumn` branch is permanently dead.
   - Starred floats (`\begin{figure*}` and `\begin{table*}` spanning two columns) appear in 78 gauntlet papers, but 0 in the fixture.
3. **Appendix Reset**:
   - 100+ gauntlet papers use `\appendix \section{Proofs}`, resetting the section counter to alphabetical (`Appendix A`, `A.1`). Adding `\appendix` before `sections/tail.tex` would directly validate counter-reset handling.

---

### 5. Recommended Consolidation Blueprint

To integrate these stressors into `gauntlet-master` while preserving Tectonic 0.16.9 compatibility:

1. **In [body/paper.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/body/paper.tex)**:
   - Add `\usepackage{booktabs,multirow}` to package imports.
   - Insert `\appendix` right before `\input{sections/tail}` to test section counter alphabetization.
2. **In [sections/math.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/math.tex)**:
   - Add common math accents and delimiters:
     ```latex
     $\hat{\theta}, \bar{x}, \tilde{y}, \vec{v}, \widehat{AB}, \left. \frac{\partial f}{\partial x} \right\vert_{x=0}, \bigl( x + y \bigr)$
     ```
   - Add an `aligned` block inside `equation`, and an `\intertext{where}` line inside `align`.
3. **In [sections/figures.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/figures.tex)**:
   - Add a compact `booktabs` + `multirow` + `\multicolumn` table with `\caption` and `\label`.
4. **In [sections/nesting.tex](file:///d:/aipithicus/LaTeXAI/python/PyTeXML/tests/fixtures/gauntlet-master/sections/nesting.tex)**:
   - Exercise the currently uncalled macros:
     ```latex
     \gmname \gmcard[Warning]{Pay attention} \gmagent{Antigravity} \gmseven{1}{2}{3}{4}{5}{6}{7}
     \begin{gmpacked}\item First item\item Second item with footnote\footnote{A numbered note.}\end{gmpacked}
     \href{https://example.org}{Example Link}, \ref{tab:sample}, \pageref{eq:one}.
     \gmrobust
     ```
   - Correct the `\gmstarred` call to match its signature: `\gmstarred*[default-opt]{mandatory}`.