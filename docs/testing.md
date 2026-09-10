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
ltst t/85_nicematrix.t        # one package suite
ltst t/40_math.t t/70_parse.t # the drivers covering a touched layer
ltst t                        # everything; required for changes under Core/ or Common/
```

Report failures with the harness output, not a summary.

## 7. Capture regression audit

`lgold --check` digests and lints; it does not compare existing goldens. The audit has two independent checks: exact raw capture-off bytes and capture-on/off tree and diagnostic differences. Run through the repository PowerShell profile, from the repository root:

```powershell
lgen
$auditPerl = "$env:PERL_ROOT/perl/bin/perl.exe"
& $auditPerl -I lib tools/dev/capture-audit.pl record --output temp/t/audit-baseline
& $auditPerl -I lib tools/dev/capture-audit.pl compare --baseline temp/t/audit-baseline --output temp/t/audit-replay
```

No driver arguments selects every `t/*.t` driver. Append named drivers for a bounded audit; comparison requires the same selection. `--jobs N` sets independent driver workers (default one); keep this setting identical when comparing. Record and replay run separately, with fixed inputs. Every output directory must be new. Record is an explicit baseline operation; compare never modifies or renews its baseline, including on failure. Do not inject the observer through `PERL5OPT` or use the superseded `LATEXAI_CAPTURE_OFF_*` / `LATEXAI_CAPTURE_ON_AUDIT` interface.

To retain the older raw-byte check while establishing a new paired baseline, add `--legacy-off <old-directory>` to record. This reads the original per-driver JSON/XML layout and fails on changed, added or omitted conversions; it never overwrites those files. Generic historical difference reasons cannot reconstruct missing historical capture-on trees. A newly recorded pair describes its own recorded input state, not a reconstruction of the historical run.

The audit observes `LaTeXML::Util::Test` conversions before golden normalization and retains their original raw bytes. It also runs fresh off/on controls in separate Perl processes with the driver's complete Core options, differing only in capture. This avoids confusing repeated-pool warnings in the prove process with capture effects. Original driver diagnostics and their differences from the fresh off control remain separate evidence. It records suite inventories, skip reasons, conversion failures, and drivers with zero observed conversions. Direct conversions outside `convert_texfile_as_test` are excluded from this count. In particular, `t/45_capture.t` owns fresh-process capture fixtures; the extpfeil, scalerel, nicematrix and tikz-cd drivers also contain direct checks outside the observer. Post-processing, daemon, unit and Markdown tests are not implicitly capture comparisons. `t/99_capture_audit.t` independently exercises the helper and gate in fresh processes.

Each driver report retains fixture identities, options, source/support hashes, raw and stripped XML (`driver-off`, fresh `off`, fresh `on`), helper requests/results/logs, engine status and error-node counts. `run.json` reconciles the complete selected driver set and the ordinary harness result. A record is qualified only if all selected drivers report, conversions are accounted for, the ordinary tests pass, and the input state stays fixed during the run. It can contain explicitly recorded residuals. The manifest records the checkout and dirty input identity (including restorable uncommitted content), generated revision, library/test/tool file hashes, runtime and relevant environment. Freeze these inputs during conversions; a unique output name alone is insufficient. Generated version metadata is distinct from Git identity.

The comparison dispositions are deliberately conservative:

- An unchanged known residual passes and remains in the report.
- A newly different fixture, changed residual, removed residual, changed fixture/options/support inputs, or coverage change fails for review.
- Raw capture-off changes fail independently, even when the capture-on and capture-off trees still agree.
- Process failure, invalid/missing helper output and conversion failure remain distinct from IR differences. Engine diagnostics and `ltx:ERROR` nodes are separate observations.
- Ordinary suite success cannot override audit failure. An audit implementation change requires a new explicitly recorded baseline; the comparator cannot silently reinterpret an old baseline.

`CaptureStrip.pm` removes capture attributes, unused capture namespace declarations and the ledger. It retains comments and every text node, including whitespace-only prose and verbatim content, and canonicalizes the DOM directly without re-parsing it. The audit compares live DOMs; file-based capture checks use compact LibXML serialization. The Core serializer currently ignores its format argument, so `Core::Document->toString(0)` does not produce that compact input. Both original serializations remain available for inspection; no engine repair is performed by the comparison.

Read `run.json` and the per-driver reports before explaining a change or deliberately establishing a replacement baseline. Retain the previous baseline and its report. Report the exact selected/omitted surface, the actual harness result, residuals and input identities; a fixture audit does not qualify a manuscript corpus.
