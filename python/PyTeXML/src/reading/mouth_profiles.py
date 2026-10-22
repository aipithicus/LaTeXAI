"""Load and validate mouth configuration once, outside the incremental reader."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from typing import Any
from ..yaml_io import load_mapping
from .character_rules import CatcodeLayer, ProfileError, compile_layer
from .contracts import MouthBaseline


def overlay(*layers: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for layer in layers:
        for key, value in layer.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = overlay(result[key], value)
            else:
                result[key] = deepcopy(value)
    return result


class MouthProfiles:
    """Resolved metadata and immutable regex layers, with no legacy-file fallback."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.profiles: dict[str, dict[str, Any]] = {}
        self.registries: dict[str, dict[str, Any]] = {}
        self._resolved: dict[str, dict[str, Any]] = {}
        self._layers: dict[str, tuple[CatcodeLayer, ...]] = {}
        if not directory.is_dir():
            raise ProfileError(f"Missing mouth profile directory: {directory}")
        for path in sorted(directory.glob("*.yaml")):
            data = load_mapping(path, error_type=ProfileError)
            identity = data.get("identity", {})
            if not isinstance(identity, dict):
                raise ProfileError(f"{path}: identity must be a mapping")
            registry = identity.get("registry")
            name = registry if registry is not None else identity.get("name")
            target = self.registries if registry is not None else self.profiles
            if not isinstance(name, str) or not name or name in target:
                raise ProfileError(f"{path}: missing or duplicate identity {name!r}")
            target[name] = data
        if not self.profiles:
            raise ProfileError(f"No mouth profiles found in {directory}")
        for name in self.profiles:
            self._resolve(name, ())
            if self._resolved[name]["identity"]["category"] == "baseline_catcodes":
                self.baseline(name)

    def _resolve(self, name: str, chain: tuple[str, ...]) -> None:
        if name in chain:
            raise ProfileError(f"Cyclic mouth inheritance: {' -> '.join(chain + (name,))}")
        if name in self._resolved:
            return
        if name not in self.profiles:
            raise ProfileError(f"Unknown mouth profile {name!r} referenced by {chain}")
        own = self.profiles[name]
        allowed = {"identity", "inherits", "family", "terminator_pattern", "comment_char",
                   "escape_char", "preserve_whitespace", "allow_nesting", "multiline_allowed",
                   "span_classification", "delimiter_mode", "has_star_variant", "group_delimiters",
                   "interpolations_allowed", "interpolation_mode", "lexical_mode"}
        if set(own) - allowed:
            raise ProfileError(f"{name}: unknown profile keys {sorted(set(own) - allowed)}")
        kind = own.get("identity", {}).get("category")
        if kind not in {"baseline_catcodes", "inline_literal", "block_literal"}:
            raise ProfileError(f"{name}: unknown mouth profile category {kind!r}")
        parent = own.get("inherits")
        inherited, layers = {}, ()
        if parent is not None:
            if not isinstance(parent, str):
                raise ProfileError(f"{name}: inherits must name a mouth profile")
            self._resolve(parent, chain + (name,))
            inherited, layers = self._resolved[parent], self._layers[parent]
        lexical = own.get("lexical_mode", {})
        layer = compile_layer(lexical, f"mouth/{name}")
        if kind != "baseline_catcodes" and "default" in lexical:
            raise ProfileError(f"{name}: a literal profile cannot replace the default catcode")
        self._resolved[name] = overlay(inherited, own)
        # Inheritance composes effects in order, rather than replacing a parent's
        # regex list or allowing old explicit assignments to beat a child's rules.
        self._layers[name] = layers + ((layer,) if layer.rules or layer.assignments else ())

    def profile(self, name: str) -> dict[str, Any]:
        if name not in self._resolved:
            raise ProfileError(f"Unknown mouth profile {name!r}")
        return deepcopy(self._resolved[name])

    def layers(self, name: str) -> tuple[CatcodeLayer, ...]:
        if name not in self._layers:
            raise ProfileError(f"Unknown mouth profile {name!r}")
        return self._layers[name]

    def baseline(self, name: str) -> MouthBaseline:
        profile = self.profile(name)
        if profile["identity"]["category"] != "baseline_catcodes":
            raise ProfileError(f"{name}: a baseline_catcodes profile is required")
        lex = profile.get("lexical_mode", {})
        if "default" not in lex or "endlinechar" not in lex.get("reader_parameters", {}):
            raise ProfileError(f"{name}: baseline requires default and endlinechar")
        return MouthBaseline(name, lex["default"], lex["reader_parameters"]["endlinechar"],
                             self.layers(name))
