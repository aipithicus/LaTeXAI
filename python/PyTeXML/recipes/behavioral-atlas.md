# Behavioral atlas: spacing, meanings and generated parameters

The [catalog](behavioral-atlas/catalog.json) is a research and qualification map
of **nine behaviors**, grounded in **17 existing files and 21 pinned byte ranges**.
It complements the native meaning census with programs that exercise interactions.
It is not a vocabulary installation table or a claim of nine passing documents.
The first slice was authored on 2026-10-29 against LaTeXAI `76ec228` and the
upstream baseline `ee4b3640`. Raw source SHA-256 values and byte intervals are
authoritative; line ranges are navigation aids, including physical CR/LF lines.
The original files remain in place and are never newline-normalized by the atlas.

## First slice

| ID | Behavior and primary source | General mechanism | Current bounded check |
| --- | --- | --- | --- |
| S01 | [Trailing spaces and tabs](../../../t/tokenize/trailingspaces.tex) with disabled endline insertion | Physical-line normalization differs from semantic space-token handling | Exact body excerpt; joined words, separator spaces and tab provenance |
| S02 | [Mixed newlines](../../../t/tokenize/newlines.tex) and its [included input](../../../t/tokenize/newlines-input.tex) | Physical-line events, paragraph state and input-stack boundaries | Raw-byte preservation checked; execution remains open |
| S03 | [Equality under category changes](../../../t/tokenize/equality.tex) | Character identity, aliases, scoped reading state and frozen tokens | Synthetic provisional read restored and reread under corrected catcodes; old tokens remain unchanged |
| M01 | [Meaning, string and detokenize](../../../t/expansion/meaning.tex) | Typed identity and context-dependent display are separate observations | Whole fixture not run |
| M02 | [Meaning-based reconstruction](../../../t/expansion/multi_escaped_param.tex) | Nested parameter escaping, expansion order, deliberate rescanning and semantic comparison | Definition fragment plus eight observations match pinned native execution |
| M03 | [Escapechar and generated names](../../../t/expansion/escapechar.tex) | Name construction consumes state; a generated name survives independently of source spelling | Synthetic `T1-cmd` definition derives one control-sequence token; display reconstruction splits it and changes its typed descriptor |
| P01 | [Constructed parameter, test 4](../../../t/expansion/pdftex_expanded.tex) | Definition scanning consumes tokens across expansion boundaries | Unchanged construction excerpt produces `macro:#1->#1`; invoking the new macro returns its argument |
| P02 | [Expansion barriers, T5.1–T5.9](../../../t/expansion/pdftex_expanded.tex) | Frame-local suppression, token-register insertion and literal versus compiled parameters | Nine separate native observations; seven Python matches, two explicit gaps |
| P03 | [Extracted expl3 conditional generator](../../../t/expansion/pass_param_toks_in_gen_macros.tex) | Source-derived computed names, category changes, protected expansion and conditional skipping | Python derives the native-matching definition; invocation reaches missing `romannumeral` |

Each case records prerequisites, mechanisms, located expectations, limitations,
supporting Python checks and a proposed staged experiment. Its three baseline
qualification fields retain the first-slice baseline `not_run`, `not_run`,
`proposed`. Current native/Python comparisons are recorded separately below and
in a checked reference fixture; the complete original documents and general
staged resolver remain unqualified. A catalog edit cannot promote an XML golden
into a native observation.

## What the first slice establishes

S01 separates physical trailing ASCII-space removal from state-dependent space
tokenization. In the fixture one tab follows an ordinary space and is skipped;
another tab supplies a semantic space. A blanket whitespace rewrite loses this
distinction and may lose the source occurrence that produced the token.

M03 supplies a small witness for the assay's reconstruction lesson. The shared
engine creates the generated name from source. Its original replacement is one
control-sequence token; reconstructing its display under ordinary letter catcodes
creates a different token sequence. M02 now supplies a native-matched execution
of the reconstruction protocol, including this negative outcome; neither check
repairs every census exception.

P01 shows that the existing expansion and definition machinery can assemble a
parameter from distinct contributions. The derived check removes only the
original `meaning` output command, inspects the definition directly and invokes
it with `OK`. No engine primitive was added. P03 is a larger witness: its native
execution derives the name and exercises defined/undefined/relax branches, while
Python's remaining invocation gap is recorded below. It is adapted from 2019
expl3, not the current pinned release; later source-family qualification must
preserve that distinction.

