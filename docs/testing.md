# Testing

LaTeXAI inherits LaTeXML's fixture shape and driver and narrows what they mean. This document defines a fixture, says how suites are laid out and run, and fixes where runtime output goes.

## 1. What a fixture is

A fixture is one case in a suite directory under `t/`:

| File | Role | Read by the driver |
| :--- | :--- | :--- |
| `t/<suite>/<case>.tex` | the source, byte-exact; under capture the bytes are part of the contract | yes |
| `t/<suite>/<case>.xml` | the IR golden; the only thing the driver asserts against | yes |
| `t/<suite>/<case>.pdf` | an optional witness of what TeX itself makes of the same source; regenerated at authoring time only | no |
| `t/<suite>/<case>-post.xml` | a post-processing golden; used only by suites that exercise a math oracle | yes, when present |
| `t/<suite>/*.sty`, `*.cls`, `*.ltxml` | support files a case needs; the suite directory is on the search path | as loaded |

A `.tex` without a matching `.xml` is skipped, not failed. A golden is therefore a deliberate act: nothing is covered until someone has looked at the IR and committed it.

The witness PDF is never consulted by a test. It exists so that a person revising a golden can compare the IR against an independent reading of the source. A witness produced by a different TeX distribution than the one recorded in its header comment is stale, and a stale witness is worse than none. Suites carried over from upstream keep their witnesses as inherited evidence; new fixtures include one only when the case turns on a typesetting question.

## 2. Suites and drivers

A suite is a directory plus a two-line driver:

```perl
use LaTeXML::Util::Test;
latexml_tests("t/<suite>");
```

The driver digests every `.tex` in the directory with a fixed core configuration (no preload, no search paths beyond the suite directory, comments off, path processing instructions off, quiet), canonicalizes the DOM, and compares it to the golden as strings. Options for a whole suite go in the driver call; per-case options are not supported and are not wanted.

**Strict suites.** Upstream's driver compares XML and nothing else. An undefined macro, a missing package, or any other error the engine counts leaves no trace in the digested document and is suppressed from the log, so a golden generated from a broken run passes forever. LaTeXAI adds a `strict` option:

```perl
use LaTeXML::Util::Test;
latexml_tests("t/<pkg>", strict => 1);
```

A strict suite fails a case whose conversion reported errors (engine status 2) or a fatal (3), before the golden is compared, with the engine's status message as the diagnostic. Cases whose name contains `fatal` are exempt, as upstream's are. Package suites are always strict. Inherited upstream suites stay lenient because some of their goldens deliberately exercise error paths.

**Goldens are written by `lgold`, not `lxml`.** The CLI always emits a `<?latexml searchpaths=…?>` processing instruction that the driver suppresses, so a golden written with `lxml` fails at line 1. `tools/dev/golden.pl` digests with the driver's own configuration, refuses to write if the engine counted errors, refuses to write if the golden lint fails, and refuses to overwrite without `--force`:

```powershell
lgold t\<pkg>\<case>.tex             # writes t\<pkg>\<case>.xml
lgold --force t\<pkg>\<case>.tex     # replace after an intended change
lgold --check t\<pkg>\*.tex          # digest and lint, write nothing
lgold --lenient t\<pkg>\<case>.tex   # skip the lint for a case that exercises the failure on purpose
```

The lint is mechanical and small: every `labelref` in the document has a matching `labels` target, no `ltx:ERROR` element is present, and no engine-internal `\lx@…` control sequence leaked into text or a `tex` attribute. Each check corresponds to a golden that was committed with the defect in it.

Read the golden before committing it, and read it against something the binding did not produce. The tool guarantees the golden is what the driver will see and that the conversion was clean; it does not know whether the structure is right. A binding that drops a label produces a golden with no label, and that golden diffs clean against itself forever. The reading is done against the expectations written from the package source before the golden existed, with the checklist in the recipe (`docs/recipes/package-bindings.md`, section 5).

Suites are grouped by what they exercise, following upstream's numbering by engine layer:

