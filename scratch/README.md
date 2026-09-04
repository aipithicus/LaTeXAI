# scratch/

Disposable working files. Everything here except this README is gitignored.

Use it for anything an agent or a person writes to disk while working that is
not a deliverable: probe `.tex` inputs, ad-hoc `latexml` output dumps, test-run
transcripts, one-off helper scripts, before/after comparisons.

Rules:

- Put files under a subdirectory named for the actor or task
  (`scratch/codex/`, `scratch/claude/`, `scratch/tokenize-drift/`), never
  loose at the top level.
- Nothing here is an input to a test or a build. Fixtures live in
  `t/<suite>/`; goldens next to them as `*.xml`. If a scratch file turns out to
  be worth keeping, move it there and give it a test.
- Anything written by a test at runtime goes through `File::Temp`, not here.
- Delete freely. Nothing else in the repository may reference this directory.
