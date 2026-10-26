# PyTeXML development backlog and implementation record

Recorded 2026-10-24 after Batch 4; updated 2026-10-25 for Batches 5A and 5B and
the four authorized reading/dependency increments on `main`. Review findings from
`20261025-reading-increments` were added to sections 1 and 2 on 2026-10-25. Broader
interpretation and binding-design work below remains a plan, not authorization to
implement it all.

## Where we are

The five-batch cleanup plan is in [astra-refactor-plans-part1.md](astra-refactor-plans-part1.md).

| Batch | Completed work | Commit |
| --- | --- | --- |
| 1 | Surgical failure-location reset and shared record traversal | `cd468c5` |
| 2 | Shared helpers/defaults, explicit scanner interfaces, named positional state | `cb0b3f3` |
| 3 | Manifest record construction and lifecycle ownership | `6a7da8d` |
| 4 | YAML option consumers/validation, declaration indexes, cached literal templates | `a382b5a` |
| 5A | Explicit preparation request; one publication and rollback owner | `f8cf250` |
| 5B | Explicit inspection inputs; session-owned emission, observations and payload edits | `0aac97c` |

Batch 4 validation: dedicated-venv suite ran 771 tests, with 769 passing and two
optional compiler tests skipped. The first full run reached its 600-second limit;
the successful retry used an 1800-second budget and took about 442 seconds inside
unittest. This is not a performance benchmark. Four specimen manifests and all
69 payload/provenance files matched the Batch 3 baseline; run logs changed.

The [reading-control audit](../resources/bindings/reading-controls.md) separates
active controls, descriptive invariants, and retained `deferred_phase2` knowledge.
Catalog data is shared read-only knowledge; activation and occurrence options
remain document-local. No full expansion or new binding authoring language was introduced.

## Batch 5A: simplify the preparation entry point

Completed in [pipeline.py](../src/prepare/pipeline.py). Previously, the public wrapper
forwarded `dict(locals())`; `_prepare_paper` repeated its argument list, path setup,
validation, and output-file handling despite receiving `output_file=None`.
The implementation follows this scope:

1. Inventory callers and tests before changing signatures. Preserve the supported
   public API and return tuple for this increment.
2. Build one explicit validated request/configuration record containing the settings
   the internal builder really uses. Names and exact fields are implementation
   choices, not a new framework contract. Separate the requested destination from
   the transaction's staging directory.
3. Centralize redundant argument/path checks and retired-option rejection. Do not
   delete checks that require later discovery, such as protecting a source file
   recognized by the source store. Decide error/logging timing explicitly: moving
   validation before a transaction must not accidentally erase expected diagnostics.
4. Give the inner builder explicit configuration, staging destination, exclusions,
   and logger. Remove `dict(locals())`, duplicated forwarding, and unreachable
   secondary-output handling.
5. Keep publication, rollback, retained failure evidence, and secondary publication
   in the outer transaction owner. Keep the distinction between failure before
   publication and a logging failure after successful publication.

Gate: public calls and CLI behavior remain consistent; partial preparation still
publishes; rollback preserves the previous payload; failed manifests cannot claim
unpublished locations. Include logger ownership/failure behavior and output-path
protection. Run the full suite and compare specimens, then make a focused commit.

Do not silently remove public legacy parameters merely because their non-default
values are rejected. Any public API removal needs an explicit caller migration.

5A validation: 47 focused tests passed; the dedicated-venv suite ran 776 tests with
two optional compiler skips. All four manifests and all 69 payload/provenance files
matched Batch 4. Source-dependent checks remain after discovery, while rejected
legacy options still produce an attempt log. The removed inner overwrite check
was unreachable: the wrapper always passed `output_file=None`; public source-path
protection and output exclusions remain enforced.

## Batch 5B: clarify session/helper ownership

Completed across [session.py](../src/prepare/session.py),
[deferred.py](../src/prepare/deferred.py), bibliography and asset preparation.
The problem is helpers reaching through an entire session to mutate unrelated
state, not simply the number or length of files.

1. Make a small table of each helper's reads and writes: source lookup, reader
   registration, observations/requirements, emitted pieces, omissions, payload
   edits, dependency resolution, and manifest updates.
