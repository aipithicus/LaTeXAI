# Experimental configurations

These files preserve design work without making it part of default resource
loading. No production code recursively discovers this directory.

- [policies/lossless.yaml](policies/lossless.yaml) explores archival preservation.
- [policies/prose_extraction.yaml](policies/prose_extraction.yaml) explores a prose
  projection. Neither policy is integrated into a transformation pipeline.
- [projections/latexml/](projections/latexml/README.md) contains provisional output
  mappings derived from LaTeXML conventions. They do not prescribe PyTeXML's future
  XML schema and have no runtime consumer.

To inspect an experimental policy, pass its explicit path to `load_policy(path)`.
It receives the same strict field/action validation as the preparation policy;
validation does not demonstrate that its requested rewrites are implemented or
that a "lossless" run would preserve bytes.