| Range | Layer |
| :--- | :--- |
| `00`–`09` | unit and tokenizer |
| `10`–`39` | expansion, grouping, digestion, fonts, encoding, keyval |
| `40`–`49` | math, capture |
| `50`–`59` | structure, namespaces, alignment, theorems, AMS |
| `60`–`69` | graphics |
| `70`–`79` | parsing |
| `80`–`89` | complex documents and one suite per package or class: `t/<pkg>/` driven by `t/8N_<pkg>.t`, as upstream does for `babel`, `moderncv`, `expl3`; when the two-digit slots run out, three digits keep the order (`t/851_extarrows.t`), as upstream's `931_epub.t` does |
| `90`–`99` | post-processing and driver behaviour; includes the independent Markdown projector in `t/98_markdown.t` |

The Markdown projector's bespoke driver, `t/98_markdown.t`, supplies XML directly and asserts manuscript behavior: reading order, references, TOC anchors, mixed content, bibliography fields, tables, and explicit residue. It compares both traversal strategies and verifies that projection leaves the supplied IR unchanged. It does not mint engine goldens. Corpus traversal timing is a separate experiment described in [Markdown projection](markdown-projection.md).

## 3. Binding fixtures

Every binding has its own suite, `t/<pkg>/`, with a driver `t/8N_<pkg>.t`, following upstream's per-package layout (`t/ams`, `t/babel`, `t/moderncv`). Cases inside are named for the construct they exercise, as `t/ams/` has `cd`, `dots`, and `amsdisplay`; a small binding may have a single case. Together the cases are complete documents that load the package and exercise each construct the binding claims in its header. A construct the binding stubs to nothing still appears in a fixture, so the golden records that it is dropped. The cases also contain, verbatim, the forms found in the gauntlet corpus for the package (recipe section 1): a suite whose cases were written from the binding's feature list has covered the binding, not the package, and the constructs documents actually use are exactly the ones such a suite misses.

Package suites are strict (see section 2), so a fixture that fails to load something its constructs depend on fails the suite rather than freezing the error into a golden. Binding goldens are produced with capture **off**. The binding is judged on the structure it emits, the golden stays free of provenance attributes, and the fixture remains portable to a contribution fork. Capture provenance over a binding's output is asserted separately by `t/45_capture.t`, which may reference a fixture from a package suite but does not own it.

A binding that replaces an existing passthrough or hybrid keeps the same case name. The before-and-after outputs are compared during minting (see the recipe) but only the after is committed.

## 4. Capture fixtures

`t/45_capture.t` is a bespoke driver, not a `latexml_tests` suite. Its fixtures under `t/capture/` exist to exercise provenance, byte custody, the ledger, and the schema, and its goldens are normalized only for the portable base path and build revision. Cases that need a binding load one from `lib/`; they do not duplicate the binding's structural assertions.

`t/46_source_fidelity.t` checks the ordinary and capture readers against the same active encoding, including changes within an open file, malformed UTF-8 groups, and already-decoded strings. It checks byte spans and diagnostic counts independently. Fresh conversions then serialize and reparse LF, CRLF and CR sources and compare every captured formula or callsite with its recorded byte range, including nested `equation`/`aligned` and bracket displays. These assertions cover the actual Core serializer, not a LibXML substitute.

`tools/dev/capture-fixture.pl --golden <source.tex> <golden.xml>` writes a capture golden with this driver's configuration and normalization. Run it with the repository Perl and `-I lib`, in a fresh process: package definitions can produce redefinition warnings across repeated engine states. The helper refuses any engine warning or error. Without `--golden` it writes the unnormalized capture document for assertions and schema validation.

Use `--compact` for tree-comparison inputs and load them with `keep_blanks => 1`. This prevents serializer indentation and parser defaults from being confused with manuscript whitespace. Goldens retain their existing formatting and normalization.

## 5. Where output goes

- **Logs.** Every `latexml` and `latexmlpost` run writes `<jobname>.latexml.log` to the current directory unless told otherwise. Tests and aliases pass `--log` so the file lands under `temp/logs/<runstamp>/`, one directory per run. The stamp is `LATEXAI_RUNSTAMP` when set, otherwise minted when the aliases load (once per `pwsh_exec` command) or when a bespoke driver starts. `lrun` sets the variable for the current process, so `lrun; ltst t/851_extarrows.t; lxml …` in one command groups everything under one stamp, and `ltst` exports it to the drivers it runs. A log at the repository root is a bug in whatever wrote it.
- **Driver output.** The shared driver writes its comparison copy beside the fixture and deletes it. Bespoke drivers write to `File::Temp` or to `temp/t/<test>/`, never beside the fixture and never to the root.
- **Witnesses.** Generated into `temp/bindings/<pkg>/` or `temp/t/<test>/`, then moved beside the fixture by hand when they are meant to be kept.

