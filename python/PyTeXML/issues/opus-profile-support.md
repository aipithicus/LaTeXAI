"LaTeX3" started in the late 1980s as the name for a planned successor to LaTeX2e. That successor was never released as a separate format. The LaTeX team built its pieces and gradually merged them into ordinary LaTeX instead. So today the name mostly refers to those pieces:

- **expl3, the programming language.** It ships in the LaTeX kernel itself, loaded by default since the 2020-02 release. Code looks like this:

  ```latex
  \ExplSyntaxOn
  \cs_new:Npn \my_double:n #1 { #1 #1 }
  \tl_new:N \l_my_name_tl
  \tl_set:Nn \l_my_name_tl { world }
  \ExplSyntaxOff
  ```

  Names follow the pattern `\module_description:signature`. The letters after the colon describe each argument:
  - `n`: a braced argument
  - `N`: a single token
  - `V`: the value of a variable
  - `e`/`x`: expanded first
  - `T`/`F`: branches taken on true or false

  Variants such as `\tl_set:NV` are generated automatically from a base function by `\cs_generate_variant:Nn`.

- **Interfaces built on expl3, now in the kernel.**
  - `\NewDocumentCommand` (xparse, now called ltcmd) arrived in 2020-10, with argument specifications like `s o m`.
  - The hook system (`\AddToHook`, lthooks) arrived in the same release.
  - Key-value package options (`\DeclareKeys`, `\ProcessKeyOptions`) came later.

- **l3build**, the team's test tool, which has the `.lvt` and `.tlg` regression files I mentioned earlier.

For PyTeXML, it matters in four ways:

- **It's a catcode regime.** `\ExplSyntaxOn` makes `_` and `:` letters, makes spaces and newlines ignored, and turns `~` into a space. That's one of the few common regimes your L4 reading model should treat as a known transition, not an arbitrary write.
- **Much of it is generated, not written out.** Variants and many kernel functions are created by executing code rather than appearing as literal definitions. This is the harvest-versus-evaluate distinction from earlier.
- **It sets your engine baseline.** Current expl3 requires e-TeX plus `\expanded`, which is why L2 chose that identity. Which string-comparison primitive it uses depends on the engine profile.
- **Modern packages lean on it.** Newer packages, and the kernel's own newer features, are written in expl3. This is the shift behind arXiv's statement that HTML conversion success slipped as dependencies migrated to newer LaTeX 3 definitions. Its argument-specification language is the same one your ontology brief proposed for binding signatures.


Think of a profile as four independent choices, and only one of them is the engine:

1. **Engine:** pdfTeX, XeTeX or LuaTeX. All three are built on e-TeX, which is built on Knuth's TeX.
2. **Output mode:** pdfTeX can produce DVI (the classic `latex` command) or PDF (`pdflatex`).
3. **Format:** plain TeX, LaTeX2e, or LaTeX2e's compatibility mode for LaTeX 2.09's `\documentstyle`, which shows up in older arXiv papers.
4. **TeX Live year:** this sets the kernel and package versions.

For your purposes, only LuaTeX needs a second programming language. pdfTeX and XeTeX are pure TeX plus data tables.

## The shared base

Every profile needs all of this.

**Knuth TeX core:**
- expansion and conditionals
- grouping
- catcodes and the reader parameters
- registers and allocation
- `\csname`, `\afterassignment`, `\aftergroup`, `\futurelet`
- I/O: `\openin`, `\read`, `\ifeof` and `\write`, which `\IfFileExists` and friends depend on
- fonts, boxes and other typesetting primitives as sinks that still consume their operands exactly

**e-TeX extensions:**
- `\protected`, `\detokenize`, `\unexpanded`
- `\numexpr`, `\dimexpr`, `\glueexpr`, `\muexpr`
- `\ifdefined`, `\ifcsname`, `\iffontchar`, `\unless`
- `\scantokens`, `\readline`, `\everyeof`
- `\currentgrouplevel`, `\currentiftype` and related introspection
- register numbers up to 32767

**`\expanded`:** shared by all three engines since 2019, and required by current expl3.

