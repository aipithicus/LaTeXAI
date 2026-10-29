"""Select an initial primitive environment; implementations live in the catalog.

These are deliberately partial environments. A missing implementation does not
establish that an arbitrary name is undefined. Explicit exclusions do.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from types import MappingProxyType

from .catalog import COMMON_PRIMITIVES, EXTENSIONS
from .primitive import PrimitiveMeaning
from ..reading.contracts import UndefinedMeaning
from ..yaml_io import load_mapping, validate_resource_identity


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
    primitives: Mapping[str, PrimitiveMeaning | UndefinedMeaning] = field(init=False, repr=False, compare=False, hash=False)

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
        primitives = dict(COMMON_PRIMITIVES)
        primitives.update((name, EXTENSIONS[name]) for name in self.extensions)
        primitives.update((name, UndefinedMeaning(None, format_origin=f"engine profile: {self.name}"))
                          for name in self.absent)
        object.__setattr__(self, "primitives", MappingProxyType(primitives))

    def lookup(self, name):
        return self.primitives.get(name)

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