## 6. Running

From the repository root, through the `pwsh_exec` profile. Run `lgen` first on a fresh clone or after a grammar edit; it produces the two generated modules into `lib/` so the drivers need only `-I lib`.

```powershell
lgen                          # compile grammar + stamp version into lib/ (idempotent)
ltst t/856_nicematrix.t       # one package suite
ltst t/40_math.t t/70_parse.t # the drivers covering a touched layer
ltst t                        # everything; required for changes under Core/ or Common/
ltbatch -Selection math       # same drivers as a TAP batch (requires CDXSCI_ROOT)
lcfg                          # runtime/selection preview; no tests
```

`ltst` remains serial `prove` for a focused driver. `ltbatch` (`scripts/test-run.ps1`) plans one job per `t/*.t` driver, isolates output under `temp/t/test-batches/<stamp>/`, and uses the shared executor. Named selections (`math`, `capture`, `bindings`, `full`) are in `scripts/policy.psd1`. Do not overlap a TAP batch with a capture-audit `--jobs` run in the same checkout until their writes are proven disjoint.

For MCP setup, long calls and timeout ownership, use the
[PowerShell workflow recipe](recipes/powershell-workflows.md).
TAP runs retain `native.json`, full executor evidence in `executor-execution.json`, and the
domain summary in `execution.json`; missing or malformed worker evidence fails the batch.
Run `scripts/tests/native-regressions.ps1`, `scripts/test-qualify.ps1` and
`scripts/test-timeout.ps1` to qualify these infrastructure paths.

Report failures with the harness output, not a summary.

## 7. Capture regression audit

`lgold --check` digests and lints; it does not compare existing goldens. The audit has two independent checks: exact raw capture-off bytes and capture-on/off tree and diagnostic differences. Run through the repository PowerShell profile, from the repository root:

```powershell
lgen
$auditPerl = "$env:PERL_ROOT/perl/bin/perl.exe"
& $auditPerl -I lib tools/dev/capture-audit.pl record --output temp/t/audit-baseline
& $auditPerl -I lib tools/dev/capture-audit.pl compare --baseline temp/t/audit-baseline --output temp/t/audit-replay
```

No driver arguments selects every `t/*.t` driver. Append named drivers for a bounded audit; comparison requires the same selection. `--jobs N` sets independent driver workers (default ten). Worker count remains recorded execution provenance; comparison contract 2 does not mistake scheduling for compiler configuration. Keep concurrency fixed when measuring performance. Record and replay run separately, with fixed inputs. Every output directory must be new. Record is an explicit baseline operation; compare never modifies or renews its baseline, including on failure. Do not inject the observer through `PERL5OPT` or use the superseded `LATEXAI_CAPTURE_OFF_*` / `LATEXAI_CAPTURE_ON_AUDIT` interface.

To retain the older raw-byte check while establishing a new paired baseline, add `--legacy-off <old-directory>` to record. This reads the original per-driver JSON/XML layout and fails on changed, added or omitted conversions; it never overwrites those files. Generic historical difference reasons cannot reconstruct missing historical capture-on trees. A newly recorded pair describes its own recorded input state, not a reconstruction of the historical run.

The audit observes `LaTeXML::Util::Test` conversions before golden normalization and retains their original raw bytes. It also runs fresh off/on controls in separate Perl processes with the driver's complete Core options, differing only in capture. This avoids confusing repeated-pool warnings in the prove process with capture effects. Original driver diagnostics and their differences from the fresh off control remain separate evidence. It records suite inventories, skip reasons, conversion failures, and drivers with zero observed conversions. Direct conversions outside `convert_texfile_as_test` are excluded from this count. In particular, `t/45_capture.t` owns fresh-process capture fixtures; the extpfeil, scalerel, nicematrix and tikz-cd drivers also contain direct checks outside the observer. Post-processing, daemon, unit and Markdown tests are not implicitly capture comparisons. `t/99_capture_audit.t` independently exercises the helper and gate in fresh processes.