2. Reuse existing owners and methods first. Introduce narrow operations or a small
   protocol only where actual callers need them. Do not create a service class per
   branch, a generic event bus, or a speculative downstream session interface.
3. Move mutations behind their owner; pass stable data directly where no mutation
   is required. Start with one coherent helper, verify it, then continue.
4. Preserve Batch 3's record/lifecycle ownership and Batch 4's catalog boundary.
   Do not duplicate those rules inside a new facade.

Gate: repeated inputs retain distinct occurrences; shared source reads stay cached;
selected/skipped/deferred activity remains distinct; retained local styles still
allow later discovery; literal bytes, bibliography/asset resolution, edit-aware
locations, and publication behavior remain equivalent. Use focused tests plus the
full suite and four-specimen comparison. Commit separately from 5A.

Recheck the earlier candidates for dead helpers and repeated separator logic only
after this inventory. Do not remove historical evidence or resurrect regex cleanup.

### Ownership inventory and implemented boundary

| Helper | Reads | Mutation owner / result |
| --- | --- | --- |
| Asset header parsing, survival selection and reference rewriting | Captured commands, source bases, pieces and destination map | Return asset uses or new pieces; no session argument |
| Asset observation | Resolver/search state, units and deferred observations | Session registers uses and requests work; helper records candidate dependency metadata |
| Asset conversion | Admitted uses and explicit project/output roots | Writes derivatives; returns mapping. Pipeline orders conversion, session payload edits and immutable piece rewrites |
| Citation discovery | Pieces, resolver knowledge and line lookup | Returns selection, gaps and typed requirement requests; bibliography coordinator applies manifest fields and session requirements |
| Deferred inputs and bibliography | Cached documents, entry context, resolver, frames and unit registry | Session registers occurrences, observes spans, emits pieces, links replacements and captures/finishes bibliography state |
| External literals | Cached text, reading profile, policy and current emission mode | Session opens occurrences, records coverage and emits/omits/edits; resource helper records retained-resource metadata |
| Bibliography formatting/audit | Captured site, command inventory, cached databases and citations | Returns rewritten pieces and writes canonical resources; session owns generated-source registration, omissions and insertion rollback |
| Coverage accounting | Source bases, generated bases, tombstones, reader discards and line lookup | Mutates only its `PreparedLocations` index; finalization adapter calls the existing manifest lifecycle owner |
| Lint records and repair | Established unit, line and diagnostic evidence; repair additionally needs ordered reading context | Lint owns findings/proof; dispatcher owns resumption; session records the repair emission and omission |

The session remains the preparation coordinator. Traversal helpers intentionally
retain session access where several ordered operations must cooperate; their
dependency/resource metadata remains explicit. This is not a new downstream
session protocol, nor an attempt to hide every collection behind a setter.

All helpers now use named session operations instead of reaching into private
methods or the observation map. The duplicate insertion-to-command mapping loop
is shared by active and deferred inputs. The obsolete `prepare_assets` wrapper is
removed; its sequencing is visible at the pipeline. Source and generated buffers
stay in memory, with no additional source reads or serialized intermediate stage.

The new ownership tests exercise inspection without a session, occurrence-specific
coverage and asset edits, unchanged binding activation/units, and rejection of
conflicting retained-file edits across cached occurrences. Existing integration
tests cover the active/skipped/deferred paths, literal fidelity, bibliography,
publication and final locations.

5B validation: 32 asset/resource tests, 124 integration tests and four new ownership
tests passed. The final dedicated-venv suite ran 780 tests with two optional compiler
skips. All four manifests and all 69 payload/provenance files matched 5A, including
source-read counts and preparation status. The first full gate caught an indentation
error in a final consistency edit; it was corrected and both gates were rerun.
The failed iteration and successful verification have separate receipts. These
comparisons qualify refactor equivalence, not new rendering or preparation coverage.

## After Batch 5: evidence, implementation, and remaining sequence

### Evidence review, 2026-10-25

Reviewed commit `0aac97c` and the successful specimen iteration
`20261025-cleanup-batch5b-verified`. This review changes no runtime code. A fresh
in-memory traversal traced state invalidation for the two partial specimens;
it did not convert assets, publish a payload, or invoke a TeX engine.

