"""Load reusable binding declarations and compiled mouth knowledge once.

The resolver treats catalog data as read-only. Activation and lexical state belong
exclusively to document-local resolvers and reading contexts.
"""
from __future__ import annotations
from pathlib import Path
import re
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
        binding_ids = engine_ids | {f"packages/{name}" for name in self.package_bindings}
        for tier, bindings in (("engine", self.engine_bindings), ("packages", self.package_bindings)):
            for name, data in bindings.items():
                origin, reading = f"{tier}/{name}", data["reading"]
                requires = data["identity"].get("requires_engine")
                if requires is not None and (not isinstance(requires, str) or requires not in engine_ids):
                    raise ProfileError(f"{origin}: unknown required engine identity {requires!r}")
                self.lexical_layers[origin] = compile_layer(reading.get("lexical_mode", {}), origin)
                for factory in reading.get("factories", []):
                    if (factory.get("family") == "environment_factory"
                            and factory["metadata"]["base_binding"] not in binding_ids):
                        raise ProfileError(f"{origin}: unknown factory base binding")
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
                    or spec["status"] not in ("context_effect", "scanner", "deferred")
                    or not isinstance(spec["description"], str) or not spec["description"]):
                raise ProfileError(f"{self.handlers_path}: invalid handler {name!r}")
        return handlers

    def _validate_reading(self, reading: dict[str, Any], path: Path) -> None:
        if "package_input_catcodes" in reading:
            assignments = reading["package_input_catcodes"]
            if (not isinstance(assignments, dict) or any(not isinstance(c, str) or len(c) != 1
                    or type(n) is not int or not 0 <= n <= 15 for c, n in assignments.items())):
                raise ProfileError(f"{path}: invalid package input catcodes")
        if "baseline_classes" in reading:
            names = reading["baseline_classes"]
            if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n for n in names):
                raise ProfileError(f"{path}: invalid baseline class inventory")
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
                if section == "conditionals":
                    role = spec.get("role")
                    fields = {"name", "role", "evaluation"} if role == "opener" else {"name", "role"}
                    if (set(spec) != fields
                            or role not in ("opener", "alternative", "case_alternative", "terminator")
                            or (role == "opener" and spec.get("evaluation") not in
                                ("always_true", "always_false", "deferred"))):
                        raise ProfileError(f"{path}: {name} requires a conditional role and opener-only evaluation")
                grammar = spec.get("grammar", {})
                if not isinstance(grammar, dict):
                    raise ProfileError(f"{path}: {name} grammar must be a mapping")
                if "handler" in grammar:
                    handler = grammar["handler"]
                    if not isinstance(handler, str) or handler not in self.reading_handlers:
                        raise ProfileError(f"{path}: unknown grammar handler {handler!r} for {name}")
                if grammar.get("handler") == "physical_line_literal":
                    if (set(grammar) - {"handler", "arity", "body_start"} or grammar.get("arity") != 0
                            or grammar.get("body_start", "after_header") not in {"after_header", "next_physical_line"}):
                        raise ProfileError(f"{path}: invalid physical-line literal grammar for {name}")
                if spec.get("family") == "stored_definition":
                    if (set(grammar) != {"handler", "expansion"}
                            or grammar.get("handler") != "primitive_definition"
                            or grammar.get("expansion") not in ("none", "full")
                            or spec.get("scope") not in ("local", "global")):
                        raise ProfileError(f"{path}: {name} requires a primitive definition grammar, expansion and scope")
                if spec.get("family") == "conditional_factory":
                    setters = grammar.get("setters")
                    if (set(grammar) != {"handler", "target_prefix", "initial", "setters"}
                            or grammar.get("handler") != "boolean_declaration"
                            or spec.get("scope") != "local"
                            or not isinstance(grammar.get("target_prefix"), str) or not grammar["target_prefix"]
                            or not isinstance(grammar.get("initial"), str) or not grammar["initial"].startswith("\\")
                            or len(grammar["initial"]) < 2
                            or not isinstance(setters, dict) or not setters
                            or any(not isinstance(suffix, str) or not suffix
                                   or not isinstance(source, str) or not source.startswith("\\") or len(source) < 2
                                   for suffix, source in setters.items())):
                        raise ProfileError(f"{path}: {name} requires a local boolean declaration recipe")
                if spec.get("action") == "assign_catcode_dynamic":
                    if grammar != {"handler": "literal_catcode_assignment"} or spec.get("scope") != "local":
                        raise ProfileError(f"{path}: {name} requires the local literal assignment scanner")
                if spec.get("family") in ("source_command", "structural_environment", "environment_factory", "option_control"):
                    if not isinstance(spec.get("metadata", {}), dict):
                        raise ProfileError(f"{path}: {name} metadata must be a mapping")
                    arguments = grammar.get("arguments")
                    allowed = {"handler", "arguments"}
                    if spec.get("family") == "option_control" and "starred_arguments" in grammar:
                        allowed.add("starred_arguments")
                    if (set(grammar) != allowed or grammar.get("handler") != "source_arguments"
                            or not isinstance(arguments, list)):
                        raise ProfileError(f"{path}: {name} requires a source_arguments grammar")
                    arg_names = set()
                    for arg in arguments:
                        if (not isinstance(arg, dict) or set(arg) != {"name", "kind"}
                                or not isinstance(arg.get("name"), str) or not arg["name"]
                                or arg["name"] in arg_names or arg.get("kind") not in ("braced", "optional", "star", "filename")):
                            raise ProfileError(f"{path}: invalid source argument for {name}")
                        arg_names.add(arg["name"])
                    if spec.get("family") in ("source_command", "environment_factory", "option_control") and spec.get("action") not in self.reading_handlers:
                        raise ProfileError(f"{path}: unknown source command action for {name}")
                    if spec.get("action") == "citation":
                        if {"name": "keys", "kind": "braced"} not in arguments:
                            raise ProfileError(f"{path}: {name} citation requires braced keys")
                        wildcard = spec.get("metadata", {}).get("allow_wildcard", False)
                        if type(wildcard) is not bool:
                            raise ProfileError(f"{path}: {name} allow_wildcard must be boolean")
                    if spec.get("action") == "pass_options":
                        if (arguments != [{"name": "options", "kind": "braced"}, {"name": "name", "kind": "braced"}]
                                or spec.get("metadata") not in ({"target_kind": "package"}, {"target_kind": "class"})):
                            raise ProfileError(f"{path}: {name} requires literal forwarding arguments and a target kind")
                    if spec.get("family") == "environment_factory":
                        self._validate_factory(spec, arg_names, path)
                    if spec.get("family") == "option_control":
                        self._validate_options(spec, path)
                if section in ("catcode_mutators", "grouping", "inclusions"):
                    action = spec.get("behavior" if section == "inclusions" else "action")
                    if not isinstance(action, str) or action not in self.reading_handlers:
                        raise ProfileError(f"{path}: unknown reading handler {action!r} for {name}")
                if section == "grouping":
                    state = spec.get("state_management", {})
                    if not isinstance(state, dict) or state.get("group_kind") not in ("simple", "semi_simple"):
                        raise ProfileError(f"{path}: {name} requires a simple or semi_simple group_kind")
                if "profile" in spec:
                    profile = spec["profile"]
                    if not isinstance(profile, str):
                        raise ProfileError(f"{path}: {name} profile must be a name")
                    self.mouth.profile(profile)

    @staticmethod
    def _validate_options(spec, path):
        braced = lambda name: {"name": name, "kind": "braced"}
        shapes = {
            "declare_option": ([braced("name"), braced("body")], [braced("body")]),
            "process_options": ([], []),
            "execute_options": ([braced("options")], None),
        }
        shape = shapes.get(spec.get("action"))
        grammar, metadata = spec["grammar"], spec.get("metadata", {})
        if (shape is None or grammar["arguments"] != shape[0]
                or grammar.get("starred_arguments") != shape[1]
                or (shape[1] is None and "starred_arguments" in grammar)):
            raise ProfileError(f"{path}: invalid option-control argument recipe")
        if spec["action"] == "process_options":
            if (set(metadata) != {"order", "starred_order"}
                    or any(v not in {"declaration", "request"} for v in metadata.values())):
                raise ProfileError(f"{path}: option processing requires declared ordering rules")
        elif metadata:
            raise ProfileError(f"{path}: unexpected option-control metadata")

    @staticmethod
    def _validate_factory(spec, arguments, path):
        recipe = spec.get("metadata", {})
        required = {"name_argument", "base_binding", "variants", "terminator"}
        allowed = required | {"base", "base_argument", "options_argument", "classification"}
        def fail():
            raise ProfileError(f"{path}: invalid environment factory recipe for {spec.get('command', spec.get('name'))}")
        if (spec.get("action") != "define_environment" or not required <= recipe.keys()
                or set(recipe) - allowed or ("base" in recipe) == ("base_argument" in recipe)):
            fail()
        for key in ("name_argument", "base_argument", "options_argument"):
            if key in recipe and (not isinstance(recipe[key], str) or recipe[key] not in arguments):
                fail()
        if not isinstance(recipe["base_binding"], str) or not recipe["base_binding"]:
            fail()
        if "base" in recipe and (not isinstance(recipe["base"], str) or not recipe["base"]):
            fail()
        variants = recipe["variants"]
        if not isinstance(variants, list) or not variants:
            fail()
        suffixes = set()
        for variant in variants:
            if (not isinstance(variant, dict) or set(variant) != {"suffix", "options"}
                    or not isinstance(variant["suffix"], str) or not isinstance(variant["options"], dict)
                    or variant["suffix"] in suffixes):
                fail()
            suffixes.add(variant["suffix"])
        term = recipe["terminator"]
        if (not isinstance(term, dict) or set(term) != {"exact_string", "regex_pattern"}
                or any(not isinstance(v, str) or "{name}" not in v for v in term.values())):
            fail()
        try:
            exact = term["exact_string"].format(name="example+*")
            pattern = term["regex_pattern"].format(name=re.escape("example+*"))
            if re.fullmatch(pattern, exact) is None:
                fail()
        except (KeyError, ValueError, re.error):
            fail()
        if "classification" in recipe:
            category = recipe["classification"]
            if (not isinstance(category, dict) or set(category) != {"category", "semantic_role"}
                    or category["category"] not in {"editorial_comment_block", "transparent_block"}
                    or not isinstance(category["semantic_role"], str) or not category["semantic_role"]):
                fail()
