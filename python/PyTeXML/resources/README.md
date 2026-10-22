# Resource ownership

Python owns the reading algorithms. These YAML libraries supply knowledge and
configuration; they are loaded deliberately at bootstrap, then reused in memory.

| Store | Owner/consumer | Authority |
| --- | --- | --- |
| [bindings/](bindings/README.md) | Binding catalog and document resolver | Core/package syntax, reading effects, argument grammar, construct classifications, and package knowledge |
| [profiles/mouth/](profiles/mouth/README.md) | MouthProfiles and the reusable reader | Baseline catcodes, regex character classes, profile inheritance and local reading settings |
| [registries/reading_handlers.yaml](registries/reading_handlers.yaml) | Binding catalog | Current core reading-action vocabulary and capability status |
| [policies/prepare.yaml](policies/prepare.yaml) | Preparation policy loader | Role/event actions for preparing `master.tex` |
| [experimental/](experimental/README.md) | Explicit inspection and conformance tests | Alternative policy ideas and provisional output projections |

There is one package binding identity across stages. The current bindings contain
reading contracts; future interpretation can extend that ownership without
creating separate preparation copies of package knowledge. Author-local state
belongs to document execution and is not a global YAML library.

## Naming and references

Every resource YAML declares an explicit local identity equal to its filename
stem, with exact spelling and case. Use the existing schema field: `identity.name`
for engine bindings, mouth profiles, policies and engine projections;
`identity.package` for package bindings/projections; `identity.registry` for
registries. For example, `engine/verbatim.yaml` declares `name: verbatim`.
Missing or mismatched identities are configuration errors, including in custom
policy files. Loaders share the same validation; the resource-wide test also
checks experimental files that have no runtime consumer.

Directories establish namespaces within each library. Binding references use
qualified IDs such as `engine/verbatim` and `packages/verbatim`, without `.yaml`.
`requires_engine` and projection `corresponds_to_binding` fields use those IDs.
Mouth `profile` and `inherits` references already have an unambiguous mouth-profile
namespace and use local names. Top-level filesystem locations such as `resources/`
are not part of these IDs. Experimental projections have their own library
namespace and reference the corresponding binding explicitly.

Renaming a resource means changing its filename, declaration and references
together; no alternate identity aliases are maintained. Names inside aggregate
resources, such as handler keys and TeX command names, are not file identities and
do not require separate files.

## Loading boundaries

Profiles do not decide which source to delete. Policies do not define catcodes.
The handler registry does not repeat command names, syntax, scope, or effects from
the core binding. Its `context_effect` status means an immediate state helper
exists; `deferred` means a scanner/dispatcher is still required. Neither status
claims that a source occurrence is automatically dispatched today. The registry
currently covers only catcode mutators, grouping, and inclusions, not all future
TeX operations or literal handlers.

All runtime loaders use the duplicate-key-rejecting [YAML loader](../src/yaml_io.py).
Each owner validates its current contract. Mouth profiles validate inheritance and
regex rules; catalogs validate current identities and references; preparation
policies validate types, known fields and actions. Experimental projections have
conformance checks but no runtime loader or final output-schema authority.

Source provenance remains a preparation output. Binding `source_capture` metadata
describes lexical capture mechanics. Experimental XML projections describe
possible output forms. Those are three separate concerns.
