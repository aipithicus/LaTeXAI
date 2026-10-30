# Pinned native meaning assay

The offline assay is implemented in `src.validation.meaning_assay`. It acquires
knowledge before Q4's runtime work: a name inventory, native displays, qualified
macro reconstructions, a static reference graph, individually recorded
exceptions, generated fixtures, and CPU/memory receipts. It does not install
meanings into production or implement intrinsic dispatch.

## Reproduce

Run through the repository PowerShell MCP from `python/PyTeXML`, using the
project interpreter and the existing pinned oracle. Outputs must be new
directories; existing receipts are never reused. These paths describe retained
local evidence, not a dependency on a new TeX installation.

```powershell
& ../.venv/Scripts/python.exe -B -m src.validation.meaning_assay `
  --oracle ../../temp/texlive-oracle `
  --inventory ../../temp/oracle-root-a/20261029/oracle-files.json `
  --output temp/meaning-assays/<new-run-id> `
  --workload-note '<other work and instrumentation context>' --timeout 180

& ../.venv/Scripts/python.exe -B -m src.validation.meaning_assay.fixtures freeze `
  --assay temp/meaning-assays/<new-run-id> `
  --destination tests/fixtures/engine/native-meanings/<new-basis-id>

& ../.venv/Scripts/python.exe -B -m unittest discover -s tests -p '*meaning*.py' -v
```

The ordinary test run needs no native engine. The frozen fixture set is described
in [its provenance note](../tests/fixtures/engine/native-meanings/README.md).
Regeneration requires the original oracle inventory and files; source, binary,
format and recorder-observed input hashes must match it. The receipt also hashes
the Python/YAML implementation, Lua/TeX probes and generated artifacts. Recorder
inputs are not a claim to have inventoried OS dependencies or every Lua file I/O.

## Acquisition and qualification

1. Start the pinned LuaLaTeX format without loading a class. `tex.hashtokens()`
   supplies names, including generated names and undefined hash entries.
   `token.create` exposes the command kind. A single queued set of native
   `\meaning` queries supplies complete displays, including flags and primitives.
   `token.get_meaning` alone omits those parts on this runtime. The empty-name
   entry with no Lua token is retained explicitly.
2. Supplement the Lua names with vocabulary from the pinned `latex.ltx` and
   `expl3-code.tex`, then repeatedly probe pdfTeX and discover referenced names.
   Source vocabulary includes uses and comments; it is not a declaration census.
   This supplements engine-specific branches but does not prove a complete
   pdfTeX hash census. Names outside the byte-name transport stay explicit.
3. Construct macro candidates with PyTeXML's `DefinitionScanner` and
   `StoredDefinition`, retaining flags, parameters and typed replacement tokens.
   First try a regime with `_`, `:` and `@` letters; then ordinary LaTeX internal
   catcodes. Spaces are category 10 in both: this is a reconstruction convention,
   not a claim to reproduce all `ExplSyntaxOn` input handling. Control/non-ASCII
   source, malformed definitions and trailing input are rejected before probing.
4. Check the Python printed display, then reconstruct the same source in the
   pinned pdfTeX format under the recorded catcodes and require native `\ifx`.
   No candidate body is executed. Native errors isolate the candidate and the
   next candidate continues in a fresh process. Every attempt remains recorded.
   `exact` means the first regime passed; `recovered` means the alternate passed.
   Both have the same native equality qualification. This is a bounded source
   reconstruction method, not a generic token serializer.
5. Emit a semantic descriptor/hash and fixture for each accepted macro. Replay
   it through PyTeXML and compare typed meaning and display. Non-macro meanings
   remain inventory observations; register initial values and primitive behavior
   are not qualified by their printed names.

`meanings.jsonl` includes every candidate. `exceptions.jsonl` lists each exception
with its meaning and attempted regimes. `graph.json` records control-sequence
references with multiplicity and separate active-character references. Hubs count
distinct referring bodies, not execution frequency. Unparsed bodies and possible
computed-name users are listed. Parameter delimiters, dynamically constructed
names, primitive state and aliases used as data prevent treating this graph as
complete intrinsic eligibility dependencies. Naming layers are heuristics;
`public_format` includes public LaTeX2e, plain-TeX and primitive names, without
claiming source ownership from spelling alone.

## 2026-10-29 result

Qualified run ID: `20261029-final`. Native targets: LuaHBTeX 1.24.0 and pdfTeX
1.40.29, both with LaTeX2e 2026-06-01 and expl3 2026-09-09. The complete oracle
inventory SHA-256 is
`e477567821917a9b0116f55833dfff79333363a1187a2dd6a641242bb19805b4`.

| Census / outcome | Count |
| --- | ---: |
| Lua hash entries | 23,039 |
| Lua undefined entries / unavailable empty-name token | 1,549 / 1 |
| Supplemented candidate names | 23,160 |
| Names observed defined in target pdfTeX | 20,239 |
| pdfTeX-defined names absent from Lua hash | 40 |
| Macro meanings | 17,546 |
| Exact first-regime reconstructions | 15,481 |
| Recovered alternate-regime reconstructions | 71 |
| Unresolved macros | 1,994 |
| Names outside pdfTeX probe's byte-name domain | 352 |
| Non-macro / undefined inventory records | 5,262 |