Each driver report retains fixture identities, options, source/support hashes, raw and stripped XML (`driver-off`, fresh `off`, fresh `on`), helper requests/results/logs, engine status and error-node counts. `run.json` reconciles the complete selected driver set and the ordinary harness result. A record is qualified only if all selected drivers report, conversions are accounted for, the ordinary tests pass, and the input state stays fixed during the run. It can contain explicitly recorded residuals. The manifest records the checkout and dirty input identity (including restorable uncommitted content), generated revision, library/test/tool file hashes, runtime and relevant environment. Freeze these inputs during conversions; a unique output name alone is insufficient. Generated version metadata is distinct from Git identity.

The comparison dispositions are deliberately conservative:

- An unchanged known residual passes and remains in the report.
- A newly different fixture, changed residual, removed residual, changed fixture/options/support inputs, or coverage change fails for review.
- Raw capture-off changes fail independently, even when the capture-on and capture-off trees still agree.
- Process failure, invalid/missing helper output and conversion failure remain distinct from IR differences. Engine diagnostics and `ltx:ERROR` nodes are separate observations.
- Ordinary suite success cannot override audit failure. An audit implementation change requires an explicit evidence transition; the comparator cannot silently reinterpret an old baseline.

`CaptureStrip.pm` removes capture attributes, unused capture namespace declarations and the capture ledger directly beneath the actual document root, regardless of that root's name or namespace. Other namespaces' ledgers remain manuscript content. It retains comments and every text node, including whitespace-only prose and verbatim content, and canonicalizes the DOM directly without re-parsing it. This includes text immediately before and after a ledger, even beside a comment or under `xml:space="preserve"`: adjacency cannot identify formatting. The audit compares live DOMs; compact LibXML serialization avoids adding indentation to file-based controls. Without a declared normalization contract, formatted historical files retain all text and formatting differences fail. The Core serializer currently ignores its format argument, so `Core::Document->toString(0)` does not produce that compact input. Both original serializations remain available for inspection; no engine repair is performed by the comparison.

A reviewed residual transition is a separate, explicit compare input: `--transitions FILE`. The file is `latexai/capture-transition/1` and must pin the baseline `run.json` SHA-256. Each entry names one case key, the exact prior `residual` object, and `removed-residual` or `changed-residual`. The claimed disposition must occur in the raw comparison; matching prior/current signatures alone cannot authorize a no-op review. Only hash-matching listed entries can clear observed dispositions; unused entries, stale signatures, remaining differences, extra unlisted residual changes and diagnostic drift still fail. Rejected no-op entries produce `transition-not-observed`, remain unconsumed, and also fail the run's unused-entry gate. Raw issues remain in the driver reports; `run.json` records the applied file and the qualified verdict. There is no count-based, wildcard or automatic acceptance.

For an explicit transition to the current comparison contract, compare with `--project-baseline <SHA256-of-original-run.json>`. This requires a qualified original baseline and its exact hash; it replaces the narrower former `--restrip-baseline` option. The current stripper processes both the baseline's retained canonical off/on trees and the candidate's live DOMs. The new output retains each driver's `baseline-projection/` trees and a projection record with original report hashes, strip identity and every changed tree hash. The original baseline, raw outputs, diagnostics and failed comparisons are never rewritten. `run.json` pins the source run, historical implementation, interpreted runtime and projection records under `baseline_projection`; the candidate input manifest identifies the current implementation. The conversion helper must remain identical. Without this explicit option, changed audit implementations or comparison contracts still fail.

`CaptureRuntime.pm` separates runtime meaning from physical spelling. It normalizes path separators and dot segments in `PERL_ROOT`. A checkout-owned kpsewhich launcher is identified by its resolved repository Perl helper only when its entire source matches the simple launcher contract. Launcher source must match the snapshot hash: it comes from the matching current file, retained dirty bytes, or the recorded Git commit. Wrapper and target paths/hashes remain evidence. Extra commands, added arguments, another target, or unverifiable historical source cannot be called a relocation. Other runtime settings, including Perl options, library paths and cache-only mode, remain comparison inputs. Engine-owned helper implementation hashes remain recorded inputs, like engine source changes; their behavioral compatibility is tested by the unchanged raw-output and diagnostic gates, not inferred from the role name.

