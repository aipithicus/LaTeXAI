"""Captured option declarations and bounded selection; execution is dispatcher's job.

Selection follows latex2e base/ltclass.dtx ProcessOptions/ExecuteOptions. This
models resolved legacy option lists, not key/value frameworks.
"""
from dataclasses import dataclass, field

from .contracts import ReadingIssue, ScannedArgument
from .spans import SourceSpan
from .tex_reader import CatCode, Token


@dataclass(frozen=True, slots=True)
class Option:
    name: str
    tokens: tuple[Token, ...]
    anchor: SourceSpan


def option_items(argument: ScannedArgument | None) -> tuple[Option, ...]:
    if argument is None:
        return ()
    argument.literal()
    items, current = [], []
    for token in (*argument.tokens, None):
        if token is None or token.value == "," and token.catcode == CatCode.OTHER:
            if current:
                items.append(Option("".join(t.value for t in current), tuple(current), argument.span))
                current = []
        elif token.catcode != CatCode.SPACE:
            if token.value == ",":
                raise ReadingIssue("option_syntax", "Option separators require category-12 comma tokens")
            current.append(token)
    return tuple(items)


def option_names(argument: ScannedArgument | None) -> tuple[str, ...]:
    return tuple(option.name for option in option_items(argument))


@dataclass(frozen=True, slots=True)
class OptionBody:
    argument: ScannedArgument
    text: str
    option: Option | None = None


@dataclass
class OptionScope:
    """One package/class load, shared with its ordinary input files only."""
    name: str
    local: tuple[Option, ...] = ()
    global_options: tuple[Option, ...] = ()
    is_class: bool = False
    depth: int = 0
    declarations: dict[str, OptionBody] = field(default_factory=dict)
    default: OptionBody | None = None
    processed: bool = False
    uncertain: SourceSpan | None = None

    def copy(self):
        return OptionScope(self.name, self.local, self.global_options, self.is_class,
                           self.depth, dict(self.declarations), self.default, self.processed, self.uncertain)

    def require_known(self):
        if self.uncertain is not None:
            raise ReadingIssue("uncertain_options", "Unexecuted source may have changed option state at "
                               f"{self.uncertain.basis.source_id}:{self.uncertain.start}", causes=(self.uncertain,))

    def declare(self, name, body):
        if self.processed:
            raise ReadingIssue("option_lifecycle", "Declarations after ProcessOptions need further resolution")
        if name is None:
            self.default = body
        else:
            if not name or "," in name:
                raise ReadingIssue("option_name", "An option declaration needs one literal name")
            self.declarations[name] = body

    def defaults(self, options):
        self.require_known()
        if self.processed:
            raise ReadingIssue("option_lifecycle", "ExecuteOptions after ProcessOptions is unsupported")
        # ExecuteOptions ignores undeclared names; it does not use DeclareOption*.
        return [(option, self.declarations[option.name]) for option in options if option.name in self.declarations]

    def plan(self, order):
        self.require_known()
        if self.processed:
            raise ReadingIssue("option_lifecycle", "Repeated ProcessOptions needs further resolution")
        globals_ = () if self.is_class else self.global_options
        if order == "declaration":
            requested = {option.name for option in globals_ + self.local}
            options = [body.option for name, body in self.declarations.items() if name in requested]
            options.extend(option for option in self.local if option.name not in self.declarations)
        elif order == "request":
            # Starred processing executes recognized globals first, then locals
            # in request order (including the default action for unknown locals).
            options = [option for option in globals_ if option.name in self.declarations] + list(self.local)
        else:
            raise ReadingIssue("option_order", f"Unsupported option order {order!r}")
        plan, used = [], set()
        for option in options:
            name = option.name
            if name in self.declarations:
                if name not in used:
                    plan.append((option, self.declarations[name]))
                    used.add(name)
            elif self.default is not None:
                plan.append((option, self.default))
            elif not self.is_class:
                raise ReadingIssue("unknown_option", f"No declared/default action for {name!r} in {self.name}")
            # A class's undeclared options remain available to later packages.
        return plan
