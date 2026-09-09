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

## 7. Capture-off byte comparisons

`lgold --check` digests and lints; it does not compare the result with the existing golden. For a capture change that promises unchanged capture-off output, `tools/dev/CaptureOffAudit.pm` records or compares the raw XML returned by each standard fixture conversion, before test normalization, using that driver's actual options. Keep the same source paths and options between runs:

```powershell
$env:LATEXAI_CAPTURE_OFF_BASELINE = Join-Path (Get-LaTeXAIRoot) 'temp/t/capture-off-baseline'
$auditExec = '"' + "$env:PERL_ROOT/perl/bin/perl.exe" + '" -I lib -I tools/dev -MCaptureOffAudit'
ltst --exec $auditExec t                    # record before editing
$env:LATEXAI_CAPTURE_OFF_COMPARE = '1'
ltst --exec $auditExec t                    # compare after editing
```

Use a new baseline directory for each investigation and leave `LATEXAI_CAPTURE_OFF_COMPARE` unset while recording. The audit fails on a byte difference or an omitted baseline conversion and reports new fixtures outside the baseline. Capture-on conversions and bespoke drivers that do not call `convert_texfile_as_test` need their own assertions, including the capture-off hash check in `t/45_capture.t`. Do not load this helper through `PERL5OPT`: that would also instrument child utilities instead of just the test drivers.

A second, opt-in pass compares the capture-on `ltx` tree against the capture-off serialization of the same fixture. Set `LATEXAI_CAPTURE_ON_AUDIT=1`. After each capture-off conversion the helper converts the same source again with `capture => 1` and otherwise identical Core options, strips the ledger, every `capture:*` attribute, and the capture namespace (the same strip as `t/45_capture.t`, in `tools/dev/CaptureStrip.pm`), and compares that string plus the `ltx:ERROR` count. A difference fails and is recorded per driver under the baseline directory as `capture-on-audit.json`. This pass is independent of recording or comparing the capture-off bytes:

```powershell
$env:LATEXAI_CAPTURE_OFF_BASELINE = Join-Path (Get-LaTeXAIRoot) 'temp/t/capture-off-baseline'
$env:LATEXAI_CAPTURE_ON_AUDIT = '1'
$auditExec = '"' + "$env:PERL_ROOT/perl/bin/perl.exe" + '" -I lib -I tools/dev -MCaptureOffAudit'
ltst --exec $auditExec t
```