Re-stripping uses the canonical trees, whose text nodes were preserved from the original DOM, in a fresh Perl process with whitespace-preserving parser settings. This isolation also prevents XML::LibXML 2.0210's [parser-state defect](https://github.com/cpan-authors/XML-LibXML/issues/88): a previous `no_blanks` parser can override the next parser's explicit whitespace setting. It must not re-parse the pretty raw XML and guess which whitespace was formatting. This operation can remove capture metadata left by an earlier strip; it cannot recover content an earlier strip discarded. It does not record a replacement baseline, accept candidate residuals, allowlist revisions, or weaken raw-byte, diagnostic, coverage and ordinary-suite gates. Review the projection changes and retain the original strict verdict alongside the new result.

Read `run.json` and the per-driver reports before explaining a change or deliberately establishing a replacement baseline. Retain the previous baseline and its report. Report the exact selected/omitted surface, the actual harness result, residuals and input identities; a fixture audit does not qualify a manuscript corpus.

### Manuscript corpus comparison

New acquisitions use worker-owned `jobs/<attempt>/run.json` and coordinator-owned `batch.json`, under a frozen `experiment.json`. See [record ownership and migration](specification/gauntlet-records.md). The corpus auditor defaults to these records and selects condition `conversion`; `--baseline-condition` and `--candidate-condition` select named conditions explicitly. `--project-baseline` pins the baseline `batch.json` in this format. Acquisition completion alone has `not-requested` qualification.

`lgauntlet -CaptureParity` runs frozen off/on conditions and their comparison
inside each paper job. The worker and corpus CLI share `CaptureCompare.pm`;
the worker calls `compare-paper.pl` with direct, hash-verified condition evidence
in a fresh Perl process. No completed batch summary is needed to compare a paper.
Both paths retain the same whitespace, source-byte, diagnostic and tree gates.
The paired worker reports conversion/inspection, comparison and input-validation
costs separately; its input freeze has a separate preparation duration.

`scripts/tests/gauntlet-measure-regressions.ps1` checks inclusive phase timing
extraction from nested progress logs, untimed xcolor/listings load notices,
CRLF, repeated phases, truncated digestion and absent math parsing. It runs
without conversions; only completed timed groups contribute phase values.

With a prepared checkout supplied as `LATEXAI_ROOT`, CDXSCI's public
`tests/batch.ps1 -Framework Pester -PesterPath tests/inventory-records/paired.Tests.ps1`
exercises the paired launcher, nonempty nested/bracket source checks, failed
native condition, changed frozen source/generated module, altered/malformed XML,
model pins and a true comparison difference. `latexai.Tests.ps1` retains the
single-condition consumer checks; `records.Tests.ps1` and the inventory-adapter
driver cover missing/nonterminal records, executor disagreement and qualification
aggregation. Full Core/Common tests remain mandatory for engine changes.

The paired controls also exercise analysis-only execution, selective retry from
a failed batch, rejection without fallback conversion, changed options/raw bytes
and corpus-reader consumption of reused conditions. Replays must publish new
attempt identities, preserve origin hashes and report zero current native time
for reused conversions. The record reader's explicit `-MetadataOnly` option
defers artifact-byte checks to the stage consumer; ordinary reads and aggregation
continue to verify every declared artifact.

`tests/inventory-records/contrasts.Tests.ps1` exercises explicit engine and style
contrasts plus receipt import through the same public runner. Its engine fixture
changes pinned input bytes without changing semantics; negative controls retain
strict output/option gates. Legacy controls cover preserved raw hashes, zero
current conversion time, unknown cleanup and changed artifact rejection. Engine
performance claims still require a separate unprofiled population experiment.
`contrast-revisions.Tests.ps1` checks that engine commit metadata comes from an
actual checkout root and that nested snapshots are labeled `unversioned`.

Historical inputs require `--baseline-format legacy` and/or `--candidate-format legacy` for the corresponding side. A legacy side retains its batch-level `run.json` and worker receipts; the baseline pin then names that original `run.json`. `CaptureInventory.pm` verifies new record/artifact identities and provides the existing comparator with condition evidence. Both formats and condition selections are recorded in the result. No legacy files are rewritten, and the completed-batch timeout inference below applies only to explicitly selected legacy inputs.

