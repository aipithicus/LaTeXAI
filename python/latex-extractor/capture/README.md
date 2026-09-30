# Downstream Capture & Projection Architecture

This directory defines the downstream projection specifications that map bound LaTeX constructs, environments, and commands to canonical XML IR elements, AST nodes, and semantic attributes.

---

## 1. Architectural Mirroring

The `capture/` layer mirrors the directory structure of `bindings/`:

```
python/latex-extractor/
├── bindings/                     # Pure syntactic comprehension & lexical rules
│   ├── engine/                   # Engine kernel primitives
│   │   ├── core_latex.yaml
│   │   └── verbatim.yaml
│   └── packages/                 # CTAN package bindings
│       ├── alltt.yaml
│       ├── comment.yaml
│       ├── fancyvrb.yaml
│       ├── listings.yaml
│       └── verbatim.yaml
│
└── capture/                      # Downstream IR projections mirroring bindings
    ├── README.md
    ├── engine/
    │   └── verbatim.yaml         # Projection for engine/verbatim (ltx:verbatim)
    └── packages/
        ├── alltt.yaml            # Projection for packages/alltt
        ├── comment.yaml          # Projection for packages/comment (null / discarded)
        ├── fancyvrb.yaml         # Projection for packages/fancyvrb (ltx:verbatim, boxed)
        ├── listings.yaml         # Projection for packages/listings (ltx:listing)
        └── verbatim.yaml         # Projection for packages/verbatim (\verbatiminput)
```

---

## 2. Separation of Concerns

* **`bindings/`** answers: *How is this read?* What are its catcodes, delimiters, whitespace rules, arity, and span classifications?
* **`policy/`** answers: *What should the pipeline do with it?* Should it be pruned, preserved, unwrapped, or routed to sidecars?
* **`capture/`** answers: *How is this represented in downstream IR?* What XML element is emitted, what attributes decorate it, and what semantic role does it fulfill in the document tree?

---

## 3. Projection Schema

Each capture file specifies:
* `identity`:
  * `name`: Identifier of the projection mapping.
  * `corresponds_to_binding`: Relative path to the authoritative binding in `bindings/`.
  * `target_format`: Downstream representation format (`ltx_xml`, `ast_json`, etc.).
  * `tier`: `engine_kernel` or `ctan_package`.
* `projections`:
  * `environments`: Map from environment name to XML element tag (`xml_element`), attributes, and `semantic_role`. Setting `xml_element: null` indicates that the environment emits zero IR nodes.
  * `commands`: Map from control sequence to XML element tag, attributes, and `semantic_role`.
