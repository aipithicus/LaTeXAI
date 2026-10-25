# Bounded lint and justified repairs

Preparation collects lint from established reader and source-load observations.
It does not run an external linter or scan every character with document-wide
regular expressions. Findings live in `manifest.lint` and appear as `lint.finding`
events in the structured journal. They carry stable run-local IDs, reader unit
IDs, source occurrence coordinates, final artifact locations, evidence and
remediation guidance. The original sources are never edited.

[`resources/lint/preparation.yaml`](../resources/lint/preparation.yaml) owns the
diagnostic vocabulary and remediation knowledge. The catalog records a schema,
version and identity matching its filename; the manifest records its digest.
[`prepare/lint.py`](../src/prepare/lint.py) supplies the reusable rule projection
and bounded repair check. Rule knowledge, user policy and reader machinery have
separate owners. The dispatcher remains responsible for execution routing.

## Reporting and limits

The initial catalog recognizes reader-observed invalid characters, group,
conditional, environment, literal, argument/definition and math boundaries.
These are observations under the current reading assumptions, not a guarantee
that the author source is defective: an unresolved package or macro may explain
an apparent boundary. Missing knowledge remains a requirement, not a lint error.
No guessed closing delimiter or environment name is inserted.

The reader protects literals, stored definitions, skipped branches and deferred
regions according to their reading contracts. The linter does not independently
reinterpret their contents as ordinary source. A scanner may report a lexical
error there, but it cannot be resumed by the ordinary-character repair.
Inspection after an unresolved reading boundary remains incomplete; consult
the manifest's requirements, input occurrences and source survey. No findings
does not mean exhaustive coverage, successful compilation or semantic fidelity.

## Explicit repair policy

The default preparation policy reports findings without applying repairs:

```yaml
linting:
  mode: report
  repairs: []
```

An explicit custom preparation policy can authorize the implemented repair:

```yaml
identity:
  name: checked_repairs  # Save as checked_repairs.yaml.
linting:
  mode: repair
  repairs: [drop_invalid_character]
```

Pass that policy path to `preprocess_paper(..., policy=...)`. Other policy fields
use preparation defaults. `mode: off` disables lint findings and repairs while
retaining the existing unresolved-reading diagnostics. Unknown settings and
repair names are rejected; selecting repair mode alone authorizes no edits.

`drop_invalid_character` admits exactly one literal catcode-15 character between
adjacent ordinary ASCII alphanumeric characters. The left neighbor must already
be an ordinary, untransformed reader token; both neighbors must currently have
letter/other categories. The failure must occur at the dispatcher's normal token
fetch, with no partially consumed scanner header or body. There must be no prior
unresolved/deferred work, and the occurrence must be emitted into the master.
Retained local code is not repaired by this contract.

A small in-memory mouth check compares the surrounding tokens and exit state
after explicit invalid-character discard with the proposed deletion. This is
comparison against the declared recovery operation, not a claim that erroneous
input was already valid. The recovery reference is the invalid-character branch
in [Knuth's tex.web](https://raw.githubusercontent.com/TeX-Live/texlive-source/trunk/texk/web2c/tex.web),
under “Decry the invalid character and goto restart.” The restriction excludes caret notation, control-word
joins, physical-line boundaries, adjacent invalid characters, synthetic endlines
and arbitrary Unicode scrubbing. The live catcode table determines invalidity;
the code point alone does not. Decoding failures are not repair candidates.

Only after the precondition and postcondition hold does policy allow the
dispatcher to resume the exact failed cursor. The reader's default remains a
sticky error. The preparation adapter emits a mapped deletion, with a tombstone,
before/after text and a final zero-width `master.tex` location. It uses existing
edit tracking; no source file is reopened or overwritten for the check.

Repair states distinguish `proposed`, `ineligible`, `applied_in_memory`, `applied`,
`not_emitted` and `not_published`. If later continuation rolls back the enclosing
input, the repair is not claimed as emitted. If publication fails, a retained
failure manifest does not advertise the attempted artifact locations. Artifact
hashes and final locations work without the original-source provenance sidecar.

## Package and preamble evidence

The next layer uses ordered source-visible load facts already collected by
preparation. It reports two cases:

- A later package/class request adds options absent from its first observed
  request. Evidence contains initial, requested and added options, and links
  the first load to its final master or retained-code location.
- Options are forwarded after the target has already been requested. The
  finding links that declaration to the earlier load for review.

Literal options forwarded before the first load are included in the comparison;
subset requests are not clashes. Skipped and stored declarations are not treated
as executed loads. Unknown commands and packages do not supply invented load
facts. Loads performed implicitly by unavailable bindings remain outside this
source-visible check. Several clashes in a multi-package declaration produce
separate findings.

These diagnostics propose inspection of load order and intended options, not an
automatic package-specific fix. Moving a declaration or unioning options may
change behavior and requires package knowledge and validation evidence. The
optional rendering adapter's log diagnostics remain an independent observation;
matching lint and compiler messages are not automatically treated as one result.

## Verification

`tests/test_preparation_lint.py` covers cursor ownership, protected regions,
category changes, forbidden joins, report/repair policy, repeated inputs,
continuation rollback, final addresses, idempotence, and related load evidence.
Reader, pipeline, emission and qualification suites continue to run independently.
Adding a new repair requires its own applicability proof, witnessed fixtures,
negative cases, edit accounting and a postcondition; adding a diagnostic does
not automatically authorize its repair.
