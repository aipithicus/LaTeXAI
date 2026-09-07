# lib-park

Vendored macro packages with no binding and no current demand. Same layout as `lib-ctan/` (CTAN-id directory, provenance, TDS `tex/`), never indexed, never on a search path. Returning an entry to `lib-ctan/` is the visible event of demand: a receipt that asks for the file, or a binding that starts delegating to it. See `docs/architecture.md` section 5.
