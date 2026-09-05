# temp/

Disposable working files. Everything here except this README is gitignored.

Use it for anything an agent, a person, a probe, or a test writes to disk that
is not a deliverable: probe `.tex` inputs, ad-hoc `latexml` output dumps,
conversion logs, test-run transcripts, one-off helper scripts, before/after
comparisons.

Layout:

| Path | Holds |
| :--- | :--- |
| `temp/logs/` | every `*.latexml.log` and `latexmlpost` log, from probes and tests alike; the jobname is in the filename, so this is flat |
| `temp/t/<test>/` | output a test driver writes to disk |
| `temp/bindings/<pkg>/` | intermediates while minting a binding: census, stub, probes, before/after outputs |
| `temp/<actor-or-task>/` | anything else, named for who or what produced it (`temp/codex-1/`, `temp/tokenize-drift/`) |

Rules:

- Nothing loose at the top level.
- Nothing here is an **input** to a test or a build. Fixtures live in
  `t/<suite>/`; goldens next to them as `*.xml`. If a temp file turns out to be
  worth keeping, move it there and give it a test.
- Tracked code may **write** here (a `--log` default, a driver's output
  directory) but never reads from here.
- Delete freely.
