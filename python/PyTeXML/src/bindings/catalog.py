"""Load reusable binding declarations and compiled mouth knowledge once.

The resolver treats catalog data as read-only. Activation and lexical state belong
exclusively to document-local resolvers and reading contexts.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..yaml_io import load_mapping, validate_resource_identity
from ..reading.character_rules import CatcodeLayer, ProfileError, compile_layer
from ..reading.mouth_profiles import MouthProfiles

RESOURCE_DIR = Path(__file__).resolve().parents[2] / "resources"
BINDINGS_DIR = RESOURCE_DIR / "bindings"
PROFILES_DIR = RESOURCE_DIR / "profiles"
HANDLERS_PATH = RESOURCE_DIR / "registries" / "reading_handlers.yaml"


class BindingCatalog:
    """Loaded knowledge reusable across multiple documents, without activation state."""

    def __init__(self, bindings_dir: Path | None = None, profiles_dir: Path | None = None,
                 handlers_path: Path | None = None):
        self.bindings_dir = bindings_dir or BINDINGS_DIR
        self.profiles_dir = profiles_dir or PROFILES_DIR
        self.handlers_path = handlers_path or HANDLERS_PATH
        self.profiles: dict[str, dict[str, Any]] = {}
        self.engine_bindings: dict[str, dict[str, Any]] = {}
        self.package_bindings: dict[str, dict[str, Any]] = {}
        self.lexical_layers: dict[str, CatcodeLayer] = {}
        self._load_all()

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        return load_mapping(path, error_type=ProfileError)

    def _load_all(self) -> None:
        self.reading_handlers = self._load_handlers()
        self.mouth = MouthProfiles(self.profiles_dir / "mouth")
        self.profiles = self.mouth.profiles
        for tier, target in (("engine", self.engine_bindings), ("packages", self.package_bindings)):
            directory = self.bindings_dir / tier
            identities = set()
            if not directory.is_dir():
                raise ProfileError(f"Missing binding directory: {directory}")
            for path in sorted(directory.glob("*.yaml")):
                data = self._load_yaml(path)
                identity, reading = data.get("identity"), data.get("reading")
                if not isinstance(identity, dict) or not isinstance(reading, dict):
                    raise ProfileError(f"{path}: identity and reading must be mappings")
                name = validate_resource_identity(data, path,
                    key="name" if tier == "engine" else "package", error_type=ProfileError)
                if name in identities:
                    raise ProfileError(f"{path}: duplicate binding identity {name!r}")
                identities.add(name)
                self._validate_reading(reading, path)
                target[name] = data
        engine_ids = {f"engine/{name}" for name in self.engine_bindings}
        for tier, bindings in (("engine", self.engine_bindings), ("packages", self.package_bindings)):
            for name, data in bindings.items():
                origin, reading = f"{tier}/{name}", data["reading"]
                requires = data["identity"].get("requires_engine")
                if requires is not None and (not isinstance(requires, str) or requires not in engine_ids):
                    raise ProfileError(f"{origin}: unknown required engine identity {requires!r}")
                self.lexical_layers[origin] = compile_layer(reading.get("lexical_mode", {}), origin)
                for section in ("environments", "environment_overrides", "commands", "command_overrides"):
                    for spec in reading.get(section, []):
                        if "profile" in spec:
                            self.mouth.profile(spec["profile"])
                            key = f"{origin}/{spec['name']}"
                            self.lexical_layers[key] = compile_layer(spec.get("lexical_mode", {}), key)

    def _load_handlers(self) -> dict[str, dict[str, str]]:
        data = self._load_yaml(self.handlers_path)
        validate_resource_identity(data, self.handlers_path, key="registry", error_type=ProfileError)
        identity, handlers = data.get("identity"), data.get("handlers")
        if (set(data) != {"identity", "handlers"} or not isinstance(identity, dict)
                or identity.get("registry") != "reading_handlers"
                or set(identity) != {"registry", "description"}
                or not isinstance(identity.get("description"), str)
                or not isinstance(handlers, dict) or not handlers):
            raise ProfileError(f"{self.handlers_path}: expected the reading_handlers registry")
        for name, spec in handlers.items():
            if (not isinstance(name, str) or not name or not isinstance(spec, dict)
                    or set(spec) != {"status", "description"}
                    or spec["status"] not in ("context_effect", "deferred")
                    or not isinstance(spec["description"], str) or not spec["description"]):
                raise ProfileError(f"{self.handlers_path}: invalid handler {name!r}")
        return handlers

    def _validate_reading(self, reading: dict[str, Any], path: Path) -> None:
        # Validate the structural surface consumed today, not a speculative schema
        # for future interpretation. Override sections may intentionally reuse names.
        for section in ("catcode_mutators", "grouping", "inclusions", "conditionals",
                        "environments", "environment_overrides", "commands",
                        "command_overrides", "factories"):
            specs = reading.get(section, [])
            if not isinstance(specs, list):
                raise ProfileError(f"{path}: reading.{section} must be a list")
            names = set()
            for spec in specs:
                if not isinstance(spec, dict):
                    raise ProfileError(f"{path}: reading.{section} entries must be mappings")
                name = spec.get("name", spec.get("command"))
                if not isinstance(name, str) or not name or name in names:
                    raise ProfileError(f"{path}: missing or duplicate name in reading.{section}: {name!r}")
                names.add(name)
                if section in ("catcode_mutators", "grouping", "inclusions"):
                    action = spec.get("behavior" if section == "inclusions" else "action")
                    if not isinstance(action, str) or action not in self.reading_handlers:
                        raise ProfileError(f"{path}: unknown reading handler {action!r} for {name}")
                if "profile" in spec:
                    profile = spec["profile"]
                    if not isinstance(profile, str):
                        raise ProfileError(f"{path}: {name} profile must be a name")
                    self.mouth.profile(profile)