## Pinned native program comparisons

The [probe manifest](../tests/fixtures/engine/atlas-native/cases.json) and
[frozen native reference](../tests/fixtures/engine/atlas-native/native-reference.json)
initially recorded P03, M02 and a minimal P03 insertion contrast; the extension
below adds P02 observations and general mechanism checks. The native basis is
[root-a-pdftex-20261029](oracle-pins/root-a-pdftex-20261029.json): pdfTeX 1.40.29,
LaTeX 2026-06-01 and expl3 2026-09-09. The runner checks the archived inventory,
selected binary/format/source hashes and recorded TeX input files. No ambient
TeX installation or LaTeXML XML target supplies an expected result.

The unchanged P03 definition fragment is lines 1–89; M02 is lines 1–16. Each
receives explicit observation probes. Original document output and `bye` are
excluded; the native wrapper runs in the pinned **pdflatex format**, writes
hex-framed traces and terminates through that format. Python starts with the
pdfTeX primitive profile, known initial undefined state, and the fragment's own
definitions. This is a bounded source-execution comparison, not full format
startup or original/prepared-document equivalence.

Each target's displayed definition is reconstructed as a candidate. A second
fresh native process repeats all observations and must find that candidate
equal to the original with `ifx` before its typed descriptor becomes a reference.
Printed equality alone cannot qualify it. The tracked reference contains source,
probe, replay and basis identities; ordinary tests verify those identities and
replay the successful Python protocol without requiring native TeX.

| Program | Native observations | Python result |
| --- | --- | --- |
| M02 | Ordinary selectors, a literal parameter marker and protected/long flags reconstruct; a body containing the single generated name `T1-cmd` does not; the scratch definition is restored | All eight observations and the protocol's typed descriptor match |
| P03 | Defined operand skips the F branch; undefined/relax take it; defining the operand later changes subsequent calls; locally redefining `returnfalse` changes behavior, then group exit restores it; generated definition is unchanged | Definition now matches; invocation stops at missing `romannumeral`, with all nine probe observations absent after transactional rollback |
| P03 insertion contrast | `edef` with `unexpanded{#1}` has meaning `macro:->##1`, equal by `ifx` to an authored `##1` replacement | Definition and all three observations now match |

The first acquisition reported:

```text
invalid_definition_parameter: Replacement text requires a declared parameter or doubled marker
```

The implicated shared path was `expanded_body` in
[definition operations](../src/engine/primitives/definitions.py), which applied
ordinary replacement-parameter validation to an inserted list. The implementation
below closes that gap. The first acquisition changed no engine behavior; its
raw receipts remain separate from the later implementation qualification.

The Python runner reads physical source lazily so category/endline assignments
apply at their original positions. A strict diagnostic dispatcher uses the
shared expansion and setup evaluator but exposes the original failure instead
of preparation's deferred-source fallback. Probe token lists are frozen only
after the fragment has established their reading context. This adapter does not
qualify normal preparation routing, a general `scantokens` implementation, or
automatic staged resolution.

These results sharpen the staged design. M02's negative reconstruction is loss
of token identity, not a whitespace defect to normalize away; retained typed
source or additional justified context may resolve it. P03's current blocker is
an unavailable engine rule, not a missing declaration that another pass can
supply. Native helper-redefinition behavior also shows why a cached evaluation
depends on current helper meanings even when the generated macro body is stable.
Selective invalidation/replay remains proposed.

From `python/PyTeXML`:

```powershell
& ../.venv/Scripts/python.exe -B -m src.validation.atlas_native `
  --oracle ../../temp/texlive-oracle `
  --inventory ../../temp/oracle-root-a/20261029/oracle-files.json `
  --output temp/behavioral-atlas/<new-native-run> --timeout 60 `
  --workload-note '<host workload>'
& ../.venv/Scripts/python.exe -B -m unittest discover -s tests -p test_atlas_native.py -v
```

