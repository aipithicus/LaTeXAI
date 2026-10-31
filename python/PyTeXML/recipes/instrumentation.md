# Reusable native probes and matched state observations

The validation layer now provides four connected instruments. They do not add
native TeX to the production content path or claim that Python can load arbitrary
LaTeX formats. The original fixed semantic witnesses remain regression checks.

| Instrument | Implemented contract |
| --- | --- |
| `validation.probe_runner` | Stage unchanged manuscript bytes in baseline/probed copies; identical initial auxiliaries, jobname and requested pass count; explicit executable and a shared finite execution deadline; retain each pass's logs, recorder opens, initial/final auxiliary bytes and hashes |
| `validation.primitive_census` | Stream command/operand reports by checkpoint-delimited phase; keep character/font reports and conditional outcomes separate; report registered primitive names without implying qualified behavior; keep lexical candidates separate |
| `validation.tex_trace` | Preserve raw lines, command reports, macro headers and argument records, box/mode lists and native branch paths; reject or explicitly report unknown, orphaned, wrapped and abbreviated list records |
| `validation.checkpoint_state` | Generate one observer for both engines; capture selected values when each checkpoint executes; compare only matching source/start-state bases, field selections, labels and occurrence numbers |

## Running a probe

Use the repository PowerShell MCP from `python/PyTeXML` and the project Python.
The output directory must be new. Supply an explicitly selected Web2C executable;
`latex` mode expects a LaTeX format, while `initex` uses `-ini -etex`.

```text
python -B -m src.validation.probe_runner <project> --entry main.tex --executable <pdflatex.exe> --plan tests/fixtures/engine/instrumentation/latex/plan.json --initial-state <pinned-format-contract> --passes 2 --output ../../temp/instrumentation/example
```

`--initial-aux <directory>` supplies an identical auxiliary starting inventory to
both arms; otherwise both start without auxiliary files. `--timeout` bounds the
combined native executions (default 120 seconds), not each individual pass.
`--expected-ok N` requires exactly N intentional show diagnostics and exit code 1;
other errors remain failures. `--no-trace` disables command profiling.
`--parse-trace` additionally materializes the full trace, including raw lines;
ordinary profiling and checkpoint reads stream the retained log.

The preload uses `RequirePackage` without editing the manuscript. The default
LaTeX schedule is `preamble`, `body`, `afterlastpage`, `afteraux`, `end`, supplied
by the example plan. Preamble begins after observer installation. Body begins at
`begindocument/end`; afterlastpage precedes auxiliary close/reread, so it is not
interchangeable with afteraux. A plan may provide a `hooks` mapping from selected
labels to LaTeX hook names. Other labels require explicit source call sites.

The run sets `max_print_line=10000`, `error_line=254`, and `half_error_line=238`.
These are finite bounds: a record reaching the print limit is marked incomplete,
not reconstructed by joining arbitrary following lines. Executable and observer
hashes, native banners, source hashes, search/print settings, commands, return
codes and execution times are recorded. Recorder INPUT/OUTPUT/PWD records retain
order and repeated opens. Dependency hashes describe **pass-end bytes**, not the
bytes at each individual open. Package-list text is separate metadata.

Each pass retains `receipt.json`, `files.json`, the native `.log`/`.fls`, console
output, and initial/final auxiliaries. The probed arm also writes
`checkpoints.json`, `profile.json`, and optionally `trace.json`. The manifest
compares auxiliary hashes and ordered inputs after excluding only the declared
observer files. `observed_equal` is scoped evidence for these observations, not
a universal non-interference proof. A run may be complete with an observed
difference; callers must inspect the separate non-interference result.

## Checkpoint selection and comparison

A plan supplies an ordered `checkpoints` schedule (labels may repeat) and a
nonempty `fields` list with unique identifiers. The fixture plans are runnable
examples. Supported selectors are count/dimen/skip/muskip/toks registers; catcode,
mathcode, lccode, uccode, sfcode and delcode entries; `meaning` of a named control
sequence; and the seven standard `fontdimen` entries of a known font selector.
Indices and names are validated before TeX is generated.

Counts, codes, dimensions and font dimensions compare as exact integers;
dimensions are scaled points. Meanings, token lists and glue compare as **printed
diagnostics**. A matching printed string does not establish catcode/token identity,
dependency closure or behavioral equivalence. An undefined meaning is observed
without creating that binding through `csname`.

For explicit-source INITEX work, the common source establishes braces, parameter
and superscript catcodes and `newlinechar=10`, inputs `pytexml-observe.tex`, then
calls `PyTeXMLCheckpoint{label}` at the desired cuts. See
`tests/fixtures/engine/instrumentation/initex/main.tex`. The generated observer
uses no scratch registers or additional observation groups. A checkpoint inside
an authored group therefore sees the state at that cut. The baseline uses a
named no-op at the same call sites. Source catcode/redefinition changes that make
the observer unusable produce incomplete evidence rather than a match.