| Specimen | Preparation | Bibliography entries / SVGs | Remaining preparation witness |
| --- | --- | --- | --- |
| Bayesian MARS, 2306.01911v1 | Complete under recorded assumptions | 58 / 10 | None recorded |
| Fractal, 2405.15943v3 | Partial | 33 / 9 | `requirement-68`: possible `lineno` package load in retained `neurips_2024.sty:350` |
| FPCA, 2412.11340v4 | Complete under recorded assumptions | 60 / 24 | None recorded |
| DeadSalmons, 2512.18792v1 | Partial | 154 / 5 | `requirement-128`: retained-code reading boundary at `natbib.sty:350` |

All four report completed materialization of known requests. The 3,256 requirement
records comprise 3,151 interpretation, 103 binding, and two preparation records.
The natbib boundary also has an unresolved diagnostic; these are two records for
one obstruction, not two independent failures. None of the 12,223 unit records has
an unmapped/partial location, and no recorded source-coverage interval is unaccounted
for. Coverage accounting does not prove interpretation or dependency closure.

The earlier discussion in `astra-preparation-outstanding-items.md` is historical:
its proposed declaration, image-page, logging and publication work is substantially
implemented. In particular, the current natbib trigger is **not** `providecommand`,
and the previously observed shipout image is now materialized. Preserve that earlier
discussion as history rather than reuse its recommendation as the current backlog.

#### Ranked next increments

1. **Bounded `let` capture and scoped meaning assignment.**

   Witness: `natbib.sty:210`, `\let\bibstyle@egu=\bibstyle@copernicus`.
   Current unit `unit-298` covers only `\let`; its destination and donor become
   separate unknown/stored-macro obligations. The first option-state uncertainty
   is therefore recorded at offset 10031, and `\ProcessOptions` at line 350 stops
   bounded reading. There are 21 reached unknown `let` records across this specimen,
   including retained `fancyhdr.sty` and manuscript `math_commands.tex`.

   Implement a reusable scanner with a core YAML declaration. Capture the complete
   assignment without expanding or dispatching either operand. Copy an established
   meaning at assignment time and respect scope; keep an unknown donor explicit at
   the assigned target. Known assignment to an unrelated name must not by itself
   invalidate every boolean or option scope. Conversely, aliases of reading commands,
   predicates or setters must participate in resolution and shadowing correctly.

   Acceptance: optional equals/spacing/comments, donor subsequently redefined,
   nested scope restoration, known/unknown donors, aliases of booleans and reading
   handlers, repeated inputs, and exact source/emission locations. Explicitly bound
   unsupported prefixes or computed constructions; do not swallow them as a local
   assignment. `futurelet`, expansion-based name construction, hook execution and
   general expansion remain separate contracts. Rerun the specimen and expose the
   next witnessed limit; this increment does not promise to finish natbib.

2. **Structured dependency observation beyond retained-code reading barriers.**

   Witness: the independent survey of `natbib.sty` meets `option_context` at offset
   11473. It still inventories the remaining tokens, but the later
   `\InputIfFileExists{natbib.cfg}` at line 1241 appears only as a command-name span
   (`after_reading_boundary`, 44994:45012), without filename or branch metadata.
   This command currently has no reading declaration. No `natbib.cfg` exists in
   this specimen root, so this is a discovery limitation, not a demonstrated lost file.

   Add its bounded syntax/optional-resource knowledge and preserve structurally
   captured headers when execution cannot proceed. Reuse protected literal,
   definition and argument scanning; do not turn the fallback token census into
   active dependency edges. Record filename, owning context, search assumptions,
   optionality and materialization separately. Missing within a project is not
   proof of absence from every possible TeX search environment.

   Acceptance: present/absent local optional files, nested/repeated inputs,
   stored/skipped/literal decoys, computed names, changed reading/search context,
   retained-style rebasing and cached reads. Materialize only when the captured
   syntax and resolution context justify it; otherwise retain a located candidate.

