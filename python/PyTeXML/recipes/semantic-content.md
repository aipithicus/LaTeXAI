# Semantic content and measurement checkpoint

This increment implements bounded parts of the four content-oriented priorities
inside `ContentBuilder`, using the existing dispatcher, mutable meanings,
scanners, rollback and input ownership. Native TeX remains a qualification
instrument; the Python content path does not invoke it or serialize PDF.

| Priority | Implemented | Boundary retained |
| --- | --- | --- |
| Semantic drivers | Opt-in, hash-pinned `hpdftex.def` v7.01s plain link/anchor interfaces; link identities and pairing; active-anchor state and link groups; raw expanded `pdfinfo` dictionaries | Full hyperref startup, outlines, graphics, assets, colour backends, PDF string encoding and arbitrary PDF operators |
| Local measurement | Integer-scaled TFM glyph extents, ordinary replacement ligatures and kern programs; interword glue and space factor; italic correction; horizontal/vertical packing dimensions, baselines, shifts and `vtop` | Boundary-character and retaining/stopping ligature programs, math conversion, paragraph breaking and general alignment widths |
| Content lifecycle | Immediate/deferred writes; virtual open/close streams; writes on each explicit shipout; closed auxiliary-file reinput; explicitly classified insertion bodies and stored float boxes | Automatic page output, page-selected marks, float/footnote placement and full LaTeX reference convergence |
| Layout only where needed | Known dimension fields remain usable by `ifdim`; unknown fields carry source-linked requirements and stop dependent branches; paragraph width/glue parameters are retained | No line/page algorithm is claimed from a box witness; source content survives unresolved geometry |

## Driver contract

The inventory may select:

```json
{
  "semantic_drivers": {"hpdftex.def": "hyperref-hpdftex-7.01s"},
  "insertion_roles": {"254": "footnote"},
  "box_roles": {"3": "float"}
}
```

These are optional additions to the existing inventory, not a complete inventory
example. Role numbers are **caller declarations for a known format/package**;
neither 254 nor 3 is universally a footnote or float. Unclassified insertions
stay unclassified. A stored float record preserves its body and register, with
`placement: unresolved`; it is not evidence that the box was emitted.

The driver is installed only when an executed physical input selects the exact
inventory entry. The supplied source must match SHA-256
`db41df0ca7a5001e76ef891d741ea634b9dd175c6a4f6f0ee7cd483755d3ff51`.
The unmodified LPPL source is retained in `tests/fixtures/engine/drivers/` with
its upstream copyright and licence header. Source mismatch, reload or installation
inside a group stops. No filename-based interception occurs without selection.

Implemented names are `hyper@anchorstart`, `hyper@anchorend`, `hyper@linkstart`,
`hyper@linkend`, `hyper@linkurl`, `hyper@link`, and `pdfinfo`. Their installed
meanings remain subject to `let`, local redefinition and group restoration.
The adapter emits `driver_event` nodes among the source content and records the
selected driver in the receipt tree. Links use paired identifiers; anchors keep
their names. Link scopes, including the URL outer group and colour group, are
observable even without a colour renderer. `ifHy@activeanchor` tracks anchor
entry/exit. Known border-colour meanings are retained; helper strings and absent
border-colour state which are not reproduced become uncertain, so later queries
cannot use stale values.

Colour-link, OCG, PDF/A and image-map options must be false or absent. Nonidentity
destination filters and nonempty next-action/xspace hooks stop. The supported witness uses plain destination/URL
strings; this is not a PDF-encoding equivalence claim. Metadata remains an
expanded raw PDF dictionary with an explicit interpretation label. Driver
bypasses such as `pdfstartlink` remain unsupported instead of disappearing.
The package above this seam is not rewritten, but loading the complete LaTeX and
hyperref sources in Python remains a separate bootstrap gate.

## Measurement and layout requirements

TFM bytes come only from the explicit metric inventory. Font identities retain
their metric source and size across format save/restore; parsed glyph data is a
derived cache. TeX's integer scaling is used rather than floating-point point
values. Logical character nodes and source origins remain intact; box attributes
carry separate glyph/kern runs and character-cluster indices.

Character runs survive macro expansion and `char`, but end at executed commands,
groups and unboxing boundaries. Unboxing preserves the shaped runs within the
box and cannot create a ligature between two copied boxes. Space nodes capture
their glue at execution time. `spacefactor` and `prevdepth` belong to the current
list. Baseline glue is inserted between vertical boxes, and rules reset the
previous-depth sentinel.

Unknown width, height and depth serialize as `null`, with
`measurement_requirements` such as `math_layout`, `paragraph_breaking` or an
unsupported font-program operation. A `to` width can remain known while height
and depth are unknown. The corresponding `ifdim` can use the known width; a
query of an unknown field stops before selecting a branch. A paragraph's `hsize`,
left/right skip and final-line glue are retained for a future layout consumer.
This is partial information with a stated dependency, not guessed geometry.

## Lifecycle and auxiliary input

