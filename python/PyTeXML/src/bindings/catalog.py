"""Load reusable binding declarations and compiled mouth knowledge once.

The resolver treats catalog data as read-only. Activation and lexical state belong
exclusively to document-local resolvers and reading contexts.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
from ..yaml_io import load_mapping, overlay, validate_resource_identity
from ..reading.character_rules import CatcodeLayer, ProfileError, compile_layer
from ..reading.contracts import EffectiveReadingProfile, SpanClassification, TerminatorRule
from ..reading.mouth_profiles import MouthProfiles

RESOURCE_DIR = Path(__file__).resolve().parents[2] / "resources"
BINDINGS_DIR = RESOURCE_DIR / "bindings"
PROFILES_DIR = RESOURCE_DIR / "profiles"
HANDLERS_PATH = RESOURCE_DIR / "registries" / "reading_handlers.yaml"
COMMAND_SECTIONS = ("catcode_mutators", "grouping", "command_overrides", "commands",
                    "factories", "inclusions", "conditionals")
ENVIRONMENT_SECTIONS = ("environment_overrides", "environments")


@dataclass(frozen=True, slots=True)
class ReadingDeclaration:
    """Catalog-owned snapshot; nested mappings are never lent to a document."""
    origin: str
    section: str
    reading: dict[str, Any]
    spec: dict[str, Any]
    literal: EffectiveReadingProfile | None = None


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
        self.commands: dict[str, dict[str, tuple[ReadingDeclaration, ...]]] = {}
        self.environments: dict[str, dict[str, tuple[ReadingDeclaration, ...]]] = {}
        self.groups: dict[int, dict[str, ReadingDeclaration]] = {}
        self.literal_profiles: dict[str, dict[str, Any]] = {}
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
                origin, reading = f"{tier}/{name}", deepcopy(data["reading"])
                requires = data["identity"].get("requires_engine")
                if requires is not None and (not isinstance(requires, str) or requires not in engine_ids):
                    raise ProfileError(f"{origin}: unknown required engine identity {requires!r}")
                self.lexical_layers[origin] = compile_layer(reading.get("lexical_mode", {}), origin)
                for factory in reading.get("factories", []):
                    if (factory.get("family") == "environment_factory"
                            and factory["metadata"]["base_binding"] not in binding_ids):
                        raise ProfileError(f"{origin}: unknown factory base binding")
                for sections, index in ((COMMAND_SECTIONS, self.commands),
                                        (ENVIRONMENT_SECTIONS, self.environments)):
                    for section in sections:
                        for spec in reading.get(section, []):
                            literal = None
                            if (section in ENVIRONMENT_SECTIONS and spec.get("family") != "structural_environment"
                                    or spec.get("family") in {"inline_verbatim", "external_verbatim_file"}):
                                literal = self._compile_literal(origin, section, reading, spec)
                            declaration = ReadingDeclaration(origin, section, reading, spec, literal)
                            key = spec.get("name", spec.get("command"))
                            providers = index.setdefault(key, {})
                            providers[origin] = (*providers.get(origin, ()), declaration)
                            if section == "grouping" and spec.get("trigger") == "token_category":
                                self.groups.setdefault(spec["catcode"], {}).setdefault(origin, declaration)

    def _literal_profile(self, name: str, path: Path | str) -> dict[str, Any]:
        if not isinstance(name, str) or not name:
            raise ProfileError(f"{path}: literal profile must be a name")
        if name not in self.literal_profiles:
            profile = self.mouth.profile(name)
            if "span_classification" not in profile:
                raise ProfileError(f"{path}: {name!r} is not a literal profile")
            self.literal_profiles[name] = profile
        return self.literal_profiles[name]

    def _compile_literal(self, origin, section, reading, spec) -> EffectiveReadingProfile:
        name = spec["name"]
        contract = reading.get("option_resolution", {})
        profile_name = spec.get("profile", contract.get("default_profile"))
        defaults = self._literal_profile(profile_name, origin)
        merged = overlay(defaults, {"lexical_mode": reading.get("lexical_mode", {})}, spec)
        lex = merged.get("lexical_mode", {})
        layer = compile_layer(spec.get("lexical_mode", {}), f"{origin}/{section}/{name}")
        layers = self.mouth.layers(profile_name) + tuple(
            item for item in (self.lexical_layers[origin], layer) if item.rules or item.assignments)
        classification = merged["span_classification"]
        terminator = None
        if section in ENVIRONMENT_SECTIONS:
            raw_term = merged.get("terminator", {})
            exact = raw_term.get("exact_string", defaults.get(
                "terminator_pattern", "\\end{{{name}}}").format(name=name))
            terminator = TerminatorRule(**overlay(
                {"exact_string": exact, "regex_pattern": re.escape(exact)}, raw_term))
        grammar = deepcopy(merged.get("grammar", {}))
        for key in ("syntax", "arity", "delimiter_mode", "invalid_delimiters",
                    "multiline_allowed", "starred_variant", "visible_spaces",
                    "has_optional_arguments", "options_syntax", "allow_nesting"):
            if key in merged:
                grammar[key] = deepcopy(merged[key])
        return EffectiveReadingProfile(
            name, profile_name, binding_id=origin, catcode_layers=layers,
            reader_parameters=deepcopy(lex.get("reader_parameters", {})),
            tex_mechanics=deepcopy(lex.get("tex_mechanics", {})),
            source_capture=deepcopy(lex.get("source_capture", {})), terminator=terminator,
            span_classification=SpanClassification(
                classification.get("default_category", classification["category"]), classification["semantic_role"]),
            grammar=grammar,
            configuration=overlay(contract, reading["configuration"]) if "configuration" in reading else {})

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
        if "option_resolution" in reading:
            self._validate_literal_options(reading["option_resolution"], path)
        if "configuration" in reading:
            self._validate_configuration(reading, path)
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
                    if role == "opener" and "capture_operands" in spec:
                        fields.add("capture_operands")
                        if type(spec["capture_operands"]) is not int or spec["capture_operands"] not in (0, 2):
                            raise ProfileError(f"{path}: {name} capture_operands must be 0 or 2")
                    if role == "opener" and "predicate" in spec:
                        fields.add("predicate")
                        if (spec["predicate"] not in ("character_equal", "category_equal")
                                or spec.get("evaluation") != "deferred" or spec.get("capture_operands") != 2):
                            raise ProfileError(f"{path}: {name} predicate needs two operands and deferred fallback")
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
                if spec.get("family") in ("stored_definition", "collected_environment_definition"):
                    environment = spec.get("family") == "collected_environment_definition"
                    if grammar.get("handler") == "command_definition" or environment:
                        if (set(grammar) != {"handler", "expansion", "target_requirement", "forbidden_names", "forbidden_prefixes"}
                                or grammar.get("handler") != ("collected_environment_definition" if environment else "command_definition")
                                or grammar.get("expansion") != "none" or spec.get("scope") != "local"
                                or grammar.get("target_requirement") not in ("absent", "present")
                                or any(not isinstance(grammar.get(key), list)
                                       or any(not isinstance(value, str) or not value for value in grammar[key])
                                       for key in ("forbidden_names", "forbidden_prefixes"))):
                            raise ProfileError(f"{path}: {name} requires a local command definition recipe")
                        if environment:
                            self._validate_collector(spec.get("metadata"), path)
                    elif (set(grammar) != {"handler", "expansion"}
                          or grammar.get("handler") != "primitive_definition"
                          or grammar.get("expansion") not in ("none", "full")
                          or spec.get("scope") not in ("local", "global")):
                        raise ProfileError(f"{path}: {name} requires a primitive definition grammar, expansion and scope")
                if spec.get("family") in {"meaning_assignment", "assignment_prefix"}:
                    handler = "let_assignment" if spec["family"] == "meaning_assignment" else "assignment_prefix"
                    if grammar != {"handler": handler} or spec.get("scope") != "local":
                        raise ProfileError(f"{path}: {name} requires the bounded local {handler} recipe")
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
                if spec.get("family") in ("source_command", "structural_environment", "environment_factory", "option_control", "configuration_command"):
                    if not isinstance(spec.get("metadata", {}), dict):
                        raise ProfileError(f"{path}: {name} metadata must be a mapping")
                    arguments = grammar.get("arguments")
                    allowed = {"handler", "arguments"}
                    if spec.get("family") == "option_control" and "starred_arguments" in grammar:
                        allowed.add("starred_arguments")
                    if (set(grammar) != allowed or grammar.get("handler") != "source_arguments"
                            or not isinstance(arguments, list) or not isinstance(grammar.get("starred_arguments", []), list)):
                        raise ProfileError(f"{path}: {name} requires a source_arguments grammar")
                    arg_names = set()
                    for arg in arguments + grammar.get("starred_arguments", []):
                        if (not isinstance(arg, dict) or not {"name", "kind"} <= set(arg)
                                or set(arg) - {"name", "kind", "role", "literal_categories"}
                                or not isinstance(arg.get("name"), str) or not arg["name"]
                                or arg.get("role", "unknown") not in ("unknown", "data", "diagnostic", "stored", "branch")
                                or arg.get("kind") not in ("braced", "optional", "star", "filename", "control_sequence")):
                            raise ProfileError(f"{path}: invalid source argument for {name}")
                        categories = arg.get("literal_categories")
                        if categories is not None and (not isinstance(categories, list) or not categories
                                or any(type(c) is not int or c not in (3, 4, 6, 7, 8, 10, 11, 12) for c in categories)
                                or len(set(categories)) != len(categories)):
                            raise ProfileError(f"{path}: invalid literal categories for {name}")
                        arg_names.add(arg["name"])
                    for specs in (arguments, grammar.get("starred_arguments", [])):
                        if len({a["name"] for a in specs}) != len(specs):
                            raise ProfileError(f"{path}: duplicate source argument for {name}")
                    if spec.get("family") in ("source_command", "environment_factory", "option_control") and spec.get("action") not in self.reading_handlers:
                        raise ProfileError(f"{path}: unknown source command action for {name}")
                    if spec.get("action") == "citation":
                        if {"name": "keys", "kind": "braced"} not in arguments:
                            raise ProfileError(f"{path}: {name} citation requires braced keys")
                        wildcard = spec.get("metadata", {}).get("allow_wildcard", False)
                        if type(wildcard) is not bool:
                            raise ProfileError(f"{path}: {name} allow_wildcard must be boolean")
                    if spec.get("action") == "pass_options":
                        if ([{k: a[k] for k in ("name", "kind")} for a in arguments] != [{"name": "options", "kind": "braced"}, {"name": "name", "kind": "braced"}]
                                or spec.get("metadata") not in ({"target_kind": "package"}, {"target_kind": "class"})):
                            raise ProfileError(f"{path}: {name} requires literal forwarding arguments and a target kind")
                    if spec.get("action") == "optional_source_input":
                        if arguments != [{"name": "target", "kind": "braced", "role": "data"},
                                         {"name": "then", "kind": "braced", "role": "branch"},
                                         {"name": "else", "kind": "braced", "role": "branch"}]:
                            raise ProfileError(f"{path}: {name} requires an optional input filename and two branches")
                    if spec.get("action") == "branch_test":
                        if (spec.get("metadata") not in ({"predicate": "loaded", "kind": "package"},
                                                       {"predicate": "loaded", "kind": "class"})
                                or arguments != [{"name": "name", "kind": "braced", "role": "data"},
                                                 {"name": "then", "kind": "braced", "role": "branch"},
                                                 {"name": "else", "kind": "braced", "role": "branch"}]):
                            raise ProfileError(f"{path}: invalid loaded-branch recipe for {name}")
                    if spec.get("action") == "capture_setting":
                        metadata = spec.get("metadata", {})
                        kind = metadata.get("value_kind")
                        if (set(metadata) != {"key", "value_kind"} or kind not in ("control_sequence", "tokens")
                                or not isinstance(metadata.get("key"), str) or not metadata["key"]
                                or arguments != [{"name": "value", "kind": "control_sequence" if kind == "control_sequence" else "braced"}]):
                            raise ProfileError(f"{path}: invalid capture setting recipe for {name}")
                    if spec.get("family") == "configuration_command":
                        metadata = spec.get("metadata", {})
                        if ("configuration" not in reading
                                or spec.get("action") not in ("define_configuration", "apply_configuration")
                                or set(metadata) != {"header_catcodes", "unsupported_arguments"}
                                or not isinstance(metadata["header_catcodes"], dict)
                                or any(not isinstance(c, str) or len(c) != 1 or type(n) is not int or not 0 <= n <= 15
                                       for c, n in metadata["header_catcodes"].items())
                                or not isinstance(metadata["unsupported_arguments"], list)
                                or any(a not in arg_names for a in metadata["unsupported_arguments"])
                                or {"name": "options", "kind": "braced"} not in arguments
                                or (spec["action"] == "define_configuration" and {"name": "name", "kind": "braced"} not in arguments)):
                            raise ProfileError(f"{path}: invalid named configuration recipe for {name}")
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

    def _validate_literal_options(self, contract, path):
        fields = {"default_profile", "reading_affecting_keys", "non_reading_options", "unsupported_options_behavior"}
        if not isinstance(contract, dict) or set(contract) - fields:
            raise ProfileError(f"{path}: unknown option_resolution fields")
        if "default_profile" in contract:
            self._literal_profile(contract["default_profile"], path)
        # This is a declared invariant, not a selectable ignore/fallback policy.
        if contract.get("unsupported_options_behavior", "report_unresolved") != "report_unresolved":
            raise ProfileError(f"{path}: unsupported options must report_unresolved")
        rules, passthrough = contract.get("reading_affecting_keys", {}), contract.get("non_reading_options", [])
        if (not isinstance(rules, dict) or any(not isinstance(k, str) or not k for k in rules)
                or not isinstance(passthrough, list)
                or any(not isinstance(k, str) or not k for k in passthrough)
                or len(set(passthrough)) != len(passthrough) or set(rules) & set(passthrough)):
            raise ProfileError(f"{path}: reading and non-reading options must be distinct names")
        effects = {"assign_command_and_group_delimiters", "enable_verbatim_comment",
                   "define_interpolation_delimiters", "define_single_escape_char", "toggle_math_mode_on_dollar"}
        for key, rule in rules.items():
            if (not isinstance(rule, dict) or set(rule) - {"effect", "syntax", "profile_override", "unsupported_action"}
                    or not isinstance(rule.get("effect"), str)
                    or "syntax" in rule and not isinstance(rule["syntax"], str)):
                raise ProfileError(f"{path}: invalid literal option rule {key!r}")
            deferred = rule.get("unsupported_action") == "report_unresolved"
            if ("unsupported_action" in rule and not deferred
                    or rule["effect"] not in effects | {"dynamic_catcode_mutations"}
                    or rule["effect"] == "dynamic_catcode_mutations" and not deferred):
                raise ProfileError(f"{path}: unsupported literal option effect {key!r}")
            if "profile_override" in rule:
                self._literal_profile(rule["profile_override"], path)

    @staticmethod
    def _validate_configuration(reading, path):
        config, options = reading["configuration"], reading.get("option_resolution", {})
        expected = {"namespace", "style_key", "name_normalization", "definition_scope", "assignment_scope", "exclusive_keys", "bare_defaults"}
        if (not isinstance(config, dict) or set(config) != expected
                or any(not isinstance(config.get(k), str) or not config[k] for k in ("namespace", "style_key"))
                or config.get("name_normalization") not in ("literal", "lowercase_no_spaces")
                or any(config.get(k) not in ("local", "global") for k in ("definition_scope", "assignment_scope"))
                or not isinstance(options, dict) or not isinstance(options.get("reading_affecting_keys"), dict)
                or not isinstance(options.get("non_reading_options"), list)
                or any(not isinstance(k, str) or not k for k in options["non_reading_options"])
                or not isinstance(config.get("exclusive_keys"), list)
                or not isinstance(config.get("bare_defaults"), dict)):
            raise ProfileError(f"{path}: invalid configuration contract")
        keys = set(options["reading_affecting_keys"])
        neutral = set(options["non_reading_options"])
        groups = config["exclusive_keys"]
        if (keys & neutral or config["style_key"] in keys | neutral
                or any(not isinstance(g, list) or len(g) < 2 or any(not isinstance(k, str) or k not in keys for k in g) for g in groups)
                or len([k for g in groups for k in g]) != len({k for g in groups for k in g})
                or any(k not in keys or not isinstance(v, (str, bool)) for k, v in config["bare_defaults"].items())):
            raise ProfileError(f"{path}: conflicting configuration keys or defaults")

    @staticmethod
    def _validate_collector(metadata, path):
        keys = {"collector", "body_name_setting", "default_body_name", "final_code_setting", "default_final_commands"}
        if (not isinstance(metadata, dict) or set(metadata) != keys
                or any(not isinstance(metadata[k], str) or not metadata[k] for k in
                       ("body_name_setting", "default_body_name", "final_code_setting"))
                or not isinstance(metadata["default_final_commands"], list)
                or any(not isinstance(s, str) or not s for s in metadata["default_final_commands"])):
            raise ProfileError(f"{path}: invalid collecting-environment defaults")
        collector = metadata["collector"]
        if (not isinstance(collector, dict) or set(collector) != {"handler", "begin_command", "end_command"}
                or collector["handler"] != "balanced_environment_tokens"
                or any(not isinstance(collector[k], str) or not collector[k] for k in ("begin_command", "end_command"))
                or collector["begin_command"] == collector["end_command"]):
            raise ProfileError(f"{path}: invalid environment token collector")

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
        signature = lambda args: None if args is None else [{k: a[k] for k in ("name", "kind")} for a in args]
        if (shape is None or signature(grammar["arguments"]) != shape[0]
                or signature(grammar.get("starred_arguments")) != shape[1]
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