**The LaTeX kernel**, including expl3, hooks and ltcmd, which is engine-neutral apart from small engine-specific branches.

## Per engine

| | pdfTeX | XeTeX | LuaTeX |
| :--- | :--- | :--- | :--- |
| Identity probes | `\pdftexversion`, `\pdfoutput` → `\ifPDFTeX`, `\ifpdf` | `\XeTeXversion` → `\ifXeTeX`, `\iftutex` | `\directlua`, `\luatexversion` → `\ifLuaTeX`, `\iftutex` |
| Input model | Bytes. UTF-8 handled by inputenc: each byte is active and expands to LaTeX's internal character representation (LICR), e.g. `\'e` | Native Unicode | Native Unicode |
| Initial character data | 8-bit tables | Unicode data loaded by the format: catcodes, case codes and math codes for every code point | Same as XeTeX |
| String and utility primitives | `\pdfstrcmp`, `\pdfmdfivesum`, `\pdffilesize`, `\pdffilemoddate`, `\pdfescapestring` family, `\pdfuniformdeviate`, `\pdfprimitive`, `\pdfmatch` | The same set without the `pdf` prefix: `\strcmp`, `\mdfivesum`, `\filesize`… | Mostly absent. Kernel, expl3 and pdftexcmds supply them through Lua |
| Math | 8-bit `\mathchardef`, `\mathcode` | `\Umathchardef`, `\Umathcode`, `\Uchar`; unicode-math | Same as XeTeX |
| Reading effects unique to the engine | Output mode decides driver selection, including which graphics extensions `\includegraphics` searches (`.eps` under DVI; `.pdf`, `.png`, `.jpg` under PDF) | `\XeTeXcharclass` with `\XeTeXinterchartoks` inserts tokens between characters of given classes (xeCJK uses it) | The `process_input_buffer` callback rewrites lines before tokenization; file-finding callbacks change resolution |
| Second language | None | None | **Lua 5.3**, plus the LuaTeX libraries |
| Typesetting surface to sink | Font encodings (fontenc `.def` files), PDF primitives | fontspec and OpenType fonts, `\XeTeXglyph` | luaotfload, node library, `\latelua`, mplib (MetaPost) |
| On arXiv | The default for nearly all LaTeX until late 2025 | Supported since November 2025 | Under consideration as of that announcement |

## What each engine adds to your work

**pdfTeX: data tables, no new language.**
- Stop text characters at LICR. `\'e` and `\textquotedblleft` are your text-side lexical floor.
- Map LICR to Unicode with a table. You can get one by inverting inputenc's UTF-8 definition files, which run in your engine anyway.
- Model DVI versus PDF mode explicitly, because it changes which asset file a paper actually used. That matters for your asset resolution.

**XeTeX: more data tables, no new language.**
- The Unicode character data, which you can generate from the Unicode Character Database or vendor from TeX Live's unicode-data package.
- unicode-math's tables for `\Umathcode` and its alphabets.
- Inter-character tokens as a reader-level mechanism, which only matters for CJK papers.
- Tectonic serves as your oracle.

**LuaTeX: an embedded Lua 5.3 runtime and a slice of LuaTeX's API.**
- In Python, lupa embeds Lua. You'd also need LPeg available in that runtime, because LuaTeX-oriented packages use it heavily.
- The reading-relevant libraries:
  - `tex`: `print` and `sprint` inject tokens; register access
  - `token`: scanners, `create`, `get_macro`, `set_macro`
  - `texio`
  - `lua`: function tables behind `\luafunction`
  - `kpse`, `status`, `lfs`
  - `md5` and `sha2`
  - Unicode string helpers
- `\directlua` is expandable, so it can appear inside an `\edef`.
- Under LuaTeX even vanilla LaTeX calls Lua. The kernel's `ltluatex` and expl3's utility functions run through it, so a LuaTeX profile without a Lua runtime fails before any user package loads.
- Scope `callback`, `node`, `font` and `mplib` as residue or sinks. They are mostly typesetting, and `mplib` is a whole MetaPost interpreter, so luamplib figures should be opaque islands.

## Format and year

