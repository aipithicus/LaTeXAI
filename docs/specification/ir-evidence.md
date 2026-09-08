# The IR carries evidence, not decisions

Why the LaTeXAI kernel diverges from LaTeXML, stated as a contract on what the IR must contain. Bindings are governed by [`bindings.md`](bindings.md); this document governs what the engine records around whatever a binding emits.

## 1. The problem

LaTeXML digests TeX into a tree and then parses each formula into structure. Both steps are heuristic in places and both discard information on the way. That is the correct design for its original purpose, rendering to HTML and MathML, where a plausible reading is the deliverable. It is the wrong design for a faithful IR that a downstream projection will read carefully, because the projection then inherits the engine's guesses without knowing which parts were guesses.

The register projection that consumes this IR needs to distinguish three things for any construct:

1. what the author wrote (the bytes),
2. what the author asked for (the construct, with its explicit choices),
3. what the engine made of it (the tree, with the decisions it took to get there).

Upstream keeps (3) in full, (1) not at all, and (2) only where it differs from a default. The kernel work exists to keep all three, side by side, in one document.

## 2. Worked example

Digesting the following with `--capture`:

```latex
$\operatorname{tr}A$   $\mathrm{tr}A$   $\mathbf{v}$   $\boldsymbol{v}$
\DeclareMathOperator{\Hom}{Hom} $\Hom(A,B)$
```

| Source | Engine's reading | What survives, and what does not |
| :--- | :--- | :--- |
| `\operatorname{tr}A` | application of `tr` (`role="OPFUNCTION"`) to `A` | the operator reading survives as a role; that `\operatorname` licensed it survives only in the bytes |
| `\mathrm{tr}A` | product: invisible times over identifier `tr` and `A`, both `role="UNKNOWN"` | the requested upright font is **absent** (it equals the engine's default for a multi-letter identifier); the product reading is a parser assumption recorded only in the log |
| `\mathbf{v}` | `v` with `font="bold"` | survives |
| `\boldsymbol{v}` | `v` with `font="bold italic"` | survives, distinct from the above |
| `\Hom(A,B)` | `Hom` (`role="OPFUNCTION"`, `name="Hom"`) applied to a wrapped list | the author's macro name survives as an attribute |

Two forms that render identically produced different trees, which is right. But one of them lost the author's explicit request, and the other carries a guess with nothing marking it as one. Those are the two shapes of loss this contract closes.

## 3. Contract

Every carrier in the IR (today `ltx:Math` and the `XMath` tree beneath it; the same rules extend to any element the engine is asked to be faithful about) records, in the capture namespace and never in the `ltx` namespace:

**E1. The bytes.** The exact source slice the carrier was digested from, byte-addressed against the retained file, with the ledger reconciling every carrier to exactly one provenance class. This is already in place; see `t/45_capture.t`.

**E2. What was requested in math, not only what differed from default.** Inside math mode a font is an alphabet, and alphabets are notation: `\mathbb{R}`, `\mathbf{v}`, `\mathrm{tr}`, `\mathcal{L}`, `\mathfrak{g}`, `\mathsf{T}` each say something a reader relies on, and so do explicit spacing, sizing, and delimiter choices. Any such choice the source states is recorded as requested even when it equals what the engine would have assumed; the author's stating it is the notational act. `\mathrm{tr}` records that upright was requested; bare `tr` does not.

Outside math mode a font is presentation, and this rule does not apply. Prose typography (`\textit`, `\sffamily`, `\small`, a document class's choice of face) is minutiae; the tree's existing font attributes and `ltx:emph` are what they are and E2 adds nothing to them. `\text{…}` inside a formula is text mode and falls on the prose side. The boundary is the engine's own mode, which every token already carries, not the name of the macro; that keeps the murky middle, a `\textbf` used inside a formula for a vector, on the side its context puts it.

**E3. Where the engine decided, not only what it decided.** Each point at which digestion or parsing took a heuristic step is recorded on the affected node: an identifier assumed simple, a juxtaposition read as application or product, a delimiter pairing resolved by guess, a font inherited across a boundary, a cell that failed and was wrapped as residue. The ledger already counts parser failures; the same channel carries parser assumptions, so a consumer can find every place the tree is an interpretation rather than a transcription.

**E4. Nothing is repaired.** A construct the engine cannot read stays as wrapped tokens with its bytes and its failure recorded. A construct a binding chooses to drop leaves a trace unless the binding argues, per construct, that its absence changes nothing about what the source means (see `bindings.md` section 3, item 5).

**E5. The `ltx` tree remains upstream's reading.** The contract adds evidence beside the tree; it does not change how the tree is built. A document digested without `--capture` is byte-for-byte what LaTeXML would produce, and every existing golden holds.

## 4. What this buys downstream

The first E2 slice is `capture:mathAlphabets` on `XMTok`: a JSON array of command stacks in source-box order. Each stack runs outermost to innermost and includes the backslash, including invoked aliases. Adjacent identical stacks collapse, while redundant nested commands remain: `\mathbb{\mathbb{R}}` records `[["\\mathbb","\\mathbb"]]`. A merged token whose first run requested upright and whose second run did not records `[["\\mathrm"],[]]`. Empty stacks appear only in a token with at least one explicit request. This is ordered request evidence, not character offsets or a claim that the resolved font honored the request. Text-mode entry clears the inherited request stack, including for math nested inside that text. The nine command families in this slice are `\mathbb`, `\mathbf`, `\mathrm`, `\mathcal`, `\mathfrak`, `\mathsf`, `\mathit`, `\boldsymbol`, and `\bm`; their resident package overrides use the same capture hook. Optional foreign attributes are already admitted by the common RelaxNG attribute rule.

Implemented label evidence uses `capture:labelValues` on the labeled element: a JSON object from each cleaned `labels` key to the text digested from `\@currentlabel` at that particular `\label`. Several labels on one target can have different values. Empty strings and `"0"` are retained. A visible optional item label is not necessarily this reference value. The Markdown consumer resolves a matching label through this map; `ltx:tags`, `refnum`, and capture-off output remain unchanged.

The projection from the IR to the math register is a set of rules over the tree's roles, meanings, and fonts, weighted by E3 and checked against E1 and E2. Concretely:

- `role="OPFUNCTION"` is strong evidence that a run is an operator name; the register may lower `\operatorname{tr}` to `\mathrm{tr}` and record the source form from E1 as provenance.
- Adjacent `role="UNKNOWN"` identifiers read as a product are weak evidence; E3 marks the reading as assumed, and the projection decides whether to trust it, consult E2, or fall back to E1.
- A requested math-mode font, upright, bold, blackboard, calligraphic, fraktur, sans (E2), is notation until the projection rules otherwise; the engine never rules. Prose typography never reaches the register and is not the engine's concern beyond what upstream already records.
- Residue (E4) is a signal to project from bytes, not from tree.

The engine's job ends at handing over evidence. Every decision about what the notation means belongs to the consumer, and the consumer can make it because nothing needed for it was thrown away.

## 5. Scope of the kernel changes

Changes under `lib/LaTeXML/Core/` and `lib/LaTeXML/Common/` are judged against E1 through E5. A change that makes the engine keep something it used to discard is in scope. A change that makes the engine decide something it used to leave open is not, unless the decision is itself recorded under E3. `MathParser` and the post-processors stay as they are and serve as oracles; the contract is satisfied by recording around them, not by rewriting them.