3. **Evidence-based reading effects for the NeurIPS path.**

   Witness: the manuscript requests `[final]`; the early boolean tests resolve
   final=true and preprint=false. The trace identifies `\usepackage[verbose=true,
   letterpaper]{geometry}` at `neurips_2024.sty:75` (2082:2129, `unit-54`) as the
   first invalidator, because its reading binding is absent. Later unsupported
   `widowpenalty`, `clubpenalty`, `flushbottom`, `sloppy`, and a captured `normalsize`
   invocation are additional obstacles to proving the state at line 328.

   The nested `lineno` branch is expected to be inactive if those intervening
   operations preserve the established booleans, but the current reader has not
   proved that premise. Audit package/core source and encode the bounded effects
   through reusable machinery. Do not introduce an empty geometry shim, exempt
   arbitrary formatting-looking names, or disable uncertainty globally. This is
   more investigation than the first increment and may require several small contracts.

4. **Carry the reason for uncertainty into the retained-unit records.**

   The Fractal conditional record describes capture assumptions but drops the
   original reason its boolean became uncertain. The natbib diagnostic embeds an
   upstream source offset in text. Retain a structured cause reference when a
   known state becomes uncertain and link the later requirement to it. Use current
   unit identities and final artifact locations; avoid parsing message strings or
   requiring a future scheduler/context-snapshot implementation. Test repeated
   occurrences and causes inherited across input/scope boundaries.

No new bibliography or converted-asset failure was witnessed in this review.
BibLaTeX, multiple bibliography sites and broader subfile/resource cases remain
candidate extensions, to be prioritized with specimens rather than inferred from
the large interpretation count. Opaque `providecommand`/`renewenvironment` and hook
bodies remain preserved and unexecuted. XML construction, general expansion,
counters/labels, async scheduling and full binding migration remain downstream.

The latest iteration contains preparation evidence, not a fresh rendering or
relocation qualification. Historical font/xcolor outcomes must stay separate from
this ranking and be reassessed with paired receipts when optional validation resumes.

### Four authorized increments: implementation and verification

The earlier review above records the starting state. The following work implements
its four bounded increments; it does not claim full package-effect resolution.

1. **Scoped meaning assignment.** `AssignmentScanner` captures unexpanded `let`
   operands, and the dispatcher copies the donor's current meaning into the local
   scope. Boolean, setter, stored-definition and resolved-handler aliases share
   the existing scope machinery. Unknown donors remain explicit; character
   meanings are captured but their invocation remains deferred. Assignment prefixes
   stop before an unsupported assignment can be treated as local. Stored, skipped
   and deferred observations protect operands without executing them.
2. **Structured dependency observations.** The independent source survey now uses
   `SourceObserver` after a reading barrier. It retains declaration/literal/header
   structure under a stated entry-profile assumption without activating those
   candidates. `InputIfFileExists` captures its filename and both branches. A known
   local file with empty branches can use the ordinary cached input path. Computed
   names, nonempty branches and external-search uncertainty retain a requirement.
   Source inventory now includes local `.cfg` files. A missing inventory entry is
   not a proof of absence from an external TeX search path.
3. **Sourced reading effects.** Reusable handlers admit bounded literal integer
   assignments and YAML-declared meaning copies/layout effects. The initial
   declarations cover `widowpenalty`, `clubpenalty`, `flushbottom` and `sloppy`,
   with guards against shadowed prerequisites. LaTeX kernel sources, rather than
   names that look like formatting commands, justify these summaries. Geometry's
   source-backed declaration explicitly records unresolved configuration, key
   expansion and deferred-hook effects, including `geometry.cfg`. It is not a
   purity shim and still invalidates tracked state. General macro expansion and
   hook execution remain outside preparation.
4. **Linked uncertainty origins.** The reader registers an origin when tracked
   state becomes uncertain. Requirements and diagnostics carry `cause_ids`, and
   the manifest/journal carry the corresponding unit IDs, reasons and final
   payload locations. Repeated occurrences are distinct, scope restoration and
   option replay retain the cause, and failed publication clears locations through
   the existing record lifecycle. Dependency observations can link through their
   parent conditional unit; not every child duplicates the parent's cause IDs.

The dedicated-venv full suite ran **803 tests in 1236.514 seconds: 801 passed and
two optional compiler tests were skipped**. Final review added two regression
cases and tightened deferred-assignment operand protection and option-replay cause
propagation while that run was in progress. The updated assignment (10),
continuation (11), asset-fidelity (8), and uncertainty-cause (5) focused suites all
passed. Thus the full run plus these focused checks cover the final changes; this
is not a claim that a fresh 805-test full run was performed. Receipts are named
`20261025-reading-increments-suite`, `20261025-final-assignment-review`, and
`20261025-cause-replay-review` in the existing local receipt collection.

