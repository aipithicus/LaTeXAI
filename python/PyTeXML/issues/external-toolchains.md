# PyTeXML native processing and dependencies

PyTeXML is developing its own discovery, reader dispatch, binding resolution and
preparation pipeline. It is temporarily hosted in LaTeXAI while that design and
its bindings mature. Self-sufficient processing with a small dependency set is
the architectural direction, including the work still to be implemented.

## Current dependency boundary

[requirements.txt](../requirements.txt) declares three Python packages:

- PyYAML loads the declarative profiles, bindings and policies.
- Pillow supplies raster image inspection, including dimensions.
- PyMuPDF supplies PDF inspection and PDF-page export to SVG.

These are library dependencies, including native implementations where supplied
by those packages. The preparation path does not invoke `pdflatex`, `latexmk`,
`bibtex`, `biber`, Tectonic or the Perl LaTeXML engine. Compiler probes and
recorder-file discovery have been removed from [preflight.py](../src/prepare/preflight.py).
The remaining `engine` and `execute_probe` arguments do not enable such a probe.

## Implemented foundations

- Discovery currently uses PyTeXML's static source traversal. Its coverage is
  bounded; removing the compiler path does not by itself establish complete
  dependency closure.
- [tex_reader.py](../src/reading/tex_reader.py) implements incremental N/M/S token reading
  with supplied catcodes, physical-line behavior and source spans.
  [binding_resolver.py](../src/bindings/resolver.py) resolves declarative reading
  profiles and supported effects. These are foundations for native dispatch;
  the current discovery and normalization paths do not yet consume them.
- [bibliography.py](../src/prepare/bibliography.py) and [bibtex.py](../src/bibtex.py)
  prepare supported classic BBLs and generate a canonical extraction bibliography
  from supported BibTeX data without running an external bibliography processor.
- [converter.py](../src/converter.py) exports PDF pages to SVG and embeds raster
  data in SVG wrappers. Raster wrapping is not vectorization. Unsupported asset
  conversion remains an explicit error; the package does not copy all original
  assets as a fallback.

## Continuing the native implementation

The next integration work connects source traversal to the reader, scoped state,
YAML-selected structural and literal handlers, and dependency requests. That is
how discovery will distinguish active inputs from source inside comments,
literals, stored definitions and skipped branches under the supported reading
context. A catcode-aware token reader alone does not establish all those contexts.

Package knowledge belongs in bindings; author definitions contribute runtime
knowledge. Unsupported reading effects must produce explicit unresolved results
with preserved source, rather than a claim of infallible discovery or a silent
fallback to an external compiler. Ordinary macro expansion and XML interpretation
remain later stages.

This work continues through PyTeXML's own parsing components and bindings. The
[preparation contract](DESIGN.md) and
[span-engine design](../../../../aipithicus-issues/LaTeXAI/briefs/source-span-engine.md)
describe the stages and their acceptance criteria.