The 40 target-only names include UTF-8 input helpers and five private string
case-conversion helpers. Lua membership alone therefore misses real target
definitions. Among names compared in both engines, 19,990 displays agree and
2,697 differ; differences include 1,239 undefined target names, 598 macros, 297
primitive/other entries, 282 registers, 265 character constants and 16 fonts.
These are display comparisons, not cross-engine semantic equality checks.

| Naming layer | Exact | Recovered | Exception | Non-macro / undefined |
| --- | ---: | ---: | ---: | ---: |
| Public format | 2,084 | 23 | 854 | 2,521 |
| Public l3 | 5,296 | 1 | 131 | 400 |
| Kernel `@` | 2,657 | 47 | 66 | 549 |
| Private l3 | 5,444 | 0 | 1,295 | 807 |
| `tex_*:D` names | 0 | 0 | 0 | 985 |

| Exception's furthest gate | Count |
| --- | ---: |
| Native `ifx` unequal | 771 |
| Non-ASCII/control input | 637 |
| Python display differs | 533 |
| Scanner rejected candidate | 42 |
| Trailing input | 7 |
| Native definition error | 4 |
| Name outside probe domain | 352 |

This is a substantial corpus of exceptions, not a few hand-fix outliers.
Token-aware extraction and source-backed reconstruction should address recurring
classes before considering individual repairs. Exactly reconstructed fixtures
cover 88.64% of observed target macros; this is not a measure of format behavior
implemented by PyTeXML.

The accepted bodies contain 301,919 replacement tokens plus 39,187 parameter
tokens. Body sizes range from 0 to 1,783 tokens, with median 7 and 95th percentile
80. The inventory's target meaning text totals 1,745,069 bytes. The graph has
51,702 control-sequence edges, four active-character edges and 2,270 bodies
flagged as possible computed-name users. Prominent static
helpers include `fi:` (1,096 referring bodies), `exp_after:w` (1,040) and
`exp_args:Nc` (823). Static fan-in suggests candidates to investigate; execution
profiles and dependency qualification decide whether an intrinsic pays off.

| Measurement | Observed value |
| --- | ---: |
| Assay wall time through export and fixture replay | 38.043 s |
| Python process CPU | 30.703 s |
| Native process CPU, summed over sequential probes | 5.328 s |
| Native process wall time, summed | 6.454 s |
| Retained PyTeXML representation allocations | 73,143,908 bytes (69.76 MiB) |
| Peak representation allocations | 73,147,606 bytes |
| Traced representation build wall / CPU | 16.215 / 15.578 s |
| Python process peak resident memory | 279,523,328 bytes (266.57 MiB) |
| Largest native process resident peak | 116,449,280 bytes (111.05 MiB) |

Representation allocations cover the new `SourceSpan`, `Token` and
`StoredDefinition` object graph for all 15,552 accepted macros, including its
container and newly created strings. Input records and imported modules predate
tracing. This measures today's object representation, not a future interned or
selectively installed table. Python resident peaks include parsing, tracing,
artifact generation and replay; native peaks exclude children. Peaks from
different processes must not be added as if simultaneous. Missing platform
counters remain unavailable rather than zero.

The user reported two other heavy Bayesian/Monte Carlo sessions. Every receipt
records this contention, and the representation pass uses `tracemalloc`.
These are cost observations, not a throughput baseline or a regression claim.
Runtime table installation, package attribution and intrinsic speedups remain
unmeasured.

The earlier discovery and export failures remain local evidence. Only the
completed `20261029-final` receipt qualifies this snapshot. Its generated corpus
is consumed by the normal test tree, without requiring native TeX at test time.
The focused run passes all 56 tests, including every generated entry, ordinary
meaning assignments/comparison, malformed candidates and receipt integrity.

The four native definition exceptions are `token_if_parameter:NF`,
`token_if_parameter:NT`, `token_if_parameter:NTF` and `token_if_parameter_p:N`.
Their retained native logs report the aliased parameter token while scanning
the reconstruction; for the `NTF` case the harness output is:

```text
! Illegal parameter number in definition of \AssayCandidate.
<to be read again>
                   \__prg_TF_true:w
l.7 ...not:N #1\c_parameter_token \__prg_TF_true:w
                                                   \fi: \use_ii:nn }
!  ==> Fatal error occurred, no output PDF file produced!
```

These candidates remain exceptions. The complete logs are retained in the
run's `validate-l3-32-0` through `validate-l3-32-3` directories; the harness
isolates each error and resumes subsequent candidates. This is a reconstruction
limitation, not evidence that the upstream functions fail when executed.

## Remaining implementation decisions

Use this inventory and its exceptions to choose Q4's first coherent family and
its helper/state closure. A generic token-aware extraction path, stronger
target-only census coverage, precise per-entry source locations, non-macro
initialization, runtime table installation, interned identity, dependency
invalidation and intrinsic behavior still require implementation and witnesses.
The assay moves acquisition evidence ahead of those decisions; it does not
require every exception to be resolved before a bounded family can be qualified.