Specimen iteration **`20261025-reading-increments`** completed all four papers with
a 900-second per-paper budget. Its run began before the two final guard fixes
above; it is specimen evidence for the main increment, supplemented by the final
focused regressions, not an exact-final-revision rendering qualification.

| Specimen | Preparation | Bibliography entries / SVGs | Remaining preparation witness |
| --- | --- | --- | --- |
| Bayesian MARS | Complete under recorded assumptions | 58 / 10 | None recorded |
| Fractal | Partial | 33 / 9 | Possible `lineno` load; its parent conditional links to the geometry load-effect cause |
| FPCA | Complete under recorded assumptions | 60 / 24 | None recorded |
| DeadSalmons | Partial | 154 / 5 | Retained `fancyhdr.sty` and `natbib.sty` reading boundaries, with linked upstream causes |

All four materialized their known requests. Bibliography and figure counts match
the starting iteration; every recorded source occurrence has zero unaccounted
coverage, and all 14 uncertainty causes have mapped payload locations. Each source
file appears only once in its run's read ledger. Enclosing and intentionally
omitted unit locations remain distinct from missing locations.

The natbib survey now captures the entire `InputIfFileExists` header at
44994:45079, including `natbib.cfg`, the nonempty found branch, and empty missing
branch. It reports `not_in_inventory` with `external_search: unresolved`. The
retained-code requirements link to a captured unknown donor in `fancyhdr` and
uncertain load history in `natbib`, rather than hiding those origins in prose.
Fractal still cannot prove the `lineno` branch inactive: geometry load effects
and the captured `normalsize` invocation need more knowledge. The earlier
`20261025-bounded-let` attempt hit DeadSalmons' 180-second budget and remains as
timeout evidence; it is not counted as a successful four-paper run.

### 1. Reassess preparation from witnessed remaining work

Read the latest specimen manifests and requirements after cleanup. Establish a
short ranked list of actual preparation gaps, keeping interpretation obligations,
missing binding knowledge, source defects, and rendering-environment limitations
separate. Two specimens currently have complete preparation and two are partial;
unchanged output is a refactor check, not proof that every preparation goal is met.

For each next capability: identify a source witness, define the bounded contract,
add a regression test, and record a new specimen iteration. Prioritize reading or
dependency behavior that unlocks several real cases. Unknown package semantics
must not become a blanket reason to withhold `master.tex`.

Asset conversion, multi-database/Harvard bibliography handling, optional rendering,
relocation qualification, atomic publication, policy-driven emission, structured
logging, bounded lint/repair, and edit-aware provenance already have implementations.
Inspect their residual gaps; do not schedule them again as wholly unwritten systems.

#### Bounded effect summaries: implemented baseline, remaining closure

The shared write-set contract and selective invalidation are implemented. The
[effect-summary contract](../resources/bindings/effect-summaries.md) describes its
YAML fields, immutable Python records, supported scopes, call-time body analysis,
and conservative fallbacks. Bodies remain unexpanded; the analyzer records their
possible writes rather than executing them. Unknown callees, computed names,
mode/hook-dependent text and analysis-budget exhaustion retain uncertainty.

**Witness:** Fractal (2405.15943v3). The manuscript's `[final]` option resolves the
NeurIPS booleans early. The possible `lineno` load at `neurips_2024.sty:350` still
can't be resolved, because two operations invalidate all tracked state: the
geometry load at line 75 (`unit-54`) and a later captured `\normalsize`
invocation. Increment 1 already established, for `let`, that a known assignment to
an unrelated name must not invalidate every boolean or option scope. This increment
extends that principle to package loads, declared effects and bounded invocations.

**Contract:**

