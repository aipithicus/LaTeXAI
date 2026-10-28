# Engine profiles

`etex.yaml` is the default; `pdftex.yaml` exposes the additional supported
`\pdfoutput` parameter. These files select the initial environment, preparation
setup policy and reference-engine contract. They do not encode primitive operand
grammars or implementations.

Native operations live in `src/engine/primitives/`, assembled once by the
operation catalog. `src/engine/profiles.py` maps the common vocabulary and named
extensions to those operations. Lookup first checks scoped mutable meanings,
then the selected profile, then the remaining prototype kernel/package knowledge.
Aliases retain operation identity. Redefinitions and scope restoration work through
the same state as other meanings.

The profile distinguishes three states: an exposed operation, an explicitly
absent name, and unavailable knowledge about any other name. Unsupported does not
mean undefined. The current finite `absent` list is not a complete inventory of
all other engines' names. Both profiles are partial implementations, including
partial expl3 support; `\expanded` alone does not make expl3 executable.

The default profile permits preparation to capture literal `\pdfoutput=1`
setup without assigning the parameter or exposing its name. The original setup
remains in the payload, with `external_engine_setup` evidence. This does not
authorize arbitrary expansion, or make `\ifdefined\pdfoutput` true.

Each file is validated at load time and its SHA-256 is recorded in the manifest.
Oracle declarations describe the intended evidence sources. Actual executable
paths are explicit caller configuration; actual exposure is probed. Modern TeX
Live's `etex` and `latex` are pdfTeX-backed, so they do not exactly match this
default profile's absent `\pdfoutput`. See the [oracle recipe](../../recipes/engine-oracles.md).