- **Format.** LaTeX2e is the main target. Plain TeX papers exist in older arXiv, and LaTeX 2.09 compatibility mode is handled by the kernel's own compatibility code, which your engine will run. ConTeXt is a different world on its own engine (LuaMetaTeX) and isn't an arXiv compiler, so I'd leave it out.
- **TeX Live year.** arXiv currently offers the 2025 release and the previous 2023 one, and older papers were compiled with older releases. Record the year as part of the profile, and treat any gap from your lib-ctan pins as a named assumption.

## Order I'd build them in

1. **e-TeX base plus pdfTeX, both output modes.** This covers nearly the whole arXiv corpus, needs no second language, and the inputenc/LICR work is just your engine running kernel code.
2. **XeTeX.** Your Unicode reading model already exists in D4, and XeTeX adds Unicode data tables, the `\U…` math primitives, unicode-math and inter-character tokens. It also brings an oracle you already have.
3. **LuaTeX.** This is the only step that adds a runtime dependency. Start with the token-level API that the kernel and expl3 need, 

Profile support means splitting the work into two kinds of surface.

**Closed surfaces can be specified completely, so target completeness.** These are the e-TeX and TeX primitives, the pdfTeX and XeTeX extension primitives, the LaTeX kernel and expl3 for each TeX Live year, and LuaTeX's Lua API. Each is a finite, documented set, so "support it as needed" is the wrong posture. Users should be able to trust that a primitive or kernel function behaves exactly like TeX, without checking which ones you happened to implement.

**Open surfaces can't be completed, so publish coverage measured on a population.** These are the package ecosystem and author code. Nobody covers all of CTAN. A credible tool states its coverage on a defined, representative population and reports it every release. arXiv does this for its HTML: it prioritizes from missing-package statistics gathered across the whole historical corpus, and it publishes its rate of error-free conversion against a stated target. Demand-driven development is fine here, as long as the demand is measured across the population your users care about, not your own reading list.

| Surface | Kind | Target | Evidence |
| :--- | :--- | :--- | :--- |
| TeX + e-TeX primitives | Closed | Complete | Differential tests per primitive against a real engine (Tectonic, plus pdftex in a container) |
| pdfTeX and XeTeX extensions | Closed | Complete for reading semantics; typesetting primitives consume their operands exactly and act as sinks | Same |
| LaTeX kernel + expl3, per TeX Live year | Closed | Complete | The LaTeX team's own l3build regression suites: pass rate per release |
| LuaTeX Lua API | Closed but large | A published tiered contract, stated up front | Compatibility matrix plus tests per tier |
| Packages | Open | Population-weighted coverage | Stratified sample of arXiv by year and category; per-release report with the top missing packages ranked by usage |
| Author code | Open | Exact on everything executed; typed residue for the rest | Soundness checks: every "complete" claim is compared against the oracle |

For LuaTeX, the grown-up version of my earlier advice is a contract, not an order of implementation:

- **Tier 1 (full support):** `tex`, `token`, `texio`, `lua`, `kpse`, `status`, and the string and hash helpers. This is everything the kernel and expl3 need.
- **Tier 2 (named subset):** `process_input_buffer` and the file-finding callbacks.
- **Declared out of scope:** `node`, `font` and `mplib`, documented as typesetting, with a typed residue code for each.

You can publish that contract before writing any of it. That tells users what they're getting.

The build order stays the same, but the reason changes: pdfTeX first because arXiv compiled LaTeX almost exclusively with pdfLaTeX for decades, which is population weight, not personal need.

For the population itself, arXiv's bulk source archive on S3 (requester-pays) gives you the whole corpus. A fixed stratified sample drawn from it, frozen and versioned the way your G1 inventory was, becomes the denominator for every coverage claim.

Beyond coverage, these are what make the tool usable by others:

- a compatibility matrix in the docs, covering profiles × TeX Live years × tiers
- a versioned IR schema and a stable CLI, with a deprecation policy
- engine-profile data pinned per TeX Live year, so results are reproducible
- a per-paper report saying which profile was used and what remained unresolved
- a license audit of whatever CTAN material ships inside the wheel