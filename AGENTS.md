# AGENTS.md — Working Guidance & Conventions

Behavioral expectations, development loop, and repository conventions for AI agents operating in the **LaTeXAI** repository: a local fork of LaTeXML (upstream v0.8.8, revision `ee4b3640`) shaped to return the object a manuscript compiler consumes, rather than HTML or MathML.

---

## 1. Context Routing Map

| Need / Topic | Primary Reference |
| :--- | :--- |
| **Documentation routing** | `DocOps.md` — index of in-repo `docs/` (testing, binding specification, minting recipe) and the issues workspace at `../aipithicus-issues/LaTeXAI/` (planning, briefs, chips, discussions, notes). Never link `private/` or `temp/` from tracked files. |
| **Upstream engine documentation** | `README.pod`, `INSTALL`, `doc/manual/` (the 0.8.8 manual; `manual.pdf` at top level) |
| **Engine layers** | `lib/LaTeXML/Core/` (Mouth → Gullet → Stomach → Document), `lib/LaTeXML/Common/` (Locator, Model, Config), `lib/LaTeXML/Engine/` (`*.pool.ltxml`), `lib/LaTeXML/Package/` (461 bindings, `*.sty.ltxml` / `*.cls.ltxml`) |
| **Math parsing** | `lib/LaTeXML/MathGrammar` (Parse::RecDescent source), `lib/LaTeXML/MathParser.pm`; `tools/dev/generate.pl` compiles it to the gitignored `lib/LaTeXML/MathGrammar.pm` |
| **Post-processing (oracles only)** | `lib/LaTeXML/Post/` — MathML, UnicodeMath, LexMath. Read as instruments; not the product surface. |
| **Schema** | `lib/LaTeXML/resources/RelaxNG/` |
| **Tests** | `t/*.t` drivers over `t/<suite>/*.tex` + `*.xml` reference pairs (`LaTeXML::Util::Test`) |
| **Fork history** | `git log` from the root commit `414081a` (pristine upstream baseline). Every change is a reviewable diff against that commit. |

---

## 2. Development Loop

**Run through the `pwsh_exec` MCP.** The repository owns its loop: `tools/dev/profile.ps1` is the PowerShell profile the server loads (both gitignored MCP configs, `.mcp.json` and `.codex/config.toml`, name it in `MCP_POWERSHELL_PROFILE`; `.mcp.example.json` is the tracked template), and it dot-sources `tools/dev/latexai-aliases.ps1`. The aliases derive the repo root from their own location and resolve Strawberry Perl from `$env:PERL_ROOT` (`PERL_HOME` is its `perl\` subdirectory), the one machine-specific value, which the MCP config's `env` block supplies. Ambient `PATH` is bypassed on purpose: the Bash tool and MSYS resolve a different `perl` first, and stock LaTeXML is not installed anywhere. If the aliases warn that `PERL_ROOT` is unset, the session is not using this repository's MCP config; fix that, do not hardcode a path.

| Alias | Expands to | Use |
| :--- | :--- | :--- |
| `lgen [--force]` | `perl tools/dev/generate.pl` | compile the grammar and stamp the version into `lib/`; idempotent, about 1 s |
| `lctan [opts] <pkg>…` | `perl tools/dev/fetch-ctan.pl` | vendor a package's runfiles and metadata into `lib-ctan/<pkg>/`; see `docs/recipes/fetch-ctan.md` |
| `lgold [--force] t/<suite>/<case>.tex` | `perl tools/dev/golden.pl` | write a fixture's golden with the driver's own configuration; refuses on engine errors. Never write goldens with `lxml` |
| `lxml` | `perl -I lib bin/latexml --log=temp/logs/<job>.latexml.log` | digest a file or `literal:` string to `ltx` XML |
| `lxmlp` | `… bin/latexmlpost` | post-processing, only when an oracle comparison needs it |
| `lxmlc` | `… bin/latexmlc` | combined driver |
| `ltst` | `prove -I lib` | run test drivers, e.g. `ltst t/40_math.t` |
| `lmath '<tex>' [-Preload x] [-Capture] [flags]` | `lxml [--preload=x] [--capture] [flags] literal:<tex>` | quick math probe; extra flags pass through |

Facts that save a round trip:

- Run `lgen` after a fresh clone and after editing `lib/LaTeXML/MathGrammar`. It writes the gitignored `lib/LaTeXML/MathGrammar.pm` and `lib/LaTeXML/Version.pm`; with those in place `-I lib` is the whole include path. `Makefile.PL`, the Makefile, and `blib/` are untouched and remain the path to an installable distribution; nothing in the development loop runs them.
- The CLI aliases default `--log` into `temp/logs/`, named after the job as `latexml` itself would. Pass `--log=` yourself to override. A `.latexml.log` at the repository root means something bypassed the aliases.
- The version flag is `--VERSION` (uppercase). `--version` prints usage.
- **No TeX distribution is installed.** Passthrough and hybrid bindings (tikz, pgfplots, algorithmic, xcolor, listings, cleveref, …) try to load the raw `.sty` via `kpsewhich` and error out. Real-paper runs need `--includestyles` plus a preload binding that raises `MAX_ERRORS` and turns on `LEXEMATIZE_MATH`; toy probes with `lmath` do not.
- `--capture` (fork feature) emits `capture:*` provenance attributes on every element and `capture:source` on `ltx:Math`. `--noparse`, `--tex` and `--preload` are unchanged upstream switches; `--tex` output is the expansion oracle for drift measurements.
- Fallback without the aliases: `& "$env:PERL_ROOT\perl\bin\perl.exe" -I lib bin/latexml --log=temp/logs/<job>.latexml.log …`.

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
- **New bindings:** `lib/LaTeXML/Package/<pkg>.sty.ltxml`, header comment naming the package version emulated and what it was written from, then `1;` at the end. Every binding ships with its own suite `t/<pkg>/` and driver `t/8N_<pkg>.t`, as upstream does for `t/ams`, `t/babel`, `t/moderncv`; the contract and definition of done are in `docs/specification/bindings.md`, the procedure in `docs/recipes/package-bindings.md`.
- **Ignored, never committed:** `blib/`, `*.log`, `*.aux`, `Makefile`, `MYMETA.*`, `pm_to_blib`. Disposable working files go under the gitignored `temp/` tree: logs in `temp/logs/`, test-driver output in `temp/t/<test>/`, binding intermediates in `temp/bindings/<pkg>/`. Nothing at the repo root, nothing under `.codex/` or other tool dotdirs, nothing in `private/`. Test fixtures go in `t/<suite>/` (see `docs/testing.md`); a bespoke driver's runtime output goes through `File::Temp` or `temp/t/<test>/`.
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