The run writes a summary and candidate frozen reference without overwriting an
earlier run. A completed survey can contain explicit blocked comparisons; its
completion is not an all-pass claim. Native executions and each Python specimen
run in fresh processes with wall/CPU and peak-RSS receipts. Python case timing
starts after runner imports; peak RSS includes those imports. Orchestrator CPU
and memory exclude child processes; do not add process peaks or confuse them
with retained engine-object sizes. Costs and qualification are in the newest
[checkpoint](source-execution-progress.md). Competing Monte Carlo workloads
preclude a controlled throughput conclusion.

## Expanded-list insertion implementation

The shared expansion cursor now returns a transient `TokenListInsertion` for
the `the_toks` family (`unexpanded`, `detokenize`, and supported `the` quantities).
An `edef`/`xdef` or `expanded` list consumer copies that result without expanding
it or treating its parameter tokens as newly authored parameter syntax.
Ordinary expansion, including the second operand of `expandafter`, reinserts
the same tokens as ordinary input. A parameter-number scan inside `edef` also
uses ordinary expansion. This consumer distinction replaces the old practice
of marking every `unexpanded` token as suppressed for one read.

The [pinned algorithm reference](oracle-pins/expanded-list-source.json) identifies
pdfTeX 1.40.29's `the_toks`, `ins_the_toks`, and `scan_toks` sections. Its source
revision/hash are recorded independently of the native binary archive; this is
not a claim that the binary was rebuilt from that source during qualification.
The insertion distinction comes from those general procedures and native
contrasts, not a special case for an expl3 helper.

Stored definitions currently encode literal parameter tokens as lexical `##`
pairs. The definition consumer performs that encoding while retaining each
token's original object/category/source occurrence; authored capture remains
separate. It charges insertion/encoding work against the expansion budget and
publishes definitions only through the existing transaction. Tests cover
provenance, budget exhaustion, a later invalid raw parameter restoring the old
definition, nested generated definitions, aliases/shadowing, protected tokens,
local restoration and global assignment. This is not representation compaction.

P03 also exposed a legitimate empty expansion at the end of a bounded program.
The continuation evaluator now accepts that completed tail instead of rolling
back earlier definitions merely because no executable token remains. The
`P03-tail` native contrast qualifies this behavior; physical-source continuation
admission and suppressed executable tokens keep their existing boundaries.

The reference now has **14 programs, 40 observations and five native `ifx`-qualified
typed targets**, acquired in 28 fresh native processes. Python completes **11
program comparisons and 29 observations**. All five typed target comparisons
match, including P03's generated definition; that does not imply its invocation
program completed.

| Remaining boundary | Observed outcome | Next general gate |
| --- | --- | --- |
| P02 T5.7 | `toks` is absent from the implemented primitive profile and currently reports established-undefined | Expose the native primitive correctly; implement typed token registers, aliases, scope/copy and `the` insertion through the shared contract |
| P02 T5.8 | `expanded_argument: expanded requires a balanced group` for a begin-group character alias | Qualify group-opening acquisition through current token meanings, preserving the distinction from literal closing tokens |
| P03 invocation | `romannumeral` is absent from the implemented primitive profile and currently reports established-undefined | Implement/qualify general integer-driven roman conversion, including zero/negative termination, then rerun all nine generator observations |

The native engine has `toks` and `romannumeral`: these diagnostic strings are
current Python exposure gaps, not correct claims that the names are natively
undefined. P03 now finishes definition generation and matches the native typed
body. Its later probe transaction fails and rolls back all probe observations;
missing observations are not counted as matches. M02 remains fully matched.

Each numbered P02 expression is captured separately in a parameterless `edef`
observer with the original `aaa`/group-alias prerequisites. The `toks0` assignment
and T5.9 definition are retained where required. This checks the expression's
expanded display, not a full original-document rendering or a typed descriptor
for every output character. These observation-only cases are explicitly distinct
from cases with a native-equal typed target. T5.4 previously emitted `\aaa ` in
Python where native emitted `x`; the shared insertion change corrects it.

The final receipts and full-suite results are in the newest
[execution checkpoint](source-execution-progress.md). Native expected values were
captured before implementation for the original insertion/barrier matrix; the
extended final acquisition independently confirms parameter-number and empty-tail
contrasts. No expected Python failure is promoted to a passing behavior check.

## Staged-resolution opportunities