Capture the first pass of a completed INITEX run in the bounded Python builder:

```text
python -B -m src.validation.checkpoint_state capture <run-directory> --output <python-checkpoints.json>
python -B -m src.validation.checkpoint_state compare <run-directory>/probed/pass-1/checkpoints.json <python-checkpoints.json> --output <comparison.json>
```

The CLI loads staged `.tex/.sty/.cls/.ltx/.def/.aux/.bbl` sources and `.tfm`
metrics, checking their hashes against the pass basis. The Python API
`python_observations` accepts an explicit source/metric inventory for other input
names. Python boundaries remain visible and make the observation incomplete.
Capture does not restore a native `.fmt` or complete a native LaTeX bootstrap.

The common basis includes authored inputs, actual pass-start staged files and
auxiliary hashes, entry, pass number and an explicit caller-declared initial-state
contract. The contract must name the same intended format/start state; it is not
automatically proven by giving two runs the same string. Native executable and
Python source-tree identities are separate producer evidence. Missing/duplicate
fields, missing cuts, unexpected occurrences, malformed receipts or producer
failure return `incomplete` or `not_comparable`. Two empty observations never
match. Complete comparable snapshots return `matched` or a structural `mismatch`.
This does not replace the existing macro-only format-start meaning assay.

## Profiling and parser limits

```text
python -B -m src.validation.primitive_census <native.log> --manifest <run-directory>/manifest.json --output <profile.json>
```

Profiles count observed command reports under their native printed names;
parameterized reports retain both the base name and operand text. Observer
intervals are excluded, while boundary/setup overhead is explicitly disclosed.
The profiler retains an issue count and at most 30 samples; the original log
remains the full evidence. Lexical candidates come from recorded source files
and include comments and unexecuted definitions. They are never added to executed
counts. Catalog presence is not a semantic coverage percentage or a priority
ranking. Loaded format construction needs a separate INITEX run.

TeX's token scanners can expand primitives without ordinary command reports;
the existing `the`-inside-`message` witness remains a known blind spot. Trace
settings and observer code can also affect the observed stream. These tools do
not claim a complete primitive census.

List paths preserve `.`, `^`, `_`, mathchoice `D/T/S/s`, fraction `\\` and `/`,
and discretionary `|` branches. Empty subsidiary fields and void boxes are
explicit. Depth `[]`, breadth `etc.`, unknown lines, orphan paths, missing dump
terminators and possible wrapping are incomplete. Strict parsing raises;
`strict=False` retains issues and raw records for inspection. Macro arguments
are associated with the preceding printed header, not a reconstructed call
stack. Macro replacement heads, node records and source aliases do not constitute
a causal macro-to-node graph.

## Qualification

```text
python -B -m src.validation.instrumentation_native --bin <native-bin-directory> --output ../../temp/instrumentation/qualification
python -B -m unittest discover -s tests -p 'test_instrumentation.py'
python -B -m unittest discover -s tests -p 'test_*.py'
```

The native witness uses pdfTeX 3.141592653-2.6-1.40.29 (TeX Live 2026), executable
SHA-256 `4b582d0be712b74ae5090aba2d7338f185082f6446cbee7b26115e8ab6e21184`.
Fifteen fields match at three cuts: local and global registers, exact dimensions,
six code tables, font parameters, macro/alias meanings, token lists and glue.
Two LaTeX passes match auxiliary hashes and ordered recorder inputs under the
declared observer exclusion. Native list fixtures exercise all four mathchoice
branches, fraction numerator/denominator, scripts and discretionary branches.
The prior semantic driver/lifecycle witness still matches; recognizing brace
character reports increases its parsed command count from 1,232 to 1,234.

The full regression run executed **1,333 tests: 1,330 passed and three optional
native tests skipped**, in 429.142 seconds. Complete output is retained in
`temp/instrumentation/full-suite-01/`. Subsequent void-box, missing-list-terminator,
bounded-profile and receipt refinements passed the final **14 instrumentation
tests and two existing trace tests**, with output in
`temp/instrumentation/focused-final/`. The final native qualification is
`temp/instrumentation/qualification-final/receipt.json`; the original semantic
probe's regression receipt is under `temp/instrumentation/semantic-regression/`.
The capture/compare CLI also completed with a matched result.

The [causal recording follow-up](causal-recording.md) qualifies one vocabulary
round trip and selected causal relationships with Merkle comparison. Broad
format-state, package-startup, page-layout and complete dependency qualification
remain open.

Printer/scanner mechanisms are grounded in the
[TeX source](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web)
(`show_node_list`, `print_subsidiary_data`, `scan_toks`) and
[e-TeX changes](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/etexdir/etex.ch).
