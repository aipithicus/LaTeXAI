# Markdown projection prototype

Status: implemented 2026-09-07. The projector turns one LaTeXML IR document into a continuous manuscript: front matter, linked contents, body, notes, and an ordinal bibliography. The new implementation lives in `lib/LaTeXAI/Post/Markdown.pm`; `lib/LaTeXAI/Post.pm` owns loading and optional bibliography preparation. The development CLI is `bin/latexai-markdown`. Engine output and the existing HTML processors are unchanged.

## Running it

Use the repository's `pwsh_exec` profile, which supplies `PERL_ROOT` and the source lookup configuration. From the repository root:

```powershell
& "$env:PERL_ROOT/perl/bin/perl.exe" bin/latexai-markdown `
  --output paper.md --report paper.markdown.json `
  --asset-root D:/path/to/paper-sources --path D:/path/to/bibliography paper.xml
```

`--asset-root` makes graphic paths absolute and supplies a source directory for bibliography preparation. Additional `--path` directories are passed to that preparation. Assets are linked in place; this command does not copy or convert them. Output and report paths must differ from the input and each other.

`--strategy deferred` is the default; `--strategy indexed` selects the comparison implementation. `--no-toc` omits Contents. `--prepare-only --output prepared.xml` completes external bibliographies and writes XML; `--no-prepare` uses supplied XML directly, reporting an unpopulated bibliography as residue. With no `--output`, the CLI writes UTF-8 to stdout. The optional JSON report records hashes, phase timings, traversal counters, selected math carriers, and diagnostics.

## Selection and traversal

Both strategies use the same depth-first selection and serializer. They visit manuscript content in XML order, consume small titles/tags into cached labels, and stop at each `Math` element. They select the primary `MathFork` content, including prose with inline math, and discard alternate branches. They skip navigation resources, duplicate TOC captions and tags already consumed as labels. The supplied DOM is read-only.

| Strategy | Metadata discovery | Reference resolution |
| :--- | :--- | :--- |
| `deferred` | During the manuscript walk | Typed reference fragments resolved during final serialization |
| `indexed` | A selective metadata walk before emission | References resolved when emitted |

The deferred strategy does one structural walk; the indexed strategy does two. Both also consume cached label content and serialize fragments. They keep ID/label and bibliography-key maps. Slugs are assigned in final manuscript order, reserving the title and generated headings; duplicate suffix searches retain their position. References never trigger a document-wide search.

Ordinary projection avoids constructing `LaTeXML::Post::Document` and its eager ID scan. Generic Scan/CrossRef/HTML processing serves additional purposes and is outside the measured walk. The comparison is between the two new Markdown implementations.

Both buffer fragments and the output string. Lists, table cells, inline styles and notes have local buffers; the body uses one fragment sequence. This is not a streaming parser or a constant-memory design. Nested formatting adds serialization work proportional to nesting. The index strategy shares emitter dispatch in a metadata mode; it is not a lower bound on every possible two-pass implementation.

## Manuscript conventions

| XML content | Markdown policy |
| :--- | :--- |
| Title, creators, affiliations | Front matter |
| Abstract and section hierarchy | ATX headings capped at level six; nested Contents |
| Paragraphs, emphasis, bold/italic text | Escaped prose with mixed-content boundaries preserved |
| Theorems and proofs | Bold cached heading followed by body |
| Inline/display `Math` | `$...$` or `$$` blocks from `@tex`; descendants opaque; `0` is a valid carrier |
| Figures | Asset link/image plus full caption |
| Enumerations and itemizations | Nested lists |
| Listings/algorithms | Quote lines, including continuations |
| Tables | Pipe tables; span origin holds content, covered cells stay empty |
| Notes | Inline footnote markers; Notes before bibliography |
| Bibliography | Final section with `[1]`, `[2]`, etc. in bibliography order |
| Citations | Ordinals for numeric citations; observed author-year patterns retain phrasing |
| References | Heading links where an anchor exists; otherwise readable labels |

An external `<bibliography files="...">` without entries requires preparation. `LaTeXAI::Post` clones the IR and invokes existing Scan/MakeBibliography machinery, using numeric bibliography formatting so authors and years remain in entry text. Prose citation styles stay intact. This can load and digest a `.bib` file. Its full cost is reported separately. Populated entries are used directly.

## Deliberate limits

- Math uses `Math/@tex`, not original source bytes or validated KaTeX. A caller can supply `math_renderer => sub { my ($math_node, $display) = @_; ... }`. Carrier whitespace is preserved except where containers require quoting, indentation or single-line table cells.
- The dialect uses pipe tables, dollar math, footnotes, and `^sup^` / `~sub~`. Rendering depends on the consumer. TOC anchors use lowercase, punctuation-stripped heading slugs with numeric collision suffixes; consumers with different math/heading slug rules may need an adapter.
- Spanning cells are flattened with a diagnostic per span; the first row supplies Markdown's mandatory header. Layout attributes beyond the listed conventions are omitted.
- PNG/JPEG/GIF/WebP/SVG paths become images. Other formats remain asset links with diagnostics. Embedded `picture` trees remain explicit markers.
- Unknown wrappers keep their children and a visible marker. Foreign/opaque content and missing reference targets get markers. Duplicate targets are reported; first registration wins.
- Citations/references inside cached titles remain explicit residue. The citation formatter covers patterns exercised by the study, not the entire CrossRef show-language.
- Preparation failures and invalid/overlapping table spans fail the command. Successful projection does not clear upstream digestion errors.

## Verification and timing

```powershell
ltst t/98_markdown.t
./tools/dev/markdown-compare.ps1 `
  -Manifest D:/path/to/inputs.json `
  -OutputDirectory D:/path/to/new-comparison-directory `
  -Repetitions 15
```

Manifest schema: `latexai/markdown-projection-inputs/0.1`. Each input supplies `slug`, `xml`, `xmlSha256`, `receipt`, `receiptSha256`, original engine `arguments` (including source `--path`), and `counts`. Keep engine commit, source-tree hash, entrypoint, and texmf index hash as provenance.

The launcher refuses an existing output directory and verifies input hashes. Preparation runs once per input. Each strategy gets a fresh Perl process, parses the same prepared XML, warms up once, then repeatedly projects the same DOM. Execution is sequential, alternating the first strategy across papers. The worker rejects warning-contaminated measurements, nondeterministic Markdown, and DOM mutation. The launcher requires byte-identical Markdown and equivalent diagnostic multisets.

`comparison.json` pins the manifest, prepared inputs and code hashes. Reports retain all samples, phase medians and parse time. Headline `deferred_ms` / `indexed_ms` are medians of complete `project()` calls, including return-time cleanup; internal `index`, `walk`, `finalize` and `total` times are also retained. Hashing and output-file I/O are outside call timings.

Sampled process peak working set includes Perl, parsing, warmup and repeated projection. Sampling can miss the final 20 ms; this is not incremental projector allocation. These measurements characterize a bounded corpus slice on one machine. They establish neither HTML speedup nor a full-gauntlet result.
