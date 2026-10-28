"""Select an initial primitive environment; implementations live in the catalog.

These are deliberately partial environments. A missing implementation does not
establish that an arbitrary name is undefined. Explicit exclusions do.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
from types import MappingProxyType

from .primitive import DefinitionSpec, PrimitiveMeaning
from ..reading.contracts import ConditionalRule, UndefinedMeaning
from ..yaml_io import load_mapping, validate_resource_identity


def _common():
    result = {
        "let": PrimitiveMeaning("meaning.assign"),
        "relax": PrimitiveMeaning("execution.relax"),
        "noexpand": PrimitiveMeaning("expansion.noexpand"),
        "expandafter": PrimitiveMeaning("expansion.expand_after"),
        "csname": PrimitiveMeaning("name.construct"),
        "endcsname": PrimitiveMeaning("name.end"),
        **{name: PrimitiveMeaning("assignment.prefix", name)
           for name in ("global", "long", "outer", "protected")},
        "globaldefs": PrimitiveMeaning("execution.unsupported", "globaldefs"),
        "catcode": PrimitiveMeaning("reading.assign_catcode"),
        "chardef": PrimitiveMeaning("meaning.define_character_code"),
        "begingroup": PrimitiveMeaning("scope.begin", "semi_simple"),
        "endgroup": PrimitiveMeaning("scope.end", "semi_simple"),
        **{name: PrimitiveMeaning("definition.store", DefinitionSpec(global_, expanded))
           for name, global_, expanded in (("def", False, False), ("gdef", True, False),
                                           ("edef", False, True), ("xdef", True, True))},
        **{name: PrimitiveMeaning("parameter.assign_integer", name)
           for name in ("widowpenalty", "clubpenalty")},
    }
    rules = {
        "iftrue": ConditionalRule("opener", "always_true", 0),
        "iffalse": ConditionalRule("opener", "always_false", 0),
        "if": ConditionalRule("opener", "deferred", 2, "character_equal"),
        "ifcat": ConditionalRule("opener", "deferred", 2, "category_equal"),
        "ifx": ConditionalRule("opener", "deferred", 2, "meaning_equal"),
        "ifdefined": ConditionalRule("opener", "deferred", 1),
        **{name: ConditionalRule("opener", "deferred") for name in
           ("ifnum", "ifdim", "ifodd", "ifvoid", "ifhbox", "ifvbox", "ifeof", "ifcase", "ifcsname")},
        **{name: ConditionalRule("opener", "deferred", 0) for name in
           ("ifvmode", "ifhmode", "ifmmode", "ifinner")},
        "else": ConditionalRule("alternative"),
        "or": ConditionalRule("case_alternative"),
        "fi": ConditionalRule("terminator"),
    }
    result.update((name, PrimitiveMeaning("conditional.route", rule)) for name, rule in rules.items())
    return result


COMMON_PRIMITIVES = MappingProxyType(_common())
EXTENSIONS = MappingProxyType({
    "expanded": PrimitiveMeaning("expansion.expanded"),
    "pdfoutput": PrimitiveMeaning("parameter.assign_integer", "pdfoutput"),
})


@dataclass(frozen=True, slots=True)
class OracleContract:
    language: str
    shared_extensions: str
    rendering: str
    output: str
    qualification: str
    note: str


@dataclass(frozen=True, slots=True)
class EngineProfile:
    name: str
    extensions: frozenset[str] = frozenset()
    absent: frozenset[str] = frozenset()
    capture_integer_setup: frozenset[str] = frozenset()
    oracle: OracleContract | None = None
    source_sha256: str | None = None

    def __post_init__(self):
        for field in ("extensions", "absent", "capture_integer_setup"):
            object.__setattr__(self, field, frozenset(getattr(self, field)))
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Engine profile requires a name")
        if self.extensions - EXTENSIONS.keys():
            raise ValueError("Unknown primitive extension")
        if self.absent & (COMMON_PRIMITIVES.keys() | self.extensions):
            raise ValueError("An exposed primitive cannot also be absent")
        if (self.capture_integer_setup - self.absent
                or any(EXTENSIONS.get(name) is None or EXTENSIONS[name].operation != "parameter.assign_integer"
                       for name in self.capture_integer_setup)):
            raise ValueError("Preparation setup capture requires an explicitly absent integer parameter")

    def lookup(self, name):
        if name in COMMON_PRIMITIVES:
            return COMMON_PRIMITIVES[name]
        if name in self.extensions:
            return EXTENSIONS[name]
        if name in self.absent:
            return UndefinedMeaning(None, format_origin=f"engine profile: {self.name}")
        return None

    def record(self):
        from dataclasses import asdict
        return {"name": self.name, "base": "etex", "extensions": sorted(self.extensions),
                "absent": sorted(self.absent), "capture_integer_setup": sorted(self.capture_integer_setup),
                "oracle": asdict(self.oracle) if self.oracle else None, "source_sha256": self.source_sha256}


def load_profile(path):
    data = load_mapping(path)
    if (set(data) != {"schema", "identity", "description", "base", "extensions", "absent", "preparation", "oracle", "targets"}
            or data["schema"] != "pytexml-engine-profile/1" or data["base"] != "etex"):
        raise ValueError(f"{path}: unsupported engine profile")
    name = validate_resource_identity(data, path)
    if not isinstance(data["description"], str):
        raise ValueError(f"{path}: invalid profile identity")
    if set(data["preparation"]) != {"capture_integer_setup"}:
        raise ValueError(f"{path}: unsupported preparation contract")
    lists = [data["extensions"], data["absent"], data["preparation"]["capture_integer_setup"]]
    if any(not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values)
           or len(values) != len(set(values)) for values in lists):
        raise ValueError(f"{path}: profile vocabularies must be unique nonempty names")
    oracle = OracleContract(**data["oracle"])
    if (any(name not in {"etex", "pdftex"} for name in (oracle.language, oracle.shared_extensions, oracle.rendering))
            or oracle.output not in {"pdf", "dvi"} or oracle.qualification != "capability_scoped"):
        raise ValueError(f"{path}: unsupported oracle contract")
    if set(data["targets"]) != {"expl3", "note"} or data["targets"]["expl3"] != "partial":
        raise ValueError(f"{path}: profile must report its partial implementation")
    return EngineProfile(name, *lists, oracle, hashlib.sha256(path.read_bytes()).hexdigest())


PROFILE_ROOT = Path(__file__).resolve().parents[2] / "resources" / "engine_profiles"
PROFILES = MappingProxyType({name: load_profile(PROFILE_ROOT / (name + ".yaml")) for name in ("etex", "pdftex")})


def engine_profile(value="etex"):
    return value if isinstance(value, EngineProfile) else PROFILES[value]
