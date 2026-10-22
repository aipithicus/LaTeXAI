# Experimental LaTeXML projections

These six YAML files preserve provisional output-mapping ideas based on LaTeXML.
They have no runtime consumer and do not define PyTeXML's future XML schema.
Their `ltx:*` elements, attributes and suppression decisions remain design inputs.

Each file mirrors a binding-relative ID under
[resources/bindings](../../../bindings/README.md), for example `engine/verbatim`
or `packages/listings`. `identity.corresponds_to_binding` is that stable relative
ID, not a filesystem path to the raw manuscript. Each projection's local identity
matches its filename stem (`identity.name` for engine projections and
`identity.package` for package projections). The projection library supplies its
own namespace; no extra capture suffix is needed in the local name.

The existing schema records `identity` (name, binding reference, target format,
tier) and `projections` (environment/command mappings to XML elements, attributes,
and roles). Conformance tests load these through the strict YAML loader and check
filename identities and binding correspondence for every projection file. There
is no runtime projection dispatcher or final schema validation here.

This directory is separate from preparation's emitted source-provenance ledger
and from the lexical `source_capture` settings inside reading profiles/bindings.
Neither of those requires adopting LaTeXML's XML conventions.
