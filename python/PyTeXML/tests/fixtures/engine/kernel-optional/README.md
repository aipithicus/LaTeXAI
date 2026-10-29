# First kernel source boundary

This is a native feasibility witness for the first Python source-execution
milestone. Python execution is **not implemented or qualified** by this fixture.
The source target and native observations are pinned in
[source-boundary.json](source-boundary.json); the complete environment is pinned
by [root-a-pdftex-20261029](../../../../recipes/oracle-pins/root-a-pdftex-20261029.json).

The manifest selects complete, byte-exact source fragments from LaTeX2e
2026-06-01 patch 0's `latex.ltx`. Fragment order is execution order. Byte offsets
are zero-based, end-exclusive; line numbers are one-based, inclusive. Extract
only after checking the whole-file and fragment hashes. The fragments remain
upstream definitions, not hand-maintained replacements or Python bindings.

| Source lines | Responsibility |
| --- | --- |
| 321–322, 344 | Integer constants, including the count-register meaning of `\m@ne` |
| 1225–1226, 1228–1230 | Named definitions and token-list selectors |
| 1237–1317, 1350–1358 | Star/long handling; new, renew and provide command definitions; optional wrappers and hidden implementations |
| 1380–1386, 1391–1392 | Argument selectors and token/protection helpers |
| 1442–1447, 1465 | Protection helpers and ordinary typesetting protection state |
| 1737–1783 | Definedness checks, reserved-name strings, space-skipping lookahead and star selection |

## Initial state and prerequisites

[initial.tex](initial.tex) explicitly establishes the small ASCII input state for
`pdftex -ini -etex`: grouping and parameter catcodes, `@` as a letter, normal
space/endline handling, `escapechar=92` and `globaldefs=0`. Remaining catcodes and
primitive initial meanings come from this concrete native INITEX environment.
This is not a UTF-8 kernel-startup test or an implicit adoption of those defaults
for every Python profile.

The one imported allocation fact is `\z@` as dimension register 12 containing
zero scaled points. The full format's meaning was probed; kernel line 487
creates it through `\newdimen`. The first boundary starts after that allocation,
so it needs the typed cell and internal-integer conversion from a dimension.
Replacing it with an integer constant would change the declared initial state.
The other constants and all helper macro meanings above come from source.
There are no preinstalled public or hidden optional-command meanings.

The environment exposes `\numexpr` and leaves `\directlua` and `\@undefined`
undefined. Thus the unmodified source selects its e-TeX/pdfTeX definedness path.
`\protect` is initialized by the selected kernel source. Temporary names and
generated names use ordinary meanings and scope; no special lookup table is
part of the recipe.

The implementation prerequisites exposed by this boundary are:

- Definitions with `\long`, delimited parameters, nested parameter markers,
  definition-time expansion, and the trailing-parameter-marker construction in
  `\@yargd@f`; ordinary local/global writes and restoration.
- `\expandafter`, `\csname`, `\string`, `\escapechar`, `\number`, integer scanning,
  and the typed constants/register state above.
- `\ifx`, `\ifnum`, `\ifcsname`, correct skipped-branch handling, `\let` and
  `\futurelet`, including lookahead that crosses input/replacement boundaries.
- Protection-sensitive invocation and preservation of unexpanded macro bodies.
  A stored reference to an unimplemented operation is not permission to execute
  it or to assume its effects.

These are source requirements, not claims about current Python coverage. The
native harness also uses `\meaning`, `\immediate\write`, `\errmessage` and
termination to observe results; those observations may be checked through the
Python engine's state API without making terminal output a product requirement.

## What was checked

After loading `initial.tex` and the fragments, [witness.tex](witness.tex) produced
the 12 expected trace lines under native INITEX. The same witness, with
`\makeatletter` and native LaTeX termination, produced exactly those lines under
the pinned full format. It covers public/hidden meanings, omitted/supplied
optional arguments, a local renewal and restoration, an alias after restoration,
providing an existing command, a starred two-argument command, `\@namedef`, and
undefined-name lookup without creating a meaning.

This deliberately bounded first target covers successful declarations. Duplicate
or forbidden names and renewal of an undefined command reach `\@notdefinable`
or `\@latex@error`, whose diagnostic dependencies are outside these fragments.
They must stop explicitly until that source closure is admitted; no success or
no-op stub is allowed. Moving-argument behavior, general error recovery,
`DeclareRobustCommand`, environments, xparse/expl3 initialization and etoolbox
patching are not qualified by these observations. Patching follows with the
pinned package source once its additional prerequisites are implemented.

## Reproduce the native check

Restore and verify the pinned toolchain as described in the
[oracle recipe](../../../../recipes/root-a-oracle-baseline.md). In a fresh work
directory, copy `initial.tex` and `witness.tex`, extract the manifest's fragments
from the verified `latex.ltx`, and write a driver that inputs the initial file,
each fragment in manifest order, then the witness. Extraction must preserve all
bytes, including the spaces in the `\@sptoken`/`\@xifnch` definitions.

Run `pdftex -ini -etex -interaction=nonstopmode -halt-on-error -no-shell-escape
-recorder boundary.tex`. For the full-format comparison, use `pdflatex` with the
same noninteractive flags on a driver containing `\makeatletter` followed by the
witness, replacing its final `\end` with `\csname @@end\endcsname`. Both must exit
zero and produce the exact ordered `BOUNDARY:` lines in the manifest. Keep the
source hashes, extracted-file hashes, commands and logs with the result.