- An effect summary may declare a write set: the control-sequence names or
  namespaces it can assign (for example, a package's internal prefix), plus the
  registers and dimensions, catcodes, and hooks it registers.
- When an operation with a declared write set runs, only tracked state inside that
  set becomes uncertain. Booleans, option flags and meanings outside it keep their
  established values.
- Operations without a declared write set keep today's behavior.
- Computed or expansion-built names fall back to full invalidation.
- Deferred hook effects carry their own write sets and apply them when the hook
  fires.
- For a captured author or style redefinition, such as the `\normalsize` above,
  derive the write set from the captured body, and only when every operation in
  that body is bounded.

**Evidence:** write sets come from pinned source. Geometry 6.0 is now vendored at
TeX Live revision 78315 using `lctan --docs geometry`; its catalog/provenance JSON
and `ls-R` entry follow the existing infrastructure. `lctan --check` passes.
`geometry.yaml` cites that pin and explicitly keeps its closure incomplete:
configuration search/contents, dependency effects, option expansion and deferred
hooks remain unresolved. A namespace prefix alone is not a package-effect proof.

**Acceptance:**

- Fractal's `lineno` branch resolves as inactive, or the next witnessed obstruction
  is recorded.
- A write set that includes a tracked boolean still invalidates it.
- Namespace prefixes don't match unrelated names.
- Computed names fall back to full invalidation.
- Repeated loads and scope restoration behave as they do today.
- External-search uncertainty for `geometry.cfg` stays a recorded assumption.
- DeadSalmons' `fancyhdr` and `natbib` boundaries may or may not reduce to the same
  pattern. Check them rather than assuming.

**Observed result:** the `20261025-bounded-effects-verified` iteration still reports partial
preparation and complete materialization for both papers, with unchanged counts
(Fractal 33 references/9 SVGs; DeadSalmons 154/5), no unaccounted source intervals,
and no repeated reads. Fractal's `normalsize` now explicitly identifies its first
unbounded callee, `@setfontsize`; its `lineno` branch remains unresolved. In
DeadSalmons, `headwidth` aliases an unresolved register meaning and the assignment
at `fancyhdr.sty:313` remains a boundary; `natbib.sty:350` reaches `ProcessOptions`
with uncertain earlier load history. These are distinct remaining contracts,
not evidence that broader namespace exemptions would resolve both.

Final validation: the dedicated-venv suite ran **824 tests in 300.831 seconds**,
with 822 passing and two optional compiler checks skipped. All 24 emitted payload
files across the two specimens (master, retained code, bibliography and SVGs;
excluding diagnostic/provenance records) are byte-identical to
`20261025-reading-increments`. Both runs have zero unmapped unit locations and
valid uncertainty links. This qualifies the preparation increment, not a new
rendering or relocation claim.

Hook timing remains deferred: current summaries inventory hook effects but fall
back conservatively. They do not execute registration bodies or fire hooks.

### 2. Finish the preparation-to-interpretation handoff deliberately

The reader is reusable, and the finalized `master.tex` becomes the downstream
source of truth. Original-source provenance is preparation bookkeeping, not a
mandatory downstream dependency. Unit/requirement IDs and final artifact locations
already exist; preserve them through further edits and emission.

Before adding async machinery, inventory what the current records actually carry.
Then specify any missing per-unit `ContextRef`, parent-plus-delta context snapshots,
and context-effect classification (`none`, known effects, or unknown). Account for
definitions, catcodes, package activation, scope, and unresolved prior producers.
Do not equate an entry-state assumption with a fully resolved execution context.

Workers may interpret independent units once dependencies are resolved. Counters,
label-target changes, label keys, and scope events require an ordered fold before
reference resolution. This is later interpretation design; preparation should not
grow a scheduler or expand all macros to anticipate it.

#### Inventory of current records (`20261025-reading-increments`)

All four specimens meet the location invariants:

- Emission order follows source order within each occurrence.
- Copy segments preserve length; separators are their own `SYNTHETIC_SEPARATOR`
  segments.
- Source coverage has no unaccounted intervals, and replacements are linked.
- All 3,189 requirements have exact locations, in `master.tex` or in an emitted
  resource.

Units carry `id`, `kind`, `parent_id`, `origin`, `activity`, `activity_evidence`,
`location_status` and `locations`, and the manifest adds `uncertainty_causes`. Unit
spans in this specimen inspection nest without crossings. This supports structural
index fixtures; it does not prove that every future annotation forms a tree or
that existing ownership links are containment links.

What the handoff still lacks:

1. **Context references and effects.** No unit carries a `ContextRef` or a
   context-effect class. Uncertainty origins identify witnessed invalidations, not
   every unknown producer: no cause may be minted when nothing tracked changes or
   a value is already uncertain. Bounded summaries now describe some retained
   invocations. A complete per-unit effect inventory and context versions remain.
2. **Stable ids.** `location_contract` declares `id_scope: preparation_run`. Relation
   records and a worker journal need ids that stay the same for the same
   `master.tex` analysis. Deterministic enumeration must be scoped to an analysis
   revision including reader/binding inputs and retained reading resources, not
   just the master's bytes. Document identity and analysis identity are distinct.
3. **Parent links versus containment.** `parent_id` doesn't follow span containment.
   Many `argument` units contain other units whose parent is elsewhere, apparently
   the owning command. Counting leaf pairs that nest without a parent link: 611 in
   Bayesian MARS (409 of them deferred regions inside arguments), 510 in Fractal,
   3,916 in DeadSalmons, and none in FPCA. If `parent_id` means ownership, name it
   that way. Structural containment can be derived from the spans, since they nest
   cleanly.
4. **Tiling.** Leaf units cover 35.0% (Bayesian MARS), 42.7% (Fractal), 39.9% (FPCA)
   and 97.0% (DeadSalmons) of `master.tex`, because plain text runs are not units.
   Assembly by an in-order walk needs leaves that cover every character exactly
   once.
5. **Master index.** Items 3 and 4 need no new preparation records. Build a
   structural index of `master.tex` by re-reading it with the same reader at the
   end of preparation. It holds a containment tree derived from the spans, text-run
   leaves filling the gaps, units, contexts, label observations and line starts.
   The [master-index/context design](../../../../aipithicus-issues/LaTeXAI/briefs/pytexml-master-index-contexts.md)
   refines the source-span brief (§9.6), including equal/empty/fragmented spans and
   incomplete reading contexts. Reread qualification compares surviving deferred
   content and reading behavior; raw preparation IDs/counts need not be identical.

### 3. Settle binding contracts before bulk adaptation

Continue from the declarative-binding and binding-ontology briefs in the issues
workspace, especially the ontology brief's reopened authoring-surface question.
The runtime needs canonical validated knowledge; the best authoring surface is
still open. Current YAML improvements do not settle YAML versus declarative Python,
Starlark, signature strings, tables, or a generative mechanism such as Jinja.

Use a small witness set to test candidate contracts: configurable literals,
factories/declarations, symbol families, and citation behavior. Establish the
division between reusable execution algorithms and package-specific knowledge,
including dependencies, state effects, capture, and structural assembly.

Raw TeX package sources are the authority. Existing Perl bindings are useful
evidence and shortcuts for investigation, not an executable fallback or a guarantee
of mechanical translation. Preserve package-level atomicity and aligned resource
identities. Final custodian recipes, migration tooling, skills/MCP support, and
systematic harvesting follow the contracts and their qualification examples.

## Invariants and restart instructions

- Preserve raw inputs. Preparation selects and transforms emitted payload content.
- Keep I/O cached and intentional; no permanent copies of original assets merely
  to make rendering convenient. Rendering remains optional and separate.
- Keep execution routing in the structural dispatcher. Capture of definitions or
  deferred bodies is not execution; absence of a binding is not proof of inactivity.
- Keep `reading` independent of `prepare`. Preserve source/occurrence identity,
  edit-aware locations, explicit uncertainty, and reusable logger primitives.
- Consult earlier briefs before deleting apparently unused resource fields;
  preserve anchored later contracts as documented deferrals.
- Work on `main`, honor unrelated changes, and make focused commits. At handoff,
  `issues/clumped-problems.md` was an unrelated untracked file and was left untouched.
- Use the project's dedicated interpreter, not ambient Python:

```powershell
Set-Location D:/aipithicus/LaTeXAI/python/PyTeXML
& D:/aipithicus/LaTeXAI/python/.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'
```

Allow enough outer runner time; a timeout is not a completed test gate. Keep
receipts and specimen iterations in their existing local run collections, and
reuse the harness's content sharing. No new rendering qualification is implied by
an unchanged preparation payload.

Suggested next request: **Reassess the latest specimen requirements and rank the
remaining preparation gaps by source witness and bounded contract. Keep broader
binding design and asynchronous interpretation as separate work.**
