# Resource failure recovery

Preparation defaults to `recovery="best_effort"`. Diagnosed resource failures
produce a partial payload and do not cancel later readable requests. The API's
`recovery="strict"`, or CLI `--recovery strict`, rejects a partial result after
the traversal, source survey and materialization attempt. Strict rejection keeps
the previously published payload; the exception carries the current manifest,
and the attempt journal retains the diagnostics. Without an earlier payload,
the failed attempt also leaves its manifest. Neither policy catches arbitrary
implementation exceptions or output-publication failures as missing resources.

## Facts and delivery

Resource occurrences extend the existing `dependencies` and `requirements`
records. `item_id` is unique within a preparation attempt; the journal's attempt
identity disambiguates reruns. Each record identifies the requesting source unit,
resource kind, purpose, requested/resolved name, outcome, partial knowledge,
causes/remedy, affected domains and recovery disposition. Search evidence states
the configured scope. An unspecified external search yields `unresolved`, not
`absent`; ambiguity, source access errors and processing failures are distinct.
An unevaluated filename keeps its source expression and remains unresolved.

An unfulfilled active request gets a generated text marker such as
`[PyTeXML asset absent resource-3]` at its source occurrence in `master.tex` or
the retained source payload. Its `resource.tombstone` log event and requirement
use the same item identity. The marker is a recovery projection, with source
replacement provenance; it does not claim bytes or dimensions for the missing
file. The record preserves the original expression. No dummy file is created at
the requested name. Rendering equivalence is not claimed for recovered regions.
This is a literal-text extraction marker; native typesetting under unusual
catcodes or in a preamble has not been qualified.

Markers are projected only after splice rollback and resource conversion.
An observed failure therefore survives retention of its containing input.
Repeated occurrences retain separate identities. If an occurrence cannot be
projected, its disposition explicitly reports opaque source rather than claiming
a placed marker. Undecodable child resources retain their exact bytes under
`opaque-resources/`, with a distinct artifact identity and byte coordinate domain.

Known authored file-test branches run through the normal engine first. An absent
probe with a selected fallback is recorded as `authored_branch`, not an active
missing item. The supplied job BBL can similarly make its original databases
unnecessary for this extraction. Gauntlet-master's deliberately absent
`gmlogo.pdf` is a probe witness; recovery must not create or require that asset.

## Program state and continued discovery

An unavailable input/package/class is not successful empty execution. Captured
author meanings, registers, hooks and load evidence acquire uncertainty. Reading
continues through the same dispatcher using the caller's lexical and structural
state as an explicit recovery assumption. `recovery_contexts` identifies the
failed request, the resume boundary and assumed/unestablished domains; subsequent
units carry `recovery_context_ids`. A recovered observation is not a fact about
the original program under all possible missing definitions.

An uncertain package load guard remains a possible load, with its original
invocation preserved. A preceding unavailable program may have supplied that
package, so a later source name is not automatically an active missing resource.
Adapted baseline classes/package contracts retain their existing preparation
route; otherwise, an explicit closed resource search can establish a missing
package. This is not native package-execution or rendering qualification.

Physical input boundaries remain important. Existing malformed-source recovery
may retain a child and resume its caller, or preserve an unframeable root suffix.
The independent source survey still reports captured candidates and unreadable
regions. It does not turn candidate requests into executed requests, and it does
not prove exhaustive discovery through opaque or computed source. Full semantic
recovery, arbitrary resynchronization and a universal failure taxonomy remain
broader planned work in the staged-pipeline brief.

Keep the outcomes separate:

| Field | Meaning |
| --- | --- |
| `preparation_status` | Whether the currently admitted preparation work is complete |
| `materialization_status` | Delivery of original requested resources; `partial` includes unavailable resources |
| `original_resource_status` | Whether original resource obligations are satisfied, unsatisfied or unresolved |
| `recovery_status` | Whether diagnosed resource tombstones were placed; no global extraction-quality claim |
| `acceptance_status` | Accepted, recovered, or rejected by strict policy |
| `source_dependency_closure` | Source-visible closure under the recorded reading assumptions |

The first Q1 gate is exercised by `tests/test_resource_recovery.py`: independent
failures, content on both sides, authored fallback, state consequences, rollback,
unreadable/ambiguous/computed names and strict rejection after discovery. The
execution checkpoint records actual test and specimen results; the broader
staged-pipeline contract must not be read as implemented coverage.

A fresh preparation of a recovered payload currently reads the markers as text.
It does not import the earlier manifest's typed state consequences or item
lineage. Keep that manifest and journal with the payload; marker survival alone
does not establish replay equivalence. The checkpoint records the all-nine
reread observations and the working queue retains this follow-on.
