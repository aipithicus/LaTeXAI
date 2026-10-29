# Hook-aware input preparation

The first slice covers LaTeX document-level braced inputs, including the empty
branches of `InputIfFileExists`. Unbraced `input` follows the kernel's primitive
route and does not acquire file hooks. Include, import and class/package load
protocols are separate capabilities. Include/import with observed file-hook
obligations retain their original entrypoint and resources.

`engine/hooks.py` owns global captured registrations and unresolved ordering.
`engine/file_hooks.py` declares the native format operations alongside their
handlers. These use the existing catalog and current-meaning lookup, so aliases
work and redefinitions take precedence. No YAML hook vocabulary is added.
The initial executable registration subset is the top-level label; explicit
other labels, rules and next-use operations retain an unresolved hook boundary.
Unresolved execution invalidates observed hook tables unless a complete effect
summary excludes hook writes. This follows the reader's existing bounded,
source-visible assumptions; it is not proof that arbitrary earlier opaque code
could not install a previously unobserved hook.

`engine/programs.py` evaluates bounded sequences through the existing dispatcher,
scope journals and operations. Generated coordinate buffers are diagnostic
views of frozen tokens, with original-token derivations; they are never parsed
back into tokens. An unsuccessful request restores its state and unit writes.
No package loading, filesystem I/O or typesetting runs in this consumer.

`engine/file_events.py` provides ordered events and file context around each
document input. `prepare/inlining.py` emits the corresponding kernel operations
around the body. Hook registrations and their executable bodies remain in the
payload. Python evaluates supported effects for analysis; the render executes
the residual TeX once. The input body gains no enclosing group. The trailing
empty group after context restoration is a lexical delimiter so the generated
control word cannot swallow a following authored space.
The selected kernel's string-assignment helper preserves filename character
categories (including underscores), and context is restored after nested loads.
Private helpers are checked for shadowing before publication. Unsupported
catcodes or filenames retain the input with a located requirement.
Context changes or uncertainty also require these operations when no hook is
registered: a macro left for rendering may read `CurrentFile`, and an assignment
to a context variable must not escape the input's lifetime.

The fixture includes N5's exact `gmfilehook` registration program and `gmhooked`
helper from gauntlet-master, alongside independent visible/state witnesses.
It exercises nested/repeated files, equal basenames, filename underscores, a
group spanning hooks and the body, a caller group/conditional closed by a child,
context use by deferred code, and physical-line `endinput` behavior. PDF text
extraction is an additional witness; exact page pixels and diagnostic identities
do not depend on the font's character-to-Unicode mappings.

The source contract is LaTeX2e 2026-06-01 patch 0. Its exact installed
`latex.ltx` hash, relevant source ranges and independent expected diagnostic
order are in `tests/fixtures/engine/file-hooks/contract.json`. This pins a
development witness, not the whole TeX Live package distribution or every
historical LaTeX format. Native rendering remains optional validation tooling.

From the PyTeXML directory, using the dedicated environment:

```text
python -B -m unittest discover -s tests -p test_file_hooks.py -v
python -B -m src.validation.file_hooks temp/hook-work/<new-name> --native-dir <texlive>/bin/windows --kernel <texlive>/texmf-dist/tex/latex/base/latex.ltx
```

The oracle command uses the public preparation and rendering adapters. It checks
the pinned kernel, ordered diagnostics, visible witnesses and exact 144-dpi
page pixels independently in native PDF and DVI modes. It also reads the
prepared payload with the original input files absent. Both native modes use
the concrete pdfTeX environment; this does not change or fully qualify the
restricted default `etex` exposure.

After focused qualification, run the complete PyTeXML suite and a fresh specimen
batch covering all four gauntlet-master roots and the five original papers.
Record newly reachable, retained and blocked cases separately. N5's log messages
alone are insufficient rendering evidence, and a synthetic render does not
certify all of Root A.

## Qualification checkpoint, 2026-10-28

The 24 focused tests pass. The `oracle-release` receipt checks the fixture in
both PDF and DVI modes: identical ordered diagnostics, visible witnesses and
exact 144-dpi pixels, plus a prepared-only reread with every original input absent.
Scoped registry/family type checking passes in 13 source files.
The final full-suite receipt is `full-release`: 1,092 tests run, 1,090 pass and
two optional Tectonic checks skip because that compiler is not configured.
Native PDF/DVI adapter checks run. Two traversal assertions now inspect authored
source order separately from the generated context pieces; the native fixture
independently verifies the resulting group/conditional and rendering behavior.

The default-profile corpus receipt is `20261028-hook-aware-inlining-context`;
compare it with `20261028-registry-consolidation`, not the intervening development
attempts. All nine payloads reread with their original trees unavailable: four
remain complete and five partial. The first three original-paper masters are
unchanged; the other two and roots B–D gain file-context operations while keeping
their previous requirements/assets/bibliography classifications.

Root A retains `body/paper.tex`: its master is 511 rather than 10,000 characters,
and canonical bibliography output is deferred. N5's registration program works
in the focused witness, but unresolved preceding effects invalidate its hook
table in the full root. Do not promote this run as a whole-root N5 success or
silently replace the accepted baseline.

Separate matching `pdftex` batches support native comparisons. Root D has equal
text and page pixels. Root A/B/C and the two changed papers are blocked on both
sides by missing `mathtools`, `biblatex`, `cite`, `eso-pic` and `microtype`,
respectively. Those failures do not qualify either side. The adapter's profile
guard correctly rejects a `pdftex` override on default-`etex` payloads.