Raw write tokens are retained until their owning explicit shipout. Each copied
box executes its deferred writes again under the then-current language state.
Discarded boxes and leader patterns do not execute deferred writes. Immediate
writes execute when issued, including inside a later discarded box. Observations
record stream, destination, shipment identity, text and source anchors.

`openout`/`closeout` support immediate or deferred execution over 16 **virtual**
streams. Reopening truncates the virtual file; writes to closed streams are
terminal/log observations. `virtual_outputs` contains text and contributing write
origins. After closing a virtual file, ordinary physical `input` can retokenize
it through the same engine with the current category codes. Reads of an open
output stop at `output_input_timing`, since buffering has not been qualified.
Nothing is written to manuscript files, and shell writes remain a boundary.

This unlocks the auxiliary-data mechanism used by references. The witness writes
a `newlabel` whose value changes before shipout, closes the stream, reads the
generated file and observes the new value. It does not install replacement
LaTeX `label`/`ref` commands or invent page numbers. Page-dependent labels still
require the relevant output routine and page state. Virtual text can also be
supplied explicitly in a subsequent build; automatic reruns/convergence are not
part of this checkpoint.

Content nodes, driver stacks, virtual streams, observations and role records
participate in the existing transaction checkpoint. A failed macro rolls them
back together with language state. Referenced lifecycle bodies count against the
content budget, including copied stored boxes. Existing frozen/physical-input
continuation boundaries remain in force; for example an integer scanner that
would have to expand a physical input at its terminator can still stop.

## Qualification tools and evidence

Run through the repository's PowerShell MCP, from `python/PyTeXML`, with the
project Python and an explicitly selected native oracle:

```text
python -B -m src.engine.content_builder tests/fixtures/engine/semantic-content.inventory.json --output ../../temp/semantic-content/example/content.json
python -B -m src.validation.local_measurement --pdftex <pdftex.exe> --output ../../temp/semantic-content/measurement
python -B -m src.validation.semantic_native --bin <native-bin-directory> --output ../../temp/semantic-content/semantic
python -B -m unittest discover -s tests -p 'test_*.py'
```

The two native receipts are pinned in `local-measurement.expected.json` and
`semantic-content.expected.json`. They include executable, source, metric,
driver and log hashes. The oracle is pdfTeX 3.141592653-2.6-1.40.29, TeX Live 2026.
Sixteen local-box witnesses match all three dimensions in integer scaled points:
ligatures/kerns, macro and character insertion, group/command boundaries,
spacing, italic correction, copied unboxing, shifts, baselines, rules, `vtop`,
fixed vertical size and a scaled font.

The semantic probe preloads `probe.sty` using
`pdflatex '\RequirePackage{probe}\input{semantic-driver-native.tex}'`, with an
explicit job name/output directory. The source body is shared with Python; native
LaTeX/hyperref provide the native driver. It compares destination/URL nodes from
`showbox`, active-anchor and scope observations, deferred/immediate write timing,
virtual auxiliary bytes and reinput values. `showlists` captures math atoms and
scripts. Exactly two intentional `! OK.` diagnostics are required; unexpected
errors, missing observations or mismatches fail qualification. Native executables
are used only by these validation tools.

`validation.tex_trace` separates command reports, macro-call headers, conditional
outcomes and list trees, retaining log line numbers and math-field paths. Its
structural diff reports changed observation paths. Truncated dumps are rejected.
The probe sets a large explicit print-line limit to avoid wrapping its selected
node records; macro replacement heads are not advertised as complete expansions.
The successful trace has 1,232 command reports, 86 macro calls, one box dump and
four mode-list sections. These counts characterize this witness, not engine
coverage or a performance claim.

The proposed instrumentation was useful, with one important observed limit:
aliases of `count` and expandable `number` are reported under canonical meanings,
but `the` inside the fixture's `message` expands without its own command report.
Consequently the receipt explicitly says `complete_primitive_census: false`.
Macro calls and list nodes are separate observations; a measured/discarded/copied
box prevents a general one-call/one-node correspondence.

Mechanism references are [TeX82 source](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/tex.web)
(`read_font_info`, `main_loop`, `app_space`, `hpack`, `vpackage`,
`append_to_vlist`, `write_out`, `out_what`) and the
[e-TeX change file](https://github.com/TeX-Live/texlive-source/blob/trunk/texk/web2c/etexdir/etex.ch).
Native-valid measurements, semantic driver observations and unresolved layout
requirements remain distinct. No full-package, page-layout, rendering or general
TeX-document equivalence is claimed.

The broad regression run executed **1,321 tests: 1,318 passed and three optional
native tests skipped**, in 244.776 seconds. Its complete harness output is under
`temp/semantic-content/suite-final/`. The registry type check passed for 26 source
files. The runnable inventory above completed and wrote its content tree under
`temp/semantic-content/example/`. Acquired native receipts and full logs are under
`temp/semantic-content/measurement-final/` and
`temp/semantic-content/semantic-final/`. The final driver-hook guard is covered
by the focused semantic-content tests following that broad run.
