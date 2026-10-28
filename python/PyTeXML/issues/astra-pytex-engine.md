Let’s describe **the language operations themselves**, independently of how Python eventually schedules them.

I’ll group closely related primitives, but preserve differences that affect behavior. These are compact contracts for valid input; malformed operands also produce diagnostics.

A few conventions:

- **Raw token** means read without expansion.
- **General text** means a balanced token list with its enclosing braces removed. Finding the opening brace can involve expansion; collecting the contents follows the operation’s rules.
- **Quantity** means a typed TeX scan—integer, dimension, glue or muglue—including permitted expansion.
- **State effects** below are the operation’s direct effects. Expansion performed while obtaining operands can introduce additional effects.

**Expandable**, **executable**, and **value-producing** are different properties. An executable command can expand its operands; a value-producing operation can be usable by a numeric scanner without itself expanding into digit tokens.

Definitions and meaning assignments establish what subsequent commands do.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\def` | Target, parameter pattern, braced replacement body | Executable. Target, pattern and body are read raw | Installs a macro meaning, normally locally | A callable macro; no emitted content |
| `\gdef` | Same | Same raw capture | Installs the macro globally by default | Same |
| `\edef` | Same | Executable. Target and parameter pattern are raw; replacement body undergoes expanded-list construction | Installs the resulting macro, normally locally | A macro containing the constructed replacement tokens |
| `\xdef` | Same | Same as `\edef` | Global definition by default | Same |
| Macro invocation | Literal prefix and arguments specified by its parameter pattern | Match arguments without expanding them; substitute them into the replacement | No assignment inherent in substitution | Replacement tokens become available for subsequent processing |
| `\let` | Target, optional `=`, donor token | Executable. Neither target nor donor expands; spacing follows the special `\let` grammar | Copies the donor’s current meaning to the target | Target subsequently has that copied meaning |
| `\futurelet` | Target, token A, token B | Executable. Reads all three raw | Copies B’s current meaning to the target | A and B remain available, in that order |

For macro matching, undelimited arguments are one token or a balanced group; delimited arguments run to the declared delimiter at the appropriate brace depth. Parameter-token comparison must exclude provenance. Doubled parameter markers and the special `#{` form belong to definition compilation.

The “global by default” wording matters: `\globaldefs` can override even the usual local/global distinction. TeX’s definition and assignment code makes that override explicit. [TeX source: prefixed commands and definitions](https://raw.githubusercontent.com/TeX-Live/texlive-source/trunk/texk/web2c/tex.web#L20848)

Prefixes and grouping modify assignment behavior and lifetime.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\global` | Further prefixes followed by an eligible assignment | Executable prefix; expansion can occur while finding the assignment | Sets its pending global flag, subject to `\globaldefs` | The assignment survives group restoration |
| `\long` | A macro definition, possibly with other prefixes | Executable prefix | Sets a macro attribute | Its arguments admit paragraph tokens where an ordinary macro would reject them |
| `\outer` | A macro definition | Executable prefix | Sets a macro attribute | Use is rejected in restricted scanning contexts |
| `\protected` | A macro definition | Executable prefix | Sets a macro attribute | Macro remains unexpanded in expanded-list contexts, but expands during ordinary command processing |
| Group entry/exit | Grouping tokens or `\begingroup` / `\endgroup` | Executable; delimiters do not expand themselves | Establishes or closes a typed scope; restores local assignments; releases after-group tokens | Restored context and any scheduled tokens |
| `\globaldefs` assignment | Optional `=`, integer | Executable; integer scan can expand | Changes assignment-scope policy | Positive forces global assignments; negative forces local ones; zero uses ordinary rules |

Braces have additional meanings in math, box construction and argument capture. A captured argument’s braces do not, merely by being captured, execute a scope.

Expansion control determines which tokens become available next.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\expandafter` | Raw token A, raw token B | Expandable. Performs one expansion action on B if expandable, then places A before the result | Changes processing order | A followed by B’s result; B’s expansion may consume further operands |
| `\noexpand` | One raw token | Expandable. Suppresses that occurrence’s next expansion | Temporary suppression associated with the occurrence | The token survives the expansion step |
| `\unexpanded` | General text | Expandable. Body collected raw | No direct lasting assignment | Body tokens, protected from further expansion in the current expanded-list construction |
| `\expanded` | General text | Expandable. Constructs an expanded token list, respecting protection rules | No direct definition assignment | Constructed tokens returned for subsequent processing |
| `\csname` | Material ending in `\endcsname` | Expandable. Expands material to obtain name characters | If the resulting name is undefined, locally gives it `\relax` meaning | One control-sequence token |
| `\endcsname` | None | Terminates the corresponding name scan | Ends that scan | No independent content |
| `\relax` | None | Unexpandable; execution does nothing | None | No content; scanners may treat it as a terminator |

Two details are important: `\noexpand` does not permanently protect a command, and `\expanded` constructs a token list without installing a definition. [Implementation account of `\expanded`](https://www.texdev.net/2018/12/06/a-new-primitive-expanded)

Inspection and conversion turn existing objects into tokens.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\string` | One raw token | Expandable; operand itself does not expand | Reads printing parameters such as `\escapechar` | Character tokens spelling that token |
| `\meaning` | One raw token | Expandable; operand itself does not expand | Reads its current meaning and relevant printing parameters | TeX’s textual description of that meaning |
| `\number` | Integer | Expandable; integer scan can expand | Reads quantity dependencies | Signed decimal character tokens |
| `\romannumeral` | Integer | Expandable; integer scan can expand | Reads quantity dependencies | Lowercase Roman-numeral tokens; empty for nonpositive values |
| `\the` | Internal quantity, register or token-list reference | Expandable; scans the applicable internal value | Reads that value | Its specified token representation; token registers return their contents |
| `\detokenize` | General text | Expandable; body collected raw | Reads applicable serialization parameters | Character tokens, mostly category 12, with spaces category 10 |
| `\lowercase` / `\uppercase` | General text | **Executable**; body collected raw | Reads `\lccode` / `\uccode` | Reintroduced tokens with mapped character codes and preserved categories |
| `\scantokens` | General text | Expandable; body collected raw, serialized, then read as characters | Establishes a new input source under the applicable reading state | Newly tokenized input, including any subsequent effects it produces |

There is a special expanded-list rule for `\the` applied to a token register: its returned tokens are not expanded again during that construction. The same protection applies to `\unexpanded`’s result. Retokenization through `\scantokens`, however, deliberately returns to the character-reading machinery. [e-TeX specification](https://mirrors.ctan.org/systems/doc/etex/etex_man.pdf)

Conditionals select subsequent processing; they do not emit a Boolean text value.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\if` | Two operands obtained through expansion | Expandable; compares character-code interpretations | Opens conditional state | Selection of true or false branch |
| `\ifcat` | Same | Expandable; compares category interpretations | Same | Branch selection |
| `\ifx` | Two raw tokens | Expandable, but does not expand operands; compares meanings, including macro attributes and token bodies | Same | Branch selection |
| `\ifnum` / `\ifdim` | Quantity, relation `<`, `=` or `>`, quantity | Expandable; typed operand scans can expand | Same | Branch selection |
| `\ifodd` | Integer | Expandable; scans integer | Same | Branch selected by parity |
| `\ifdefined` | One raw token | Expandable; no operand expansion | Opens conditional state; creates no definition | Branch selected by definedness |
| `\ifcsname` | Expanded name material through `\endcsname` | Expandable | Opens conditional state without `\csname`’s definition-creation effect | Branch selected by definedness |
| `\iftrue` / `\iffalse` | None | Expandable | Opens conditional state | Constant branch selection |
| `\ifcase` | Integer, followed by alternatives separated by `\or`, optionally `\else` | Expandable; scans integer | Tracks selected alternative | Alternative zero, one, etc.; otherwise the fallback |
| `\unless` | One raw Boolean conditional token, then that conditional’s operands | Expandable; reverses that predicate; excludes `\ifcase` | Uses the conditional’s state effects | Reversed branch selection |
| `\else`, `\or`, `\fi` | No ordinary operands | Expandable control operations | Advance or close conditional state | Skip remaining alternatives or resume following input |
| Mode tests | `\ifhmode`, `\ifvmode`, `\ifmmode`, `\ifinner` | Expandable; no operands | Read execution mode; open conditional state | Branch selection |
| Box tests | `\ifvoid`, `\ifhbox`, `\ifvbox` followed by a box-register number | Expandable; scans number | Read box status; open conditional state | Branch selection |
| `\ifeof` | Input-stream number | Expandable; scans number | Reads stream status; opens conditional state | Branch selection |

Skipped material uses conditional-skipping rules rather than ordinary macro expansion. Thus *evaluating a condition* and *finding the end of its unselected branch* are distinct operations.

Registers require typed scanning and assignment.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| Register reference | `\count I`, `\dimen I`, `\skip I`, `\muskip I`, `\toks I`, or an established alias | Index scans can expand; interpretation depends on the consuming operation | Reads register identity | A typed register reference |
| Register alias definition | `\countdef C [=] I`, and corresponding dimension/glue/token forms | Executable; target raw, index scanned | Binds C to the register | Another name for the same storage |
| Character-code definition | `\chardef C [=] I`, `\mathchardef C [=] I` | Executable; target raw, value scanned | Installs a character/math-character meaning | A command usable according to that meaning |
| Numeric assignment | Typed target, optional `=`, compatible quantity | Executable; quantity scan can expand | Writes the target with applicable scope | Updated value; no emitted content |
| Token-list assignment | Token-list target, optional `=`, braced body or another token-list variable | Executable; can expand while locating the RHS form; braced contents collected raw | Stores or copies a token list | Updated stored tokens |
| `\advance` | Numeric target, optional `by`, compatible quantity | Executable; scans operands | Adds to target | Updated value |
| `\multiply` / `\divide` | Numeric target, optional `by`, integer | Executable; scans operands | Scales target; division truncates | Updated value |
| Expression operations | `\numexpr`, `\dimexpr`, `\glueexpr`, `\muexpr` followed by typed arithmetic | Interpreted by quantity scanners; nested operands can expand | No assignment inherent in expression evaluation | Typed value returned to the consuming operation |

Integer scanning includes signs, decimal/octal/hexadecimal constants, backtick character codes and permitted internal quantities. Dimension scanning additionally handles units and internal dimensions. Glue adds stretch and shrink components and their orders.

Expression arithmetic must preserve e-TeX’s range checks and rounding rules. In particular, expression division rounds, whereas `\divide` truncates. These are different operations even if Python could implement both with one arithmetic expression. [e-TeX arithmetic specification](https://mirrors.ctan.org/systems/doc/etex/etex_man.pdf#page=8)

Reading parameters and character tables fit the same assignment model.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\catcode` assignment | Character number, optional `=`, category number | Executable; numeric operands can expand | Writes the category table | Changes subsequent character tokenization |
| `\lccode`, `\uccode`, `\mathcode`, `\delcode`, related table assignments | Character number, optional `=`, typed code | Executable; operands scanned | Writes the corresponding table | Changes later case conversion or character/math interpretation |
| Reader/printing parameter assignment | Parameter, optional `=`, integer | Executable; value scanned | Writes `\endlinechar`, `\escapechar`, `\newlinechar`, etc. | Changes the corresponding future reading or serialization behavior |
| State inquiry | Applicable internal quantity, such as group level/type | Read by a quantity consumer | Reads engine state | Numeric or otherwise typed observation |

Changing catcodes does not change tokens already captured.

Deferred actions introduce timing obligations.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\afterassignment` | One raw token | Executable; token not expanded now | Replaces the pending after-assignment token | Token becomes available at the next assignment’s specified insertion point |
| `\aftergroup` | One raw token | Executable; token not expanded now | Records token for the current group’s exit | Recorded tokens become available after restoration, in registration order |
| `\every…` assignment | Token-list assignment grammar | Contents captured without execution | Replaces the relevant event token list | Tokens run when that particular engine event occurs |

A box-construction assignment has special `\afterassignment` timing: the saved token enters the new box before its body is processed, rather than waiting for the completed box. That timing is observable and belongs in the operation’s tests.

Input and output operations have different capture and activation times.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\input` | Filename under the selected engine’s filename grammar | Expandable; filename acquisition can expand | Adds an input source | Its contents become available |
| `\endinput` | None | Expandable | Prevents loading further lines from the current file | Current-line material can still finish |
| `\openin` / `\closein` | Stream number; opening also takes optional `=` and filename | Executable; scans operands | Opens/closes input stream | Changed stream status and available data |
| `\read` | Stream number, keyword `to`, raw target | Executable; read text is tokenized without macro expansion | Advances stream and defines a parameterless macro | Captured input tokens |
| `\readline` | Same | Executable; line characters get prescribed categories rather than current catcodes | Same | A line represented predominantly by category-12 tokens |
| `\write` | Stream number and general text | Executable; captures body now, normally expands it when the write occurs | Schedules output activity | Serialized expanded output at that later point |
| `\openout` / `\closeout` | Output-stream operands | Executable; normally deferred | Schedules output-stream changes | Stream opened or closed when activated |
| `\immediate` | Following output operation | Obtains the following operation through expansion | Makes eligible output activity occur now | Immediate output or stream change |
| `\message` / `\errmessage` | General text | Executable; constructs expanded text now | Diagnostic/error state | Message or error, rather than document content |

For boxes and content, the operations remain observable even when page layout is excluded.

| Operation | Operand grammar | Expansion behavior | State effects | Observable result |
|---|---|---|---|---|
| `\hbox`, `\vbox`, `\vtop` | Optional `to D` or `spread D`, then a body | Executable; scans specification, then processes body | Opens box scope/mode; runs applicable hooks and body effects | Constructed box |
| `\setbox` | Register number, optional `=`, box specification | Executable; constructs or obtains the box | Stores it with applicable scope | Updated box register |
| `\box` / `\copy` | Box-register number | Executable; scans number | `\box` removes the stored box; `\copy` preserves it | Box supplied to the current construction |
| Unboxing operations | Box-register number | Executable | Move or copy contents according to the variant | Contents supplied without the enclosing box |
| `\wd`, `\ht`, `\dp` | Box-register number; optionally an assignment RHS | Typed read or executable assignment | Reads or changes a box metric | Dimension value or updated metric |
| `\char` / `\mathchar` | Character or math-character code | Executable; scans code | Reads applicable font/math state; contributes to current construction | Character or math atom |
| Spacing/rule operations | Their dimension, glue, integer or keyword specifications | Executable; operands can expand | Change current constructed list | Glue, kern, penalty or rule |
| Math-field operations | Character, command or grouped math field, depending on operation | Field scanning and subsequent execution | Change math construction state | Atoms, scripts, fractions or delimiters |
| Alignment operations | Preamble/templates and rows, with alignment-specific delimiters | Special preamble capture and per-cell processing | Manage templates, cells, groups and alignment state | An alignment structure |

Those last two families need their own detailed grammar expansions: `\over` is an infix operation on the current math list, for example, while `\halign` introduces a template language. Treating either as an ordinary command with braced arguments would lose its semantics.

One small example captures why these distinctions matter:

```tex
\edef\a{\count0=5}
\edef\b{\the\numexpr2+3\relax}
```

The first constructs a macro containing assignment tokens; it does not assign the register during the `\edef`. The second constructs a macro containing `5`, because `\the` invokes the expression’s value-producing behavior.

For Python, each row can therefore become a concrete semantic operation with tests for **what it consumes, what it expands, what it changes, and what it produces**. Shared scanners implement the operand grammars; the operations retain their distinct timing and effects.

**Yes. I would use a stateful Python object as the execution context, with the operations implemented as ordinary Python methods or functions.** Its statefulness can be local to a selected region; it doesn’t require interpreting the whole document in one continuous pass.

The main design choice is to separate **the state being manipulated** from **the machinery manipulating it**.

| Component | Owns |
|---|---|
| `EngineState` | Meanings, registers, character tables, parameters, box contents, and scope journals |
| `TeXMachine` | The current operation’s execution: input position, pending prefixes, conditionals, expansion context and limits |
| `Scanners` | Operand grammars: targets, arguments, parameter patterns, numbers, dimensions, glue |
| `Expander` | Macro application, replacement construction and expansion control |
| Primitive implementations | The actual behavior of `\def`, `\let`, `\ifnum`, etc. |
| Result collector | Produced tokens/content, diagnostics and recorded effects |

These can begin as a few small modules. There is no need for a class hierarchy corresponding to every primitive.

An illustrative shape would be:

```python
class TeXMachine:
    def __init__(self, state, input_view, primitives):
        self.state = state
        self.input = input_view
        self.primitives = primitives

        self.control = ControlState()
        self.scan = Scanners(self)
        self.expand = Expander(self)
        self.results = ResultCollector()

    def meaning_of(self, token):
        return self.state.meaning_of(token)

    def assign_meaning(self, target, meaning):
        scope = self.control.assignment_scope(self.state)
        self.state.assign_meaning(target, meaning, scope=scope)
```

Here, `input_view` can traverse the captured fragments associated with the work being evaluated. The existing character reader remains responsible for reading source characters and for explicit retokenization operations.

**The four fields we described then have straightforward implementation homes:**

| Contract field | Implementation |
|---|---|
| Operand grammar | Calls to scanner methods |
| Expansion behavior | Explicit choice of raw reading, expansion step, or expanded-list construction |
| State effects | Calls through the state API |
| Observable result | Returned values, generated fragments, content or diagnostics |

For example, `\let` could be a small imperative implementation:

```python
def execute_let(machine):
    target = machine.scan.assignable_token()
    donor = machine.scan.let_donor()

    meaning = machine.meaning_of(donor)
    machine.assign_meaning(target, meaning)
```

`let_donor()` owns the exact optional-equals and whitespace rules. `assign_meaning()` owns prefixes, `\globaldefs`, scoping and recording the write. The primitive therefore expresses its particular semantics without duplicating shared machinery.

**I would make meanings immutable, while keeping the machine’s state mutable.**

A macro meaning would contain its compiled parameter pattern, replacement fragments and flags. A primitive meaning would identify an operation and its variant. A register meaning would identify a storage location.

That gives useful behavior naturally:

- Assigning a new meaning replaces a table entry.
- Copying a meaning preserves the copied object.
- Definitions and captured token material can be shared safely.
- Register references can share a location while the value stored there changes.

For scopes, I would use a **journal of changed entries**. Entering a group starts a journal; a local assignment records the prior value; leaving restores it. Global assignments must update the restoration bookkeeping so an enclosing group cannot resurrect an obsolete value.

Your existing [`ReaderContext`](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/context.py:234) already uses this approach for local meanings. I would build on that ownership model and extend it to the additional state domains. The reader and evaluator should ultimately use the same definitions of meanings and scope behavior.

The expansion API needs particular care. I would expose distinct operations such as:

```python
read_raw_token()
expand_once(...)
next_expanded_token(...)
build_expanded_list(...)
```

Those have different contracts. A single generic `evaluate()` called everywhere would make it too easy to expand an argument that must remain raw, or execute an assignment while constructing an `\edef` body. Scanners should explicitly select the behavior their grammar requires.

For your staged architecture, the important boundary is **how a machine acquires and publishes state**. A machine starts with an explicit context and owns its working mutations. The document-level resolver decides which work becomes ready and whether its resulting changes are accepted. We can specify that interface later without changing how `\let` or integer scanning works internally.

I would implement the first coherent slice as:

1. Immutable meaning objects and scoped state.
2. Raw token access and macro-argument matching.
3. Definition construction and macro substitution.
4. `\let`, prefixes and group restoration.
5. Expanded-list construction and the expansion-control primitives.

That would exercise the object model against real semantic differences before adding the register, conditional and I/O families. Each primitive could be tested directly against a small initial state and token fragment, checking consumed operands, resulting state and produced tokens.



Yes. **The pattern I’d use is a table-driven interpreter: an explicit catalog of operations, ordinary Python handler functions, and a small stateful runtime.** It is a function-based version of the *Command pattern*; it does not require a separate class for every command.

Your concern is about organizing, locating, and composing behavior. Python functions can live in an organized catalog just as easily as declarative records can.

The important separation is:

| Component | Responsibility |
|---|---|
| **Operation catalog** | Which engine operations exist, and where their implementations are |
| **Handlers** | How each operation scans operands, expands, changes state, and produces results |
| **Machine and state** | The current evaluation, meanings, scopes, registers, and input |
| **Shared scanners and expansion machinery** | Reusable TeX mechanisms that handlers call |

**The catalog grows as vocabulary grows; the central execution loop should usually remain unchanged.**

For example, the executable side could look like this—illustrative Python, not a proposed complete API:

```python
# primitives/definitions.py

def execute_let(machine):
    target = machine.scan.assignable_token()
    donor = machine.scan.let_donor()
    machine.assign_meaning(target, machine.meaning_of(donor))


OPERATIONS = (
    ExecutablePrimitive("tex.let", execute_let),
    ExecutablePrimitive("tex.futurelet", execute_futurelet),
    ExecutablePrimitive("tex.def", execute_def),
)
```

Then one explicit assembly point:

```python
# catalog.py

CORE_OPERATIONS = build_catalog(
    definitions.OPERATIONS,
    expansion.OPERATIONS,
    conditionals.OPERATIONS,
    registers.OPERATIONS,
    grouping.OPERATIONS,
)
```

`build_catalog` checks duplicate identities and produces an immutable lookup. Once the machine has resolved something as an executable primitive, dispatch amounts to:

```python
meaning.execute(machine)
```

There can still be a small central distinction between macro application, primitive execution, and ordinary character handling. Those are fundamental language categories. Adding `\futurelet` should not require adding another branch there.

A few design choices make this coherent as it grows.

**Group by semantic responsibility, rather than making a module for every primitive.** Definitions and meaning assignment belong together; conditionals belong together; register operations belong together. Split a family when it develops distinct responsibilities or becomes difficult to navigate. A hundred operations need not mean a hundred modules.

**Keep registration explicit and boring.** Each family exports its operations; one catalog assembles the families. You can answer “where is this implemented?” by following a direct reference. I would start without automatic module discovery or decorators that mutate a global registry during import.

**Keep the fixed operation catalog separate from mutable TeX meanings.** The catalog contains implementations such as the operation underlying `\let`. The machine’s state contains what control sequences currently mean. A `.sty` file defining fifty macros adds fifty macro meanings to that state; it does not require fifty new Python handlers.

**Give genuinely different behaviors appropriate interfaces.** Execution, expansion, and supplying an internal quantity have different needs. They can have different handler protocols, and an operation can support multiple roles. We should establish these distinctions from TeX’s behavior instead of forcing everything through one generic function returning an arbitrary dictionary.

**Keep the four-part contract beside its implementation.** Operand grammar, expansion behavior, state effects, and observable result belong in concise documentation and behavioral tests adjacent to the handler. Only information the runtime actually uses needs to become catalog metadata. That keeps us from accidentally inventing a second programming language for describing Python behavior.

The stateful class also needs a boundary: it coordinates evaluation. Scope restoration belongs to the state implementation; numeric scanning belongs to scanners; macro substitution belongs to expansion machinery. Handlers use those shared mechanisms and retain operation-specific sequencing. This prevents `TeXMachine` from becoming the next giant accumulation point.

For rollout, I would establish this structure with one coherent family—definitions and meaning assignment—then exercise its interactions with macro expansion and grouping before expanding the catalog. The existing reader’s [`_next_item`](/D:/aipithicus/LaTeXAI/python/PyTeXML/src/reading/dispatcher.py:276) provides a concrete place to examine the current dispatch responsibilities, while keeping reader preparation and evaluator execution distinct.

The practical acceptance criterion is: **adding an ordinary primitive should require its handler, its family’s registration entry, and behavioral tests.** Changes to the runtime should mean we discovered a new shared capability, rather than merely another command name.


## Gemini's notes 

> **Not part of the spec.** Rejected on 2026-10-27 (language-core decision L9).
> Its `(DefScan, execute_def)` split runs operand scanning before execution,
> which primitives can't do. It also treats a `\def`'s meaning as a reference to
> `execute_def`, which confuses the operation catalog with meanings.

One common pattern is to have a **dispatcher, not a giant central class**. The dispatcher knows the current mode (e.g., expansion, execution, numeric scan) and delegates to the right small handler. Only the dispatcher and the catalog itself need to grow as new operations are added.

The evaluator does not need to know the details of how `\def` scans its arguments or how `\ifnum` reads tokens. It only needs to know:

| Query | Answer | Purpose |
|-------|--------|---------|
| What is the current primitive? | A handler function and its operand-scanning mode | Control of the control-sequence dispatch. |
| What do the arguments look like? | A parser/scanner (or a set of them), returning structured arguments | Determine how many tokens the primitive will consume and what their role is. |
| What should happen next? | Call the handler, which updates state and returns the next task | Manage evaluation order. |

For PyTeXML, you can already see a light version of this in the reader:

- `_next_item` dispatches based on whether the current token is a control sequence, special, or character.
- Different branches call `self._scan_assignable_token`, `self._scan_let_donor`, or `self._scan_assignment_value`, each returning a concrete token or structure.

To expand this to the evaluator, you don't need to give `_next_item` access to assignment implementations. You can keep those entirely separate.

One way to organize this without a monolithic evaluator class:

| Module | Contents | Lifetime/Scope |
|--------|----------|----------------|
| `primitives/definitions.py` | `\def`, `\futurelet`, `\let`, etc. and their scanners/handlers | Loaded once, kept in a catalog registry for the evaluation session. |
| `primitives/execution.py` | `\hbox`, `\vbox`, `\setbox`, dimension/glue operations, `\par` | Similarly cataloged. |
| `primitives/registers.py` | `\count`, `\dimen`, `\skip`, `\muskip`, reading/assigning them | Similarly cataloged. |
| `primitives/conditionals.py` | `\ifnum`, `\ifcat`, `\ifx`, `\else`, `\fi` | Similarly cataloged. |
| `primitives/io.py` | `\read`, `\write`, `\input`, `\open`, etc. | Similarly cataloged. |
| `catalog.py` | `build_catalog`, `select_operation`, and the combined registry | Loaded once per evaluation session. |
| `evaluator.py` | `EvaluationContext` and `evaluate` method | Owns the overall control flow, and holds per-session state like input/output streams and the current scope. |

In this organization:

- When the reader loads a macro or a `.sty` file, it:
  - scans operands for assignments and definitions, and
  - adds corresponding meanings (which could be direct references to the handler functions) into the `EvaluationContext` or its registry.
- When the evaluator needs to act on a control sequence, it:
  - looks up the meaning using its current scope rules;
  - if it’s a primitive (i.e., has a handler), it:
    - calls the handler’s operand scanner to determine how many tokens to consume, and what they are;
    - calls the handler itself, which updates state, expands things, and returns the next task or the produced output.
- If the meaning is a macro (i.e., stored replacement text), the evaluator:
  - renames the macro and pushes it onto the expansion stack (or just inserts its contents into the expansion queue), and then repeats the scan-dispatch cycle.

So, instead of a monolithic `Evaluator` class, you can have:

```python
# A simplified view of the registry structure

PRIMITIVE_REGISTRY = {
    ("tex", "def"): (DefScan, execute_def),
    ("tex", "let"): (LetScan, execute_let),
    ("tex", "\hbox"): (BoxScan, execute_hbox),
    # ... etc
}
```

- `DefScan` implements the operand grammar for `\def`;
- `execute_def` implements the assignment and scope handling.

The `EvaluationContext` holds:

- the scope stack,
- the token buffer,
- registers, and
- a runtime registry of meanings (including macros defined in the current session).

This way, when the reader processes `\def`, it doesn't need to call evaluator methods directly. It just:

- scans for the assignment, and
- adds the resulting meaning (a reference to `execute_def`, say) to the `EvaluationContext`.

The evaluator only ever interacts with the registry and the current context's meaning map.

To summarize how to keep this extensible:

| Change | Which files/modules change | Who uses it? |
|--------|-------------------------|-------------|
| A new primitive (e.g., `\futurelet`) | `primitives/definitions.py` and `catalog.py` | Scanner and handler go in the registry. |
| A new macro definition in a `.sty` file | No changes to the core. | Only affects the `EvaluationContext`'s meaning registry for that session. |
| A new kind of token for the reader (e.g., `{` inside a macro definition) | `src/reading/reader.py` | `_next_item` and other scan helpers get a new case. |
| A new evaluation mode (e.g., debug tracing) | `evaluator.py` | `EvaluationContext` gains a new state flag, and `evaluate` uses it. |

The design principle is: **the fixed, reusable parts live in the primitives and catalog, and the per-session, dynamic parts live in the `EvaluationContext`.** The scanner and evaluator only interact via the registry and the context state, so each can evolve independently.