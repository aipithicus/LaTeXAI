# Meaning assay qualification and source-derivation progress

This follows the [native assay](meaning-assay.md). Its raw census and frozen
reference corpus are unchanged. Native-display triage and source-state comparison
are implemented; representation compaction and a derived-state snapshot are
scheduled prerequisites, not implemented features.

## Purpose of studying exceptions

The user's intent is to extract general design insights from the exception
corpus, including cases outside immediate manuscript demand. Investigate which
assumptions, representations and operation contracts fail across many examples;
use that knowledge to make the engine robust to unseen cases. A list of names
or package-specific repairs is not the intended output of this study.

Group cases by mechanism, build minimal native contrasts, distinguish a general
engine rule from format/package behavior or an actual historical special case,
then qualify the resulting contract with varied examples across families.
The census alone does not establish that native TeX implemented these behaviors
case by case. LaTeXML's accumulated bindings are useful comparative evidence,
not proof that PyTeXML needs the same accumulation strategy.

The first demonstrated lesson is that printed names are not a serialization of
token identity. A representation must preserve arbitrary control-sequence names,
token kinds and categories independently of current source-tokenization rules.
That principle covers classes of generated names and spacing cases at once.
Further studies can test definition-time versus current lexical state, parameter
syntax, aliases, scope, initialized data and error continuations without waiting
for each example to block a document. Label hypotheses separately from qualified
rules. Workload evidence prioritizes implementation; broader exception study
informs architecture and anticipatory regression tests.

The study also asks what becomes possible through PyTeXML's staged architecture.
Preserved source and context can prevent ambiguities introduced by a printed
dump; provisional inspection can look ahead, discover constraints and defer a
decision; later evidence can trigger selective rereading and reevaluation.
Recovery may produce useful content from input on which native TeX errors.
Native behavior qualifies faithful execution, while recovered interpretations
carry their assumptions and consequences. Neither category should be described
as the other.

The next spacing witnesses should therefore exercise original source, generated
names, semantic space tokens, local reading-context changes and delayed
prerequisites, rather than only improve dump reconstruction. Distinguish later
discovery of an earlier applicable context from applying a later declaration
retroactively. Preserve committed token identities and revisit only provisional
readings. The staged-pipeline brief §5.1 owns this proposed shared reconsideration
mechanism and its gates; the current reader/checkpoints are supporting pieces,
not evidence that a general second-pass resolver is implemented. No new reader
behavior or tests are introduced by this design clarification.

## Display differences: 2026-10-29 triage

The 533 records classified `python_meaning_display_differs` were reconstructed
under both recorded regimes. The new native diagnostic prints each reconstructed
candidate's meaning in the same display context as Python, and separately
compares that candidate to the original target with native `ifx`.

| Observation | Result |
| --- | ---: |
| Original names | 533 |
| Candidate attempts across both regimes | 1,066 |
| Python display equals native display of the same candidate | 1,066 |
| Candidate differs from original target under native `ifx` | 1,066 |
| Candidate-display discrepancies | 0 |

All first-regime differences from the target display concern spaces:

| Diff direction, target to reconstructed candidate | Names |
| --- | ---: |
| Spaces removed only | 367 |
| Spaces added only | 146 |
| Both added and removed | 20 |

For example, retokenizing `\T1-cmd` under ordinary letter catcodes creates
control sequence `T` followed by text `1-cmd`; both engines then print
`\T 1-cmd`. Repeated spaces or control-sequence names containing spaces also
cannot generally be recovered by ordinary source tokenization. These are
examples of the reconstruction loss, not a causal classification of every row.

The comparison isolates this group from formatter defects: changing Python's
display to reproduce the target strings would make these candidates disagree
with native TeX. It does not establish universal `meaning`/`detokenize` fidelity,
and it does not diagnose the other 771 original native-inequality cases. Keep
the package-patching witnesses as independent behavior checks.

The qualified run is `20261029-display-triage-qualified` under PyTeXML's local
`temp/meaning-assays/`; every diff and native display is in `records.jsonl`.
Its receipt records 2.428 seconds wall, 1.531 Python CPU and 0.516 native CPU,
with the user's competing Monte Carlo workloads. The outer receipt and the
58 meaning tests plus four kernel-source tests are retained under repository
`temp/meaning-followup-qualified-receipt`. All **62 tests pass**.

```powershell
& ../.venv/Scripts/python.exe -B -m src.validation.meaning_assay.triage `
  --assay temp/meaning-assays/20261029-final `
  --oracle ../../temp/texlive-oracle `
  --inventory ../../temp/oracle-root-a/20261029/oracle-files.json `
  --output temp/meaning-assays/<fresh-triage-id> `
  --workload-note '<host workload>' --timeout 180
```

## Compare derived state, with an explicit denominator

`src.validation.meaning_assay.compare` loads a checksum-verified frozen
reference and compares every supplied final source-derived binding using its
semantic hash and full typed descriptor. It rejects mismatched basis identity.
Missing, uncertain, uncomparable and unqualified references are separate from
matches. This interface covers control-sequence bindings; active-character state
needs its own distinctly keyed reference. The caller selects a named state boundary and must exclude unchanged
seed state; transient definitions need observations at their own boundary.
Source execution and source-hash verification remain the caller's responsibility.

The kernel-source test now executes the pinned upstream fragments and compares
all 54 final new/changed bindings with the native corpus:

| Result | Bindings |
| --- | ---: |
| Qualified macro references, all matching | 41 |
| No qualified reference: reconstruction exceptions | 5 |
| No qualified reference: non-macro meanings | 8 |
| Mismatching / uncertain / uncomparable references | 0 |

The five macro exceptions are `:`, `@backslashchar`, `@qend`, `@qrelax` and
`@xifnch`. Source execution constructs them, but this census comparison cannot
certify their descriptors. The existing 19 native observations still qualify
bounded source behavior independently. The remaining eight entries need typed
non-macro/state oracles; a displayed register name does not establish its value.

The receipt reports **41 / 15,552 = 0.2636% of the qualified macro reference**.
That is a useful progress gauge with a fixed basis and denominator, not full
census coverage or a completion threshold. Record matched, mismatching and
unqualified counts, family scope and state boundary alongside the fraction.
Do not add fractions from overlapping families. Full-format state can legitimately
differ from intermediate bootstrap state, which needs contextual investigation
rather than silently changing either side to make it match.

Each run of `test_kernel_source.py` emits a fresh JSON comparison receipt under
`temp/tests/kernel-source-census-*.json`; its path appears in the test output.
The API is reusable for subsequent source families without installing oracle
meanings in the engine.

## Corrections to census interpretation

`fi:` and `exp_after:w` are primitive aliases. `exp_args:Nc` is a long macro
whose body uses expansion and computed-name primitives. Among the 985 names
spelled `tex_*:D`, **542 are primitive/other, 442 are undefined and one is a
font meaning** in this pdfTeX target. Naming-layer counts are not implementation
coverage. Expansion correctness is foundational, but static fan-in does not
quantify how much behavior or runtime cost one primitive accounts for.

The 598 macro display differences between engines count differing names at
these pinned states. They are not a count of independent engine-specific source
branches: several names may come from one branch or from initialized data, and
equal printed displays do not establish token equality. Keep the list as input
to later profile qualification.

## Representation and snapshot sequencing

73,143,908 retained bytes divided by 341,106 recorded body/parameter tokens is
**214.43 bytes per token as an amortized corpus ratio**. It includes definitions,
spans, strings and containers, not just a token object's layout. The traced
16.215-second pass includes reading and definition scanning as well as allocation.
It is not an uninstrumented construction benchmark or a lower bound on future
bootstrap cost. The user's approximately 205-byte mouth estimate is a separate
reported observation; it has not been remeasured here.

The 15,552 qualified names have **11,401 distinct macro descriptors**. This
supports measuring shared immutable tokens/meaning bodies, but does not by
itself establish how much memory interning saves or which provenance can share.

The queue now requires compact representation before broad source bootstrap,
and a qualified derived-state snapshot before collection-scale source-bootstrap
runs. Small source-family witnesses can establish semantics first. Measure
cold source derivation, snapshot creation, cold/warm restoration and per-document
state separately. Keep interned semantic token payloads separate from occurrence
provenance; integer locations must retain exact source identity, ranges and
derivations. Include all owned pools and source tables in memory comparisons.
Use the same fixed corpus and matched runtime/instrumentation, with ordinary
counter-only runs separate from allocation tracing.

A snapshot must be produced by qualified source execution. Its identity covers
source hashes, engine/profile, initialization, representation schema and relevant
external basis. Restore must preserve aliases, typed state and provenance while
isolating each document's mutations. It must not freeze document-specific search
results as universal truths. New declarations, redefinition and grouping must
still work after restoration. Intrinsics remain optional optimizations.

## Family selection: workload first, exceptions as additional evidence

All five current Root A entry points have exact macro reconstructions. Following
only the stored static graph until unparsed bodies or non-macros stop the walk
gives these candidate frontiers:

| Root | Reachable names | Unresolved macro frontier | Private l3 subset |
| --- | ---: | ---: | ---: |
| `seq_new:N` | 431 | 27 | 9 |
| `cs_new_protected:Npn` | 432 | 27 | 9 |
| `seq_gput_right:Nn` | 431 | 27 | 9 |
| `seq_use:Nnnn` | 445 | 27 | 9 |
| `NewDocumentCommand` | 804 | 45 | 13 |

These are overlapping, incomplete static frontiers, not executed dependency
sets. They include diagnostic paths and token-list data such as
`__kernel_msg_expandable_error:nn`, `__prop_split_flat:w` and `l__cmd_fn_tl`.
Private naming includes data and temporaries, not only helper algorithms.
Computed targets can add edges absent from this graph. The inspection is retained
under repository `temp/meaning-family-frontier-receipt`.

Keep the workload-selected sequence/declaration family. Trace its source and
claimed success/failure behavior to establish the actual prerequisites, using
these exceptions as probes of where source derivation adds value. A family with
more census exceptions is not automatically a higher implementation priority.
