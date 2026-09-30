# Mouth profile contract

These files configure character reading. Python implements matching, N/M/S
transitions and scoped state; the YAML owns baseline assignments and profile
effects. `operations.yaml` is a separate provisional registry. Its handler names
are not dynamically imported or executed by the current reader.

## Regex character classes

```yaml
identity:
  name: example
  category: baseline_catcodes

lexical_mode:
  default: 12
  reader_parameters:
    endlinechar: 13
  character_classes:
    - id: letters
      kind: catcode_run
      domain: mouth_characters
      pattern: '[A-Za-z]+'
      catcode: 11
  catcode_overrides:
    '@': 11
```

The expression itself is compiled with Python `re` and remains available for
single-character and full-span membership, and for discovering maximal matching
runs. YAML single quotes preserve regex backslashes. For example, `'[\\]+'`
matches backslashes, `'[\r]+'` matches carriage returns, and `'[ \t]+'` matches
only ASCII spaces and tabs. The baseline deliberately uses `[A-Za-z]+`, without
case folding or Unicode letter inference.

`catcode_run` has a specific contract: one character class followed by greedy
`+`. This includes ranges, unions within a class, negated classes and regex
escapes such as `\u03B1`; escape a literal closing bracket as `\]`. It excludes
empty matches, anchors, lookaround, captures and position-dependent sequences.
Consequently matching a run agrees with matching its individual characters.
Structural/delimiter expressions need their own matcher contracts; they are not
catcode rules. Python `re` does not supply nested character-set intersection or
subtraction syntax; such ambiguous patterns are rejected, not reinterpreted.

Use `CharacterRule.fullmatch(text, start, end)` to test an entire nonempty span.
Use `CharacterRule.spans(text, start, end)` for maximal matching intervals at
unchanged offsets within that bounded view. A partial match is not whole-span
membership. No character universe is enumerated to replace the expression.
The reader memoizes encountered character classifications independently of these
span queries.

## Composition and scope

Inheritance composes immutable effect layers in order. Binding-level and
construct-level effects follow the selected profile; resolved option effects
follow those layers. An explicit character assignment overrides regex rules in
its own layer. A later applied layer can override an earlier explicit assignment.
Runtime assignments act above existing layers until a subsequent effect or scope
restoration changes that state. Restoring a scope keeps the live table object and
restores its layers, assignments and default category.

Two different catcodes matching the same character within one layer are an error
unless that layer explicitly assigns the character. ASCII conflicts are checked
at load time. Other-character conflicts are diagnosed on first lookup, naming the
rules and character. Catcodes must be integers from 0 through 15; booleans,
floating-point values and numeric strings are not coerced.

## Bootstrap and source views

```python
resolver = BindingResolver()
context = resolver.new_context("latex_ascii")
reader = TexReader(source, catcodes=context.catcodes,
                   endline_char=context.endlinechar)
```

Loading and validation happen at bootstrap. Context creation and reading perform
no file I/O or regex compilation. To share configuration without loading package
bindings, use `MouthProfiles(directory).baseline(name)` and pass that compiled
baseline to `ReaderContext`.

`mouth_characters` means characters at the reader's category-lookup boundary,
including any character preprocessing already performed. Standalone regex span
queries do not perform that preprocessing, execute commands or apply state
transitions. Their caller owns the supplied view and its source/occurrence/context
identity. Raw-byte provenance and transformed-character mappings are separate.

Literal profiles describe local effects rather than complete initial tables.
Only `baseline_catcodes` profiles may initialize a document. Missing directories,
inheritance cycles, duplicate profile identities and duplicate YAML keys are
configuration errors. Removed `catcodes.yaml`/`literals.yaml` files are not read.