The shared experiment is to inspect provisionally, learn an earlier applicable
prerequisite, then invalidate and replay affected observations. Compare with a
run that had the prerequisite at the start. A future declaration's effect must
not silently move earlier; using it to repair an earlier error is an explicit
recovery policy. Already captured token lists retain their categories.

S03 currently tests **manual reader checkpoint replay only**. The experiment
preserves old token values and source basis while the revised read matches a
fresh reader. It does not implement dependency scheduling, automatic invalidation,
effect rollback, recovery-state import or downstream result replacement.

For M02, later source/context evidence may constrain an ambiguous reconstruction;
repeatedly guessing a regime is not progress. For P01–P03, suspension must preserve
parameter depth, expansion frames and suppression, then avoid duplicate definition
writes and consumption on replay. Preserve unresolved inputs and recorded
assumptions when another pass supplies no new evidence. These are shared engine
contracts to investigate, not special handlers for atlas names.

## Oracles and admission

- **Fixture intent:** comments and program structure state a claim to investigate.
- **LaTeXML golden:** records that engine's XML projection; it may include font
  conversions. The arrow in P01's golden is not a native `meaning` string.
- **Native observation:** the P03/M02 comparisons above pin source,
  initialization and probe transformations separately from the first slice.
- **PyTeXML observation:** four first-slice checks and the native-matched M02
  protocol; none runs a complete original document or establishes general staged
  resolution. P03 remains an explicit execution gap.

The ordinary LaTeXML harness selects `.tex` files with matching `.xml` targets,
checks requirements, converts and compares XML. It also has separate post/daemon
routes. File counts include helpers and do not establish execution or coverage.
The expansion driver declares `t1enc.def` for `meaning.tex`; preserve such hidden
prerequisites. Inspect active source boundaries and comments before claiming a
construct was exercised. Packages, capture tests and alignment/math cases remain
eligible research material when they reveal general contracts.

The high-level study prompted this atlas. Its proposed broad xparse coverage is
not present in the small existing `xparse.tex`, and the two `expl3` fixtures are
not an intrinsic-completeness suite. Primitive demand, macro source derivation
and optional intrinsic optimization need separate evidence. The atlas prioritizes
mechanism discovery and must not become a per-name implementation backlog.

## Verify, select and exercise

From `python/PyTeXML`, using the repository's pinned Python:

```powershell
& ../.venv/Scripts/python.exe -B -m src.validation.behavioral_atlas `
  --exercise --output temp/behavioral-atlas/<new-run>.json `
  --workload-note '<host workload>'
& ../.venv/Scripts/python.exe -B -m unittest discover -s tests `
  -p test_behavioral_atlas_catalog.py -v
```

Omit `--exercise` for integrity checking alone. `--family spacing|meaning|parameters`
and `--mechanism <catalog-tag>` select cases after verifying the whole catalog.
Unknown selections fail. Receipts never overwrite a prior run. The checker
rejects changed source bytes, changed/out-of-range fragments, duplicate or
unlocated cases, missing Python check methods and unsupported qualification.

Each exercised check reports wall and process CPU time, its test-source hash and
process RSS high-water after execution. **That memory counter is cumulative for
the process, not the check's allocation or incremental memory.** Do not sum these
peaks. The receipt also records the full engine source/resource fingerprint and
whole-process cost. Cold startup precedes per-check timing; no allocation tracer
is active. Per-case independent peak/retained-memory attribution remains future
work if an implementation decision requires it.

## First qualification

Four supporting checks and six catalog integrity tests pass. The initial failed
run is retained: the test setup mismatched reader/context endlinechar, referred
to the wrong span field and expected a skipped tab to produce a token. These were
test-authoring errors; the engine was not changed to satisfy them.

The current run receipt and costs are recorded in the newest
[execution checkpoint](source-execution-progress.md). The user's concurrent
Bayesian/Monte Carlo workloads make these diagnostic costs, not a controlled
performance comparison. Source, atlas and code identities accompany the receipt.

To extend the atlas, add a behavioral entry with exact source spans and explicit
prerequisites; keep helper inputs and harness requirements. Identify the smallest
observable claim and an independent oracle, then add a bounded check when useful.
An existing source-based test can support several entries without being counted
several times. Keep new runtime outcomes in fresh receipts and current qualification
in this recipe/checkpoint; the working queue contains only remaining work.
