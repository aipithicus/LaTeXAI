# Engine registry

Each semantic family in `src/engine/primitives/` owns its handlers, operand
types, operation descriptors and primitive declarations. `src/engine/catalog.py`
imports the families explicitly and assembles their `FAMILY` records once.
Runtime dispatch resolves the current document meaning, then indexes the
operation dictionary by its stable identity. It does not scan modules or cache
behavior by the original control-sequence spelling.

## Adding a primitive

1. Select its owning family. Define an immutable operand type there if an
   existing type does not express the meaning; `DefinitionSpec` is an example.
2. Register a `PrimitiveOperation[Operand]` with an explicit `ExpansionKind`
   and concrete `operand_type`. Its execution, expansion, typed internal-value and
   raw-capture callbacks have separate signatures in `operations.py`.
3. Declare the spelling using that operation object's `declare(name, operand)`
   method and include the declaration in the family's `FAMILY`. The assembled
   meaning retains the operation ID and operand, independent of function identity.
4. Use `extension=True` for vocabulary requiring explicit profile selection.
   Update profile YAML when exposure changes. The common vocabulary is still
   the existing partial e-TeX baseline, not a complete upstream inventory.
5. Add focused semantic/interaction witnesses and run the relevant integration
   checks. A new family also needs one explicit catalog assembly entry; an
   ordinary primitive within an existing family does not.

`ExpansionKind.EXPANDABLE` requires an expansion callback or explicit
`expansion_unavailable=True`. The latter preserves a known capability boundary;
it does not grant expansion support. Implemented conditionals share the execution
owner's frame stack in ordinary and expanded input. An unexpandable primitive
requires an execution handler and cannot have an expansion callback. Unsupported
execution uses an explicit boundary handler, with distinct operands preserving
the affected primitive identities.

Temporary kernel bridges use `ExecutableOperation[EffectiveReadingProfile]`
with `ExpansionKind.INTERNAL`. They have no native declaration constructor.
They remain ordinary family entries while the corresponding kernel behavior is
still supplied by prototype reading profiles.

The file-hook bridge declares its format profiles in Python beside the family
handler. An internal operation may opt into execution after expansion; this
does not grant a native primitive declaration, internal-value role or expansion
callback. Ordinary current-meaning resolution still precedes that dispatch.

An `internal_value` callback returns an `InternalQuantity`: integer, scaled-point
dimension, token list or font identity. Integer scanning permits TeX's dimension
to scaled-point downgrade. `the` formats dimensions with `print_scaled` and
returns token lists through the shared insertion result; it never executes the
quantity's assignment handler. Token cells, input-stream positions and global
font arrays live in `ReaderContext` and participate in its transaction copies.

`src/engine/latex/` owns the Python adaptations of kernel declaration and optional
dispatch routines. Its explicit family list assembles one immutable name index;
lookup does not scan modules. Operations register in the shared operation catalog
and update ordinary scoped meanings. The declaration handler constructs native
public/hidden macros through the primitive scanner, while `CommandDefinition`
remains an authored observation. Superseded YAML command-definition recipes and
their execution bridge have been removed. Pinned kernel fragments remain test
references; production preparation does not load them as runtime source.

## Validation

Construction checks operand types, hashability, callback presence/callability
and capability combinations. Assembly rejects duplicate operation IDs, dangling
or replaced operation-object references, and duplicate spellings, including
common/extension conflicts. Profile construction rejects contradictory exposure
and produces one immutable environment. These checks do not inspect Python
function signatures; static checking owns handler/operand compatibility.

From `python/PyTeXML`, using the repository's Python 3.14 environment:

```text
python -B -m unittest discover -s tests -p "test_engine_*.py" -v
uv tool run --python ../.venv/Scripts/python.exe --from mypy==1.19.1 mypy --follow-imports=silent --ignore-missing-imports --warn-unused-ignores --cache-dir temp/typecheck/registry src/engine/operations.py src/engine/primitive.py src/engine/catalog.py src/engine/profiles.py src/engine/primitives tests/typing/engine_registration.py
```

The pinned checker runs in an isolated tool environment. This is a check of the
registry and its families, not a claim that the whole reader has been typed.
`tests/typing/engine_registration.py` includes positive inferred-type assertions
and negative examples with expected errors. `--warn-unused-ignores` fails when
one of those invalid registrations stops producing its expected type error.

The runtime tests also check independent import orders, immutable indexes and
declaration failures. Existing meaning, scope, expansion and preparation tests
exercise aliases and redefinitions through the same catalog. For integrated
changes, follow [specimen iterations](specimen-iterations.md); compare all four
gauntlet-master roots and the original papers against the named accepted
baseline, rather than only the most recent attempt under a different profile.
