"""Load reusable binding declarations and compiled mouth knowledge once.

The resolver treats catalog data as read-only. Activation and lexical state belong
exclusively to document-local resolvers and reading contexts.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from ..yaml_io import load_mapping
from ..reading.character_rules import CatcodeLayer, ProfileError, compile_layer
from ..reading.mouth_profiles import MouthProfiles

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
BINDINGS_DIR = _PROJECT_ROOT / "bindings"
PROFILES_DIR = _PROJECT_ROOT / "profiles"


class BindingCatalog:
    """Loaded knowledge reusable across multiple documents, without activation state."""

    def __init__(self, bindings_dir: Path | None = None, profiles_dir: Path | None = None):
        self.bindings_dir = bindings_dir or BINDINGS_DIR
        self.profiles_dir = profiles_dir or PROFILES_DIR
        self.profiles: dict[str, dict[str, Any]] = {}
        self.engine_bindings: dict[str, dict[str, Any]] = {}
        self.package_bindings: dict[str, dict[str, Any]] = {}
        self.lexical_layers: dict[str, CatcodeLayer] = {}
        self._load_all()

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        return load_mapping(path, error_type=ProfileError)

    def _load_all(self) -> None:
        self.mouth = MouthProfiles(self.profiles_dir / "mouth")
        self.profiles = self.mouth.profiles
        self.operation_registries = self.mouth.registries
        for p in sorted((self.bindings_dir / "engine").glob("*.yaml")):
            self.engine_bindings[p.stem] = self._load_yaml(p)
        for p in sorted((self.bindings_dir / "packages").glob("*.yaml")):
            data = self._load_yaml(p)
            self.package_bindings[data["identity"]["package"]] = data
        for tier, bindings in (("engine", self.engine_bindings), ("packages", self.package_bindings)):
            for name, data in bindings.items():
                origin, reading = f"{tier}/{name}", data["reading"]
                self.lexical_layers[origin] = compile_layer(reading.get("lexical_mode", {}), origin)
                for section in ("environments", "environment_overrides", "commands", "command_overrides"):
                    for spec in reading.get(section, []):
                        if "profile" in spec:
                            self.mouth.profile(spec["profile"])
                            key = f"{origin}/{spec['name']}"
                            self.lexical_layers[key] = compile_layer(spec.get("lexical_mode", {}), key)
