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
3. **LuaTeX.** This is the only step that adds a runtime dependency. Start with the token-level API that the kernel and expl3 need, and grow from there as your corpus actually requires.