"""Captured option declarations and bounded selection; execution is dispatcher's job.

Selection follows latex2e base/ltclass.dtx ProcessOptions/ExecuteOptions. This
models literal legacy option lists, not key/value frameworks or macro expansion.
"""
from dataclasses import dataclass, field

from .contracts import ReadingIssue, ScannedArgument
from .spans import SourceSpan


def option_names(argument: ScannedArgument | None) -> tuple[str, ...]:
    if argument is None:
        return ()
    # The legacy kernel removes space tokens from these literal option lists.
    return tuple(name for name in argument.literal().replace(" ", "").split(",") if name)


@dataclass(frozen=True, slots=True)
class OptionBody:
    argument: ScannedArgument
    text: str


@dataclass
class OptionScope:
    """One package/class load, shared with its ordinary input files only."""
    name: str
    local: tuple[str, ...] = ()
    global_options: tuple[str, ...] = ()
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
                               f"{self.uncertain.basis.source_id}:{self.uncertain.start}")

    def declare(self, name, body):
        if self.processed:
            raise ReadingIssue("option_lifecycle", "Declarations after ProcessOptions need further resolution")
        if name is None:
            self.default = body
        else:
            if not name or "," in name:
                raise ReadingIssue("option_name", "An option declaration needs one literal name")
            self.declarations[name] = body

    def defaults(self, names):
        self.require_known()
        if self.processed:
            raise ReadingIssue("option_lifecycle", "ExecuteOptions after ProcessOptions is unsupported")
        # ExecuteOptions ignores undeclared names; it does not use DeclareOption*.
        return [(name, self.declarations[name]) for name in names if name in self.declarations]

    def plan(self, order):
        self.require_known()
        if self.processed:
            raise ReadingIssue("option_lifecycle", "Repeated ProcessOptions needs further resolution")
        globals_ = () if self.is_class else self.global_options
        if order == "declaration":
            requested = set(globals_ + self.local)
            names = [name for name in self.declarations if name in requested]
            names.extend(name for name in self.local if name not in self.declarations)
        elif order == "request":
            # Starred processing executes recognized globals first, then locals
            # in request order (including the default action for unknown locals).
            names = [name for name in globals_ if name in self.declarations] + list(self.local)
        else:
            raise ReadingIssue("option_order", f"Unsupported option order {order!r}")
        plan, used = [], set()
        for name in names:
            if name in self.declarations:
                if name not in used:
                    plan.append((name, self.declarations[name]))
                    used.add(name)
            elif self.default is not None:
                plan.append((name, self.default))
            elif not self.is_class:
                raise ReadingIssue("unknown_option", f"No declared/default action for {name!r} in {self.name}")
            # A class's undeclared options remain available to later packages.
        return plan
