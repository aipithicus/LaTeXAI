"""Validated upper bounds on writes, independent of expansion or execution.

An empty write set means no writes only when complete is true. Omitted summaries,
incomplete closure and unimplemented reading surfaces never establish purity.
"""
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class NameSet:
    names: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()

    def contains(self, name):
        return name in self.names or any(name.startswith(prefix) for prefix in self.prefixes)


@dataclass(frozen=True, slots=True)
class EffectSummary:
    complete: bool = True
    scope: str = "local"
    meanings: NameSet = field(default_factory=NameSet)
    options: NameSet = field(default_factory=NameSet)
    registers: tuple[str, ...] = ()
    catcodes: tuple[int, ...] = ()
    reader_parameters: tuple[str, ...] = ()
    hooks: tuple[str, ...] = ()
    loads: bool = False
    unresolved: tuple[str, ...] = ()

    @property
    def selective(self):
        # These surfaces need their own context/version and timing machinery.
        return self.complete and not (self.catcodes or self.reader_parameters or self.hooks or self.loads)

    def record(self):
        values = asdict(self)
        return {"complete": values.pop("complete"), "scope": values.pop("scope"),
                "unresolved": values.pop("unresolved"), "writes": values}

    @classmethod
    def parse(cls, raw):
        if (not isinstance(raw, dict) or set(raw) - {"complete", "scope", "writes", "unresolved"}
                or not {"complete", "scope", "writes"} <= set(raw)
                or type(raw["complete"]) is not bool or not isinstance(raw["scope"], str)
                or raw["scope"] not in {"local", "global", "unknown"}):
            raise ValueError("Effect summary requires complete, scope and writes")
        writes = raw["writes"]
        keys = {"meanings", "options", "registers", "catcodes", "reader_parameters", "hooks", "loads"}
        if not isinstance(writes, dict) or set(writes) - keys:
            raise ValueError("Unknown effect write domain")

        def strings(value):
            if not isinstance(value, (list, tuple)) or any(not isinstance(s, str) or not s for s in value):
                raise ValueError("Effect names must be nonempty strings")
            return tuple(dict.fromkeys(value))

        def names(value):
            if not isinstance(value, dict) or set(value) - {"names", "prefixes"}:
                raise ValueError("Effect names require literal names/prefixes")
            return NameSet(strings(value.get("names", [])), strings(value.get("prefixes", [])))

        catcodes = writes.get("catcodes", [])
        if not isinstance(catcodes, (list, tuple)) or any(type(c) is not int or not 0 <= c <= 0x10ffff for c in catcodes):
            raise ValueError("Catcode writes name Unicode character numbers")
        loads = writes.get("loads", False)
        if type(loads) is not bool:
            raise ValueError("Load-state writes must be boolean")
        unresolved = strings(raw.get("unresolved", []))
        if raw["complete"] and unresolved:
            raise ValueError("An unresolved effect closure cannot be complete")
        return cls(raw["complete"], raw["scope"], names(writes.get("meanings", {})),
                   names(writes.get("options", {})), strings(writes.get("registers", [])), tuple(catcodes),
                   strings(writes.get("reader_parameters", [])), strings(writes.get("hooks", [])), loads, unresolved)

    def union(self, other):
        def merge(a, b):
            return tuple(dict.fromkeys((*a, *b)))
        def names(a, b):
            return NameSet(merge(a.names, b.names), merge(a.prefixes, b.prefixes))
        scope = max((self.scope, other.scope), key=("local", "global", "unknown").index)
        return EffectSummary(self.complete and other.complete, scope, names(self.meanings, other.meanings),
            names(self.options, other.options), merge(self.registers, other.registers),
            merge(self.catcodes, other.catcodes), merge(self.reader_parameters, other.reader_parameters),
            merge(self.hooks, other.hooks), self.loads or other.loads, merge(self.unresolved, other.unresolved))

    @classmethod
    def unknown(cls, reason):
        return cls(complete=False, scope="unknown", unresolved=(reason,))
