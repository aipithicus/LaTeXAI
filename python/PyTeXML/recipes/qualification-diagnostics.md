# Qualification diagnostics

Preparation and optional validation have separate contracts. Diagnostic rules
live in `resources/validation/diagnostics/`, not in package bindings or the
preparation dispatcher. Python owns log normalization, evidence collection and
check combination. YAML owns recognized diagnostic patterns, extracted fields,
stable codes, phases, categories and remediation descriptions.

## Evidence and derived views

Version 2 rendering/relocation receipts record:

- Checks for staging, process execution, TeX compilation, PDF generation, output
  inspection and dependency auditing. `not_run`, `not_requested`, `inconclusive`,
  `failed`, `timeout` and `passed` remain distinct.
- Structured diagnostics with stable codes, occurrence IDs, extracted details,
  rule identity and raw log evidence. Repeated messages retain every occurrence.
- Log hashes, rule-catalog hashes, input hashes, compiler binary and rendering
  driver hashes, and configured font/bundle options. These do not snapshot the
  compiler cache or font directory contents.
- Optional original-source and XDV checks, collected in the same configured
  invocation. Each attempt has its own input hashes, log and check records.

`src.validation.assessment.summarize(receipt)` is the sole classification
projection. The CLI and regenerated specimen index call it when displaying a
result. Neither a summary nor a baseline-match verdict is saved in the receipt.
The existing lowercase operational `status` is a serialization-time projection;
it is never evidence for classification. Editing it cannot make failed checks
qualify. Baseline matching is recomputed from the two attempts' diagnostics.
Old receipts without structured checks remain historical records, not silently
upgraded diagnostic evidence.

| Classification | Evidence |
| --- | --- |
| `QUALIFIED` | Requested output validated; successful execution and dependency audit |
| `PAYLOAD_DEPENDENCY_FAILURE` | Recorded external or unresolved filesystem input |
| `ENVIRONMENT_LIMITATION` | Recognized resource/capability diagnostic in a failed phase |
| `BASELINE_REPRODUCED` | Same specific diagnostic signatures in comparable original/prepared attempts |
| `PREPARED_ONLY_FAILURE` | Original render succeeds and prepared render fails in the paired configuration |
| `INDETERMINATE` | Other outcomes, including unknown errors and insufficient evidence |

Several findings can coexist. A payload dependency failure takes precedence over
an environment limitation in the headline, followed by baseline and prepared-only
findings. The complete findings and nonpassing checks remain available.
An environment warning in a successful run does not by itself establish a failure.
Generic engine termination messages do not establish baseline equivalence.

`BASELINE_REPRODUCED` says the observed diagnostic also affects the original; it
does not certify preparation or assign blame to the author. `PREPARED_ONLY_FAILURE`
leaves preparation and the rendering adapter open to investigation. A font failure
may concern TeX resources, lookup configuration or generation capability, rather
than a missing operating-system font.

A valid partial dependency receipt is inspected after a failure or timeout, but
cannot establish closure for a completed route. No receipt is not the same as
an empty set of external dependencies. XDV evidence can establish compilation
isolation only for the identical prepared input fingerprint; it never passes a
requested PDF qualification. None of these checks certifies visual/content fidelity
or every possible conditional configuration.

## Wrapped logs

The Tectonic profile specifies the 79-column convention and known message
boundaries. Normalization precedes matching and rejoins inferred hard-wrap
continuations without adding spaces, including inside filenames or diagnostic
arguments. It also recognizes Tectonic prefixes on already wrapped TeX messages.
Blank lines and recognizable new records remain boundaries. Unrelated short lines
are not concatenated.

Every normalized match retains original byte offsets, physical line ranges, raw
text and the positions of inferred joins. Malformed UTF-8 log bytes survive via
surrogate escaping and are counted explicitly. A natural line ending exactly at
the wrap width is ambiguous without additional engine metadata; the receipt does
not disguise the inference. The current character-counting profile is for the
XeTeX console route, not a universal normalizer for every TeX engine.
The log hash covers the complete retained file; `parsed_bytes` identifies the
compiler-output prefix, excluding any final adapter footer.

See the [TeX printing implementation](https://tug.ctan.org/info/knuth-pdf/tex/tex.pdf),
section 57, for the width-triggered output mechanism. Error context truncation is
not repaired by this normalizer.

Locations explicitly printed by the compiler are retained. A location in the
staged main is adjusted for the adapter's one-line bootstrap and refers to the
input artifact (`master.tex` on the prepared side). Unknown file context is not
invented. Same-phase links between terminal/supporting and primary diagnostics
are associations, not claims of a proven causal chain.

## Growing the catalog

1. Capture a new specimen's raw diagnostic and its check outcome. Keep a minimal
   representative excerpt in `tests/fixtures/validation/` with no temporary paths
   or manuscript content unnecessary to the failure.
2. Add a rule to the appropriate YAML resource. Its identity must match the
   filename; its schema/version, code, phase, component, severity, role, category,
   regex patterns, named signature fields, witnesses and remediation are explicit.
3. Test the witnessed message, repeated emissions, a nonmatching near-neighbor,
   and relevant wrapping. Baseline signatures omit source paths and line numbers.
4. Bump the resource version when changing its interpretation contract; the
   receipt also records the semantic catalog hash. Retain unclassified messages
   rather than broadening a rule without evidence.

The initial semantic catalog covers the witnessed DeadSalmons package-option
clash and FPCA font/driver failure. The relocation catalog explains structured
audit outcomes already exercised by harness tests. No speculative package-error
catalog or automatic author-source repair is introduced.

## Optional diagnostic probes

Add `--diagnose` to specimen `qualify` to investigate failed renders. It may run
one XDV attempt and one original-source attempt, each subject to the configured
timeout. A known TeX-stage failure skips the redundant XDV attempt. The specimen
harness verifies that original and prepared checkpoint fingerprints still match
before comparing. Raw originals are staged only for their explicitly requested,
separate baseline attempt; they stay hidden from prepared/XDV attempts.

For standalone relocation, use `--diagnose --raw-source <source> --baseline-main
<main.tex>` to enable the original comparison. Without a baseline main, only the
applicable XDV probe is run. Logs and reports survive; temporary input copies,
SVG rendering derivatives and XDV products are removed. Probes do not mutate
preparation results, install dependencies, or correct the original source.
