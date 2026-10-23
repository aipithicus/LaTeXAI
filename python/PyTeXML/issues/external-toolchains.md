# PyTeXML native processing and dependencies

PyTeXML is developing its own discovery, reader dispatch, binding resolution and
preparation pipeline. It is temporarily hosted in LaTeXAI while that design and
its bindings mature. Self-sufficient processing with a small dependency set is
the architectural direction, including the work still to be implemented.

## Current dependency boundary

[requirements.txt](../requirements.txt) declares three Python packages:

- PyYAML loads the declarative profiles, bindings and policies.
- Pillow supplies raster image inspection, including dimensions.
- PyMuPDF supplies PDF-page export to SVG.

These are library dependencies, including native implementations where supplied
by those packages. The preparation path does not invoke `pdflatex`, `latexmk`,
`bibtex`, `biber`, Tectonic or the Perl LaTeXML engine. Compiler probes and
recorder-file discovery have been removed from the discovery/inventory path, now
organized as [discovery.py](../src/prepare/discovery.py) and
[inventory.py](../src/prepare/inventory.py).
`engine` is descriptive metadata; `execute_probe=True` is explicitly rejected.

## Implemented foundations

- Production discovery and input assembly share a cached, ordered source traversal.
  Each input occurrence runs through the N/M/S reader and structural dispatcher.
  Comments, literals, definitions and bounded skipped branches have established
  contexts. Ordinary unexpanded expressions and missing package bindings retain
  located requirements while later source-visible inputs continue to assemble.
  Actual reading boundaries constrain emission but do not veto publication.
- A cached whole-project survey records candidate work independently of active
  traversal, including unvisited files and source beyond reading boundaries.
  Observations made under an independent profile are not executed dependencies.
- Package activation uses declarative binding knowledge. Local styles and their
  active inputs are scanned from source. No missing binding causes a native
  package-source or compiler fallback.
- [bibliography.py](../src/prepare/bibliography.py) and [bibtex.py](../src/bibtex.py)
  prepare supported classic BBLs and generate a canonical extraction bibliography
  from supported BibTeX data without running an external bibliography processor.
- [assets.py](../src/assets.py) exports PDF pages to SVG and embeds raster
  data in SVG wrappers. Raster wrapping is not vectorization. Unsupported asset
  conversion remains an explicit error; the package does not copy all original
  assets as a fallback.

## Continuing the native implementation

The next work extends reading coverage: author macro reading effects, dynamic
assignments, deferred hooks, math/alignment contexts and additional package/literal
handlers. Integration is now live; this list describes unsupported behavior,
not a replacement of the integrated workflow by the old prototype.

Package knowledge belongs in bindings; author definitions contribute runtime
knowledge. Unsupported reading effects must produce explicit unresolved results
with preserved source, rather than a claim of infallible discovery or a silent
fallback to an external compiler. Ordinary macro expansion and XML interpretation
remain later stages.

This work continues through PyTeXML's own parsing components and bindings. The
[preparation contract](DESIGN.md) and
[span-engine design](../../../../aipithicus-issues/LaTeXAI/briefs/source-span-engine.md)
describe the stages and their acceptance criteria.
