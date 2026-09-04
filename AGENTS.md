# AGENTS.md — Working Guidance & Conventions

Behavioral expectations, development loop, and repository conventions for AI agents operating in the **LaTeXAI** repository: a local fork of LaTeXML (upstream v0.8.8, revision `ee4b3640`) shaped to return the object a manuscript compiler consumes, rather than HTML or MathML.

---

## 1. Context Routing Map

| Need / Topic | Primary Reference |
| :--- | :--- |
| **Local planning, charter, journal** | `DocOps.md` (gitignored, if present). Track planning lives outside this repo; never link private paths from tracked files. |
| **Upstream engine documentation** | `README.pod`, `INSTALL`, `doc/manual/` (the 0.8.8 manual; `manual.pdf` at top level) |
| **Engine layers** | `lib/LaTeXML/Core/` (Mouth → Gullet → Stomach → Document), `lib/LaTeXML/Common/` (Locator, Model, Config), `lib/LaTeXML/Engine/` (`*.pool.ltxml`), `lib/LaTeXML/Package/` (461 bindings, `*.sty.ltxml` / `*.cls.ltxml`) |
| **Math parsing** | `lib/LaTeXML/MathGrammar` (Parse::RecDescent source), `lib/LaTeXML/MathParser.pm`; compiled grammar lands in `blib/lib/LaTeXML/MathGrammar.pm` |
| **Post-processing (oracles only)** | `lib/LaTeXML/Post/` — MathML, UnicodeMath, LexMath. Read as instruments; not the product surface. |
| **Schema** | `lib/LaTeXML/resources/RelaxNG/` |
| **Tests** | `t/*.t` drivers over `t/<suite>/*.tex` + `*.xml` reference pairs (`LaTeXML::Util::Test`) |
| **Fork history** | `git log` from the root commit `414081a` (pristine upstream baseline). Every change is a reviewable diff against that commit. |

---

## 2. Development Loop

**Run through the `pwsh_exec` MCP.** Its PowerShell profile sources `latexAI-aliases.ps1` from `science-facility/mcp/pwsh_exec/scripts/pwsh/`, which resolves Strawberry Perl from the dedicated `$env:PERL_ROOT` (User scope; `PERL_HOME` is its `perl\` subdirectory) and points every CLI at this checkout with `-I lib -I blib/lib`. Ambient `PATH` is bypassed on purpose: the Bash tool and MSYS resolve a different `perl` first, and stock LaTeXML is not installed anywhere. If the aliases warn that `PERL_ROOT` is unset, the shell was launched without the User environment; fix the launch, do not hardcode a path.

| Alias | Expands to | Use |
| :--- | :--- | :--- |
| `lxml` | `perl -I lib -I blib/lib bin/latexml` | digest a file or `literal:` string to `ltx` XML |
| `lxmlp` | `… bin/latexmlpost` | post-processing, only when an oracle comparison needs it |
| `lxmlc` | `… bin/latexmlc` | combined driver |
| `ltst` | `prove -I lib -I blib/lib` | run test drivers, e.g. `ltst t/40_math.t` |
| `lmath '<tex>' [-Preload x] [-Capture]` | `lxml [--preload=x] [--capture] literal:<tex>` | quick math probe |

Facts that save a round trip:

- Set the working directory to the repo root first (`Set-Location D:\aipithicus\LaTeXAI`); the aliases carry absolute paths, but `latexml` writes `<jobname>.latexml.log` into the current directory.
- The version flag is `--VERSION` (uppercase). `--version` prints usage.
- `blib/lib` holds only the compiled `MathGrammar.pm` and `Version.pm`; bindings and pools are read from `lib/`. After editing the grammar, regenerate with `perl Makefile.PL` then `gmake` (about 20 s).
- **No TeX distribution is installed.** Passthrough and hybrid bindings (tikz, pgfplots, algorithmic, xcolor, listings, cleveref, …) try to load the raw `.sty` via `kpsewhich` and error out. Real-paper runs need `--includestyles` plus a preload binding that raises `MAX_ERRORS` and turns on `LEXEMATIZE_MATH`; toy probes with `lmath` do not.
- `--capture` (fork feature) emits `capture:*` provenance attributes on every element and `capture:source` on `ltx:Math`. `--noparse`, `--tex` and `--preload` are unchanged upstream switches; `--tex` output is the expansion oracle for drift measurements.
- Fallback without the aliases: `& "$env:PERL_ROOT\perl\bin\perl.exe" -I lib -I blib/lib bin/latexml …`.

---

## 3. Working Culture & Behavioral Guidance

- **One object, not patches.** The fork exists to make the engine return one well-defined object: the `ltx` document, extended with a capture namespace and a ledger. Judge every change by whether it serves that contract.
- **Reuse the 455 upstream bindings' output shape.** New structural bindings model themselves on an existing one (`amscd.sty.ltxml` for diagrams, the `\lx@gen@matrix@bindings` family for arrays) and keep the schema valid.
- **Foreign namespace for capture.** Provenance goes in namespaced attributes (`capture:`), which bypass RelaxNG validation; `ltx`-namespace additions require a schema change and a decision.
- **Deliberately unchanged:** `MathParser`, the MathML and other post-processors, reversion semantics beyond fidelity fixes, and every existing binding's output. Treat these as oracles.
- **Verbatim means verbatim.** Source slices come from the Mouth's recorded token positions, never from re-parsing or regex-guessing delimiters. Grapheme columns are the engine's native unit; byte offsets must be minted at read time, not derived downstream.
- **Preserve residue.** A formula the grammar rejects stays a wrapped token sequence with `ltx_math_unparsed`; a cell that fails degrades alone. Never auto-repair or silently drop.
- **Escalate tool inaccuracies.** When a test driver, the harness, or Perl itself misbehaves, find the cause in source and report it; do not route around it.

---

## 4. Repository Conventions

- **Branch:** work directly on `main`. Root commit `414081a` is the pristine upstream snapshot; keep it that way.
- **Commits:** one concern per commit, conventional prefixes by layer — `feat(Core):`, `feat(Package):`, `fix(Post):`, `test:`, `chore:`, `docs:`.
- **New bindings:** `lib/LaTeXML/Package/<pkg>.sty.ltxml`, header comment naming the package version emulated, then `1;` at the end. Add a `t/` pair when the binding changes structure.
- **Ignored, never committed:** `blib/`, `*.log`, `*.aux`, `Makefile`, `MYMETA.*`, `pm_to_blib`. Scratch `.tex` inputs for probes do not belong at the repo root; keep them in a session scratchpad or ask where they should live.
- **No compat shims.** Superseded fork surfaces are deleted, not aliased.

---

## 5. Verification Mandate

Before concluding a change:

1. Run the drivers that cover the touched layer, then the full suite for anything under `Core/` or `Common/`:

   ```powershell
   ltst t/40_math.t t/70_parse.t
   ltst t
   ```

2. For capture changes, digest a small source with `--capture` and confirm that every `capture:source` equals the bytes of the file at the recorded range, including a nested environment (`equation` around `aligned`) and a `\[ … \]` display.
3. For a new binding, show the emitted XML for a minimal document in the commit or report; a parse that succeeds by falling back to `parse_kludge` is not success.
4. Report failures with the harness output, not a summary.
