# PyTeXML cleanup and development handoff

Recorded 2026-10-24 after Batch 4; updated 2026-10-25 for Batches 5A and 5B on `main`.
The later development sequence remains a plan, not authorization to implement it all.

## Where we are

The five-batch cleanup plan is in [astra-refactor-plans-part1.md](astra-refactor-plans-part1.md).

| Batch | Completed work | Commit |
| --- | --- | --- |
| 1 | Surgical failure-location reset and shared record traversal | `cd468c5` |
| 2 | Shared helpers/defaults, explicit scanner interfaces, named positional state | `cb0b3f3` |
| 3 | Manifest record construction and lifecycle ownership | `6a7da8d` |
| 4 | YAML option consumers/validation, declaration indexes, cached literal templates | `a382b5a` |
| 5A | Explicit preparation request; one publication and rollback owner | `f8cf250` |
| 5B | Explicit inspection inputs; session-owned emission, observations and payload edits | This update |

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

## After Batch 5: proposed sequence, not settled implementation scope

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