For retained formatted XML, explicitly pass `--whitespace-model FILE --whitespace-model-sha256 SHA256` alongside `--project-baseline RUN_SHA256`. `CaptureWhitespace.pm` loads that pinned compiled model through the engine's `Common::Model` and reuses its `#PCDATA` decision. On cloned DOMs it removes only XML whitespace text in declared element-only LaTeXML regions whose child elements the model admits (excluding the root capture ledger that stripping removes). Mixed-content/literal, unknown and foreign subtrees remain opaque; non-whitespace text, CDATA or unmodeled children make a region opaque too. Inherited `xml:space="preserve"` prevents removal, and explicit `default` resumes the model rule. Attributes, comments, processing instructions and non-XML spaces are preserved. Ledger adjacency is never a criterion. This is comparison normalization; it changes no source, raw conversion, serializer or default strip behavior.

Corpus reports use `latexai/corpus-comparison/3`: `normalization` names `latexai/model-whitespace/1`, pins the model and loaded implementation, and records operation order. Per-side records count removed nodes/bytes by element. Original stripped and runtime-projected XML/hashes remain distinct from `*.normalized.xml`, `comparison_sha256` and `comparison_document_equal`, which determine the tree gate. Exact and unnormalized projected differences stay visible even when normalized parity qualifies. Without the option, the comparison hash is the unnormalized projected hash. No diagnostic, Math, source-byte or coverage gate is relaxed.

`t/98_capture_whitespace.t` checks symmetry, idempotence, namespace handling, model pins and preservation boundaries. `t/99_capture_audit.t` exercises the public comparator with significant-text, comment, source/callsite and pin failures under the normalization contract, while retaining its original strict-strip and no-op-transition controls. A comparator-only change can reanalyse pinned artifacts in a new directory; it does not require new conversions or qualify historical engine defects.

`tools/dev/capture-corpus-audit.pl` compares two retained inventory runs with the same paper selection. `--mode replay` (default) is two capture-on runs: it checks successful run/receipt coverage, article identities, diagnostic counts/details, every Math carrier and capture attribute, actual source/callsite bytes, and the complete stripped documents. `--mode parity` is capture-off baseline vs capture-on candidate: it checks the same coverage, identities, diagnostics and stripped/projected documents, plus Math `tex` by `xml:id`. It does not compare capture records, ledgers or source hashes on the off side, and it ignores `--capture` when comparing projected invocation identity. Only timing and output-size counters are excluded; undefined-macro and missing-file lists are unordered multisets. Replay still requires `--capture` on both sides; a missing ledger is `missing-ledger` rather than a crash.

```powershell
& $auditPerl -I lib tools/dev/capture-corpus-audit.pl `
  --baseline <retained-inventory-run> --candidate <fresh-inventory-run> `
  --output <new-comparison-directory> --project-baseline <retained-batch.json-SHA256>
& $auditPerl -I lib tools/dev/capture-corpus-audit.pl `
  --mode parity --baseline <capture-off-run> --candidate <capture-on-run> `
  --output <new-comparison-directory> --project-baseline <off-batch.json-SHA256>
```

Without projection, any stripped-document difference fails. An explicit hash-pinned projection verifies the top-level search-path processing instruction against each receipt's actual CLI arguments. It interprets the repository's former preload directory and current `scripts/preloads` as the same logical role, and resolves the recorded absolute/relative entrypoint and job-local output addresses. Search order, other paths, preloads and compiler options must still agree. Missing, duplicate, malformed or inconsistent instructions fail. Other PIs, comments, whitespace and manuscript nodes are untouched. This is an audit interpretation of historical execution metadata; runtime paths and the engine serializer are unchanged.

The comparison retains original and projected stripped XML, both instruction values, canonical invocation identities, source/input hashes and comparator identity. `exact_document_equal` and `exact_document_differences` continue to report literal differences even when the projected comparison qualifies. This is an explicit contract transition, not a replacement conversion baseline or blanket removal of processing instructions. Preserve the earlier failed verdict alongside the new report.

Older receipts can lack the later `timedOut` counter. An explicit projection may derive zero only from a retained aggregate that reports zero timeouts and success for every selected job. The report names and hashes that evidence in `derived_counts`, while retaining the original receipt counters. Missing aggregate evidence is not treated as zero. The declared destination must also identify the XML being compared; another file in the same job is not sufficient.
