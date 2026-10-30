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
| M02 | [Meaning-based reconstruction](../../../t/expansion/multi_escaped_param.tex) | Nested parameter escaping, expansion order, deliberate rescanning and semantic comparison | Whole protocol not run |
| M03 | [Escapechar and generated names](../../../t/expansion/escapechar.tex) | Name construction consumes state; a generated name survives independently of source spelling | Synthetic `T1-cmd` definition derives one control-sequence token; display reconstruction splits it and changes its typed descriptor |
| P01 | [Constructed parameter, test 4](../../../t/expansion/pdftex_expanded.tex) | Definition scanning consumes tokens across expansion boundaries | Unchanged construction excerpt produces `macro:#1->#1`; invoking the new macro returns its argument |
| P02 | [Expansion barriers, T5.1–T5.9](../../../t/expansion/pdftex_expanded.tex) | Frame-local suppression, token-register insertion and literal versus compiled parameters | Individual observations still to qualify |
| P03 | [Extracted expl3 conditional generator](../../../t/expansion/pass_param_toks_in_gen_macros.tex) | Source-derived computed names, category changes, protected expansion and conditional skipping | Source and golden inspected; execution and branch witnesses remain open |

Each case records prerequisites, mechanisms, located expectations, limitations,
supporting Python checks and a proposed staged experiment. Its three baseline
qualification fields deliberately remain `not_run`, `not_run`, `proposed` for
the original fixture, a new native run and the general staged resolver. Separate
run receipts establish supporting-check results; a catalog edit cannot promote
an XML golden into a native observation.

## What the first slice establishes

S01 separates physical trailing ASCII-space removal from state-dependent space
tokenization. In the fixture one tab follows an ordinary space and is skipped;
another tab supplies a semantic space. A blanket whitespace rewrite loses this
distinction and may lose the source occurrence that produced the token.

M03 supplies a small witness for the assay's reconstruction lesson. The shared
engine creates the generated name from source. Its original replacement is one
control-sequence token; reconstructing its display under ordinary letter catcodes
creates a different token sequence. This check establishes that local mechanism,
not successful execution of M02 or a repair of every census exception.

P01 shows that the existing expansion and definition machinery can assemble a
parameter from distinct contributions. The derived check removes only the
original `meaning` output command, inspects the definition directly and invokes
it with `OK`. No engine primitive was added. P03 is a larger follow-up candidate:
its own source creates a previously unseeded name, but its existing golden only
displays that definition. Add defined/undefined/relax branch calls before claiming
its invocation behavior. It is adapted from 2019 expl3, not the current pinned
release; later source-family qualification must preserve that distinction.

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
- **Native observation:** acquire under a pinned profile with exact source,
  initialization and probe transformations. None was newly acquired in this slice.
- **PyTeXML observation:** four supporting checks below; none runs a complete
  original document or establishes general staged resolution.

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
