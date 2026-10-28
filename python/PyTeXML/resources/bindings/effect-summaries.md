# Bounded reading effects

Implemented preparation contract, 2026-10-25. This bounds possible writes; it does
not expand a macro, compute layout, execute a hook, or settle the eventual binding
authoring language. Execution routing belongs to the structural dispatcher.

## Authored and resolved forms

Command declarations use `metadata.effect_summary`; package load declarations use
`reading.load_effects.summary`. `EffectSummary` and `NameSet` are the immutable
Python records. Catalog validation rejects unknown domains and incomplete claims
of completeness. The normalized record is carried on retained requirements and
in the preparation journal.

```yaml
complete: true
scope: local
writes:
  meanings:
    names: ['@textbottom', '@texttop']
    prefixes: []
  registers: []
```

`complete` means the write bound covers the invocation and its transitive callees
under the declared prerequisites. It is not merely a list of assignments found
by a textual scan. An omitted domain means no writes **only in a complete
summary**. An incomplete summary may retain known writes but cannot preserve
unmentioned state. `unresolved` lists the unbounded dependencies and cannot be
nonempty when `complete` is true.

| Field | Implemented use |
| --- | --- |
| `scope: local/global/unknown` | Local meaning and integer-parameter uncertainty is restored on group exit. Global or unknown-scope writes also invalidate suspended outer state. |
| `writes.meanings.names/prefixes` | Literal control-sequence names and literal namespace prefixes, without the escape character. Matching is exact-name or `startswith`, not a substring search. Use the namespace delimiter: `Gm@` does not match `GmOther`. Namespace barriers also protect catalog fallback meanings not yet queried. |
| `writes.options.names/prefixes` | Package/class option-scope identities whose declarations or selection may change. Other option scopes retain their established state. Affected option state remains conservatively uncertain; this does not introduce group-local option replay. |
| `writes.registers` | Canonical cell identities without an escape character. Established integer-parameter values are invalidated with the declared scope; other register/layout values remain for interpretation. These writes do not assign control-sequence meanings. |
| `writes.catcodes` | Unicode character numbers whose category may change. Recorded; requires conservative fallback until a corresponding resolved lexical effect can be applied. |
| `writes.reader_parameters` | Reader parameter names. Recorded; unresolved writes require conservative fallback. |
| `writes.hooks` | Hook registration/effect knowledge. Recorded; hook timing and firing remain unsupported, so such summaries currently fall back conservatively. |
| `writes.loads` | Whether the operation may load code. True requires conservative fallback until load dependencies are resolved. |

`declared_effects` still performs its small existing meaning-copy recipe and keeps
layout in source. Its summary must include every copied target. `summarized_effects`
captures a declaration's literal data arguments, preserves the invocation, and
invalidates the bounded writes without computing their values. Both require a
source reference and `requires_unshadowed` prerequisites. A shadowed prerequisite
invalidates the contract. No complete summary is inferred from a package name,
an empty binding, or a formatting-looking command.

## Captured author bodies

The analyzer reads frozen body tokens at invocation, not raw source or a cached
definition-time environment. It accepts argument-free, delimiter-free bodies
composed of bounded local declarations, literal `let` targets, literal integer
assignments, known setters, established no-ops, and summarized calls with literal
data arguments. It unions the write sets without installing any assignment or
expanding the body. Definitions inside the body contribute their target writes;
their stored replacement text is not executed.
Integer-parameter writes use the resolved primitive's cell identity, including
through an alias. Literal capture here does not execute the new expanded-integer
operation or claim that a computed value has a complete effect summary.

Unknown callees, active/typesetting tokens, computed names/values, parameter substitution,
unresolved prerequisites, recursive calls, and calls whose dependencies may have
been overwritten earlier make the closure incomplete. Nested groups may cause
over-approximation of possible local writes, never a claim of no effects. Analysis
has both call-depth and total-work guards, so even an acyclic repeatedly invoked
body graph cannot grow without bound. Text emission needs mode/hook knowledge;
its lack of explicit assignments is not proof of no writes. A complete argument-free invocation consumes no
following groups; those remain ordinary source for the dispatcher.

The same declared writes disable stale grammars in nonexecuting dependency and
conditional observations. This does not turn a candidate into an active edge or
apply effects inside a stored/skipped region.

## Source provenance and package closure

The existing [CTAN vendoring recipe](../../../../docs/recipes/fetch-ctan.md) remains
the acquisition path. `ctan.json` is catalog metadata; `provenance.json` pins the
TeX Live archive, revision, checksum and selected runfiles; `ls-R` indexes restored
files; `entries.txt` records exceptional entry rules. These roles can carry into
the Python repository independently of the Perl runtime. PyTeXML uses the package
source as binding-authoring ground truth, not as a fallback interpreter.

The current checker's native/hybrid/passthrough classifications describe Perl
routes; they do not prove a Python binding implements a package. Preserve the
acquisition and provenance records when migrating, and replace that route-specific
admission check with PyTeXML's binding/source contract. The analogous provenance
stores under `lib-symb`, `lib-katex` and `lib-park` retain their distinct roles.

Geometry is pinned at `lib-ctan/geometry/provenance.json`, version 6.0, TeX Live
revision 78315. Its summary is deliberately incomplete: `geometry.cfg`, transitive
dependencies, option expansion, engine callbacks and deferred hooks are not
bounded yet. Inventory absence does not prove external-search absence. The
runtime cannot accept a complete package summary while declared optional inputs
remain unresolved. Pin references are authoring/validation evidence; preparation
does not re-read `lib-ctan` for each invocation.

The next package investigation is the closure of those inputs and calls, rather
than widening a whitelist until one specimen's branch disappears. Hook effect
timing, full context snapshots and asynchronous readiness are later contracts.

## Qualification

The dedicated-venv suite completed 824 tests (822 passed, two optional compiler
checks skipped), including 19 focused write-bound/body-analysis tests. The final
Fractal/DeadSalmons preparation iteration is `20261025-bounded-effects-verified`.
Both publish complete materialization with unchanged payload files and complete
source coverage, but remain partial in preparation: the newly explicit effect
dependencies do not yet close those package contracts. No fresh rendering or
relocation qualification is implied.
