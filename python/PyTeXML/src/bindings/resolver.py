"""Resolve reading contracts using a catalog and document-local package activation.

Resolution does not scan source or execute factories, configuration commands,
interpolation bodies, or dynamic TeX assignments.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Iterator
from .catalog import BindingCatalog, ReadingDeclaration
from ..yaml_io import overlay
from ..engine.format import latex_meanings
from ..reading.context import ReaderContext
from ..reading.contracts import (
    ConditionalRule, EffectiveReadingProfile, InterpolationRule, SpanClassification,
    StateManagementRule, UnresolvedBindingResult, UnresolvedReason, ReadingIssue,
)


@dataclass(slots=True)
class LiteralOptions:
    active: dict[str, Any] = field(default_factory=dict)
    catcodes: dict[str, int] = field(default_factory=dict)
    interpolations: list[InterpolationRule] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)


def _characters(value: Any, count: int) -> tuple[str, ...] | None:
    """Accept decoded characters or TeX control-symbol spellings; never expand words."""
    if value == "none":
        return None
    if isinstance(value, (tuple, list)):
        chars = tuple(value)
    elif (isinstance(value, str) and len(value) == count
          and ("\\" not in value or count == 1)):
        chars = tuple(value)
    elif isinstance(value, str):
        chars_list = []
        i = 0
        while i < len(value):
            if value[i] == "\\":
                i += 1
                if i == len(value) or value[i].isalpha():
                    raise ValueError("Expected literal characters or control symbols")
            chars_list.append(value[i])
            i += 1
        chars = tuple(chars_list)
    else:
        raise ValueError("Expected characters")
    if (len(chars) != count or any(not isinstance(c, str) or len(c) != 1
                                   or c in "\r\n" for c in chars)):
        raise ValueError(f"Expected {count} literal character(s)")
    if len(set(chars)) != count:
        raise ValueError("Command and group delimiters must be distinct")
    return chars


def _delimiter_pair(value: Any) -> tuple[str, str] | None:
    if value == "":
        return None
    if isinstance(value, (tuple, list)):
        parts = list(value)
    elif isinstance(value, str):
        # Two balanced brace groups; preserve delimiters' inner/escaped braces.
        parts, i = [], 0
        while i < len(value):
            if value[i] != "{":
                raise ValueError("escapeinside requires two braced delimiters")
            start, depth = i + 1, 1
            i += 1
            while i < len(value) and depth:
                if value[i] == "\\" and i + 1 < len(value):
                    i += 2
                    continue
                if value[i] == "{":
                    depth += 1
                elif value[i] == "}":
                    depth -= 1
                i += 1
            if depth:
                raise ValueError("Unclosed escapeinside delimiter")
            parts.append(value[start:i - 1])
    else:
        raise ValueError("escapeinside requires a delimiter pair")
    if (len(parts) != 2 or any(not isinstance(p, str) or not p or "\n" in p or "\r" in p
                               for p in parts)):
        raise ValueError("escapeinside requires two nonempty delimiters")
    return parts[0], parts[1]


class BindingResolver:
    """One document's ordered package activation over reusable catalog knowledge."""

    def __init__(self, catalog: BindingCatalog | None = None, *, engine_profile="etex"):
        self.catalog = catalog if catalog is not None else BindingCatalog()
        self.engine_profile = engine_profile
        self.active_packages: list[str] = []

    def new_context(self, baseline: str = "latex_ascii", **kwargs: Any) -> ReaderContext:
        """Bootstrap from already loaded YAML; subsequent reading performs no I/O."""
        kwargs.setdefault("engine_profile", self.engine_profile)
        return ReaderContext(baseline=self.catalog.mouth.baseline(baseline),
                             initial_meanings=latex_meanings(), **kwargs)

    def load_package(self, package_name: str) -> bool:
        """Activate once; a repeated request must not reorder prior definitions."""
        clean = package_name.strip()
        if clean not in self.catalog.package_bindings:
            return False
        if clean not in self.active_packages:
            self.active_packages.append(clean)
        return True

    def is_package_active(self, package_name: str) -> bool:
        return package_name.strip() in self.active_packages

    def _active_origins(self) -> Iterator[str]:
        for name in reversed(self.active_packages):
            yield f"packages/{name}"
        for name in self.catalog.engine_bindings:
            yield f"engine/{name}"

    def _declaration(self, name, index) -> ReadingDeclaration | None:
        providers = index.get(name, {})
        for origin in self._active_origins():
            if origin in providers:
                return providers[origin][0]
        return None

    @staticmethod
    def _unresolved(name: str, reason: UnresolvedReason, detail: str,
                    options: dict[str, Any]) -> UnresolvedBindingResult:
        return UnresolvedBindingResult(name, reason, detail, deepcopy(options))

    def _missing(self, name: str, index,
                 options: dict[str, Any]) -> UnresolvedBindingResult:
        for origin in index.get(name, {}):
            tier, pkg = origin.split("/", 1)
            if tier == "packages" and pkg not in self.active_packages:
                return self._unresolved(name, UnresolvedReason.PACKAGE_NOT_LOADED,
                                        f"Reading grammar for '{name}' is known from inactive binding '{pkg}'; "
                                        "the source provider is not established", options)
        return self._unresolved(name, UnresolvedReason.UNKNOWN_CONSTRUCT,
                                f"No active binding for '{name}'", options)

    def _command_specs(self, clean: str) -> Iterator[ReadingDeclaration]:
        """Yield only the winning declaration, including nonconditional shadows."""
        declaration = self._declaration(clean, self.catalog.commands)
        if declaration is not None:
            yield declaration

    def resolve_conditional(self, name: str) -> ConditionalRule | None:
        """Classify without resolving arguments/effects or expanding macros.

        None means no conditional meaning in the established binding context.
        Stored author definitions take precedence at the scanner/dispatcher.
        """
        clean = name if name.startswith("\\") else f"\\{name}"
        for declaration in self._command_specs(clean):
            spec = declaration.spec
            if declaration.section == "conditionals":
                return ConditionalRule(spec["role"], spec.get("evaluation"), spec.get("capture_operands"), spec.get("predicate"))
        return None

    def reading_names(self) -> set[str]:
        from ..engine.file_hooks import PROFILES
        from ..engine.latex.registry import PROFILES as FORMAT_PROFILES
        names = {name.lstrip("\\") for name in self.catalog.commands}
        names.update(PROFILES)
        names.update(FORMAT_PROFILES)
        for name in self.catalog.environments:
            names.update((name, "end" + name))
        return names

    def source_command_syntax(self, name: str) -> EffectiveReadingProfile | None:
        """Inspect a unique inactive package's source-argument grammar.

        This does not activate that package or establish the command's meaning.
        Preparation uses it only to capture a pending reference's full header.
        Literal/effect profiles are deliberately outside this observational API.
        """
        clean = name if name.startswith("\\") else f"\\{name}"
        candidates = [declaration for origin, declarations in self.catalog.commands.get(clean, {}).items()
                      if origin.startswith("packages/") for declaration in declarations]
        if len(candidates) != 1 or candidates[0].spec.get("family") != "source_command":
            return None
        declaration = candidates[0]
        spec = declaration.spec
        return EffectiveReadingProfile(clean, "source_command", action=spec["action"],
            grammar=deepcopy(spec["grammar"]), tex_mechanics=deepcopy(spec.get("metadata", {})),
            binding_id=declaration.origin)

    def resolve_command(self, name: str, options: dict[str, Any] | None = None
                        ) -> EffectiveReadingProfile | UnresolvedBindingResult:
        """Resolve command identity. The caller consumes stars/arguments using grammar."""
        from ..engine.file_hooks import PROFILES
        native = PROFILES.get(name.removeprefix("\\"))
        if native is not None:
            return native
        from ..engine.latex.registry import PROFILES as FORMAT_PROFILES
        format_profile = FORMAT_PROFILES.get(name.removeprefix("\\"))
        if format_profile is not None:
            return format_profile
        clean = name if name.startswith("\\") else f"\\{name}"
        opts = dict(options or {})
        for declaration in self._command_specs(clean):
            origin, reading, section, spec = declaration.origin, declaration.reading, declaration.section, declaration.spec
            action = spec.get("action")
            if spec.get("family") == "expansion_control":
                return EffectiveReadingProfile(clean, spec["family"], grammar=deepcopy(spec["grammar"]),
                                               binding_id=origin)
            if spec.get("family") == "configuration_command":
                return EffectiveReadingProfile(clean, spec["family"], action=action,
                    grammar=deepcopy(spec["grammar"]), tex_mechanics=deepcopy(spec["metadata"]), binding_id=origin,
                    configuration=overlay(reading["option_resolution"], reading["configuration"]))
            if spec.get("family") in {"source_command", "environment_factory", "option_control"}:
                return EffectiveReadingProfile(clean, spec["family"], action=spec["action"],
                    grammar=deepcopy(spec["grammar"]), tex_mechanics=deepcopy(spec.get("metadata", {})), binding_id=origin)
            if section == "conditionals":
                if opts:
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                            "Conditional commands have no resolved options", opts)
                return EffectiveReadingProfile(
                    clean, "conditional", binding_id=origin,
                    conditional=ConditionalRule(spec["role"], spec.get("evaluation"), spec.get("capture_operands"), spec.get("predicate")))
            if section == "catcode_mutators":
                if action == "assign_catcode_dynamic":
                    return EffectiveReadingProfile(clean, "catcode_assignment", action=action,
                        grammar=deepcopy(spec["grammar"]), binding_id=origin,
                        state_management=StateManagementRule(scope=spec["scope"]))
                if action not in {"assign_catcode", "expl3_lexical_enter", "expl3_lexical_exit"}:
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_OPERATION,
                                            f"No implementation for {action!r}", opts)
                if opts:
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                            "A catcode operation has no literal options", opts)
                sm = spec.get("state_management", {})
                overrides = dict(spec.get("overrides", {}))
                if "target_char" in spec:
                    overrides[spec["target_char"]] = spec["category"]
                return EffectiveReadingProfile(
                    name=clean, family="catcode_mutator", action=action, binding_id=origin,
                    catcode_overrides=overrides,
                    reader_parameters=deepcopy(spec.get("reader_parameters", {})),
                    state_management=StateManagementRule(
                        **deepcopy(sm), scope=spec.get("scope", "local")),
                    span_classification=SpanClassification("lexical_directive", "catcode_mutation"))
            if section == "grouping":
                return self._build_group(clean, spec, origin)
            if section in {"commands", "command_overrides"} and spec.get("family") in {"stored_definition", "conditional_factory", "collected_environment_definition", "meaning_assignment", "assignment_prefix", "parameter_assignment", "character_code_definition"}:
                if opts:
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                            "Definition declarations have no resolved options", opts)
                return EffectiveReadingProfile(
                    clean, spec["family"], binding_id=origin,
                    grammar=deepcopy(spec["grammar"]),
                    tex_mechanics=deepcopy(spec.get("metadata", {})),
                    state_management=StateManagementRule(scope=spec["scope"]))
            if section in {"commands", "command_overrides"} and spec.get("family") == "environment_open":
                if opts:
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                            "Environment opener has no resolved options", opts)
                return EffectiveReadingProfile(
                    clean, "environment_open", binding_id=origin,
                    grammar=deepcopy(spec.get("grammar", {})))
            if section in {"commands", "command_overrides"} and spec.get("family") in {
                    "inline_verbatim", "external_verbatim_file"}:
                return self._build_literal(declaration, opts)
            return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_OPERATION,
                                    "This operation requires the execution/argument dispatcher", opts)
        return self._missing(clean, self.catalog.commands, opts)

    def resolve_group(self, catcode: int) -> EffectiveReadingProfile | UnresolvedBindingResult:
        """Category-driven lookup; argument delimiters must not call this as execution."""
        providers = self.catalog.groups.get(catcode, {})
        for origin in self._active_origins():
            if origin in providers:
                spec = providers[origin].spec
                return self._build_group(spec["name"], spec, origin)
        return self._unresolved(str(catcode), UnresolvedReason.UNKNOWN_CONSTRUCT,
                                "No group action for this category", {})

    @staticmethod
    def _build_group(name: str, spec: dict[str, Any], origin: str) -> EffectiveReadingProfile:
        return EffectiveReadingProfile(
            name, "grouping", action=spec["action"], binding_id=origin,
            state_management=StateManagementRule(**deepcopy(spec.get("state_management", {}))))

    def resolve_environment(self, name: str, options: dict[str, Any] | None = None
                            ) -> EffectiveReadingProfile | UnresolvedBindingResult:
        clean, opts = name.strip(), dict(options or {})
        declaration = self._declaration(clean, self.catalog.environments)
        if declaration is not None:
            spec = declaration.spec
            if spec.get("family") == "structural_environment":
                return EffectiveReadingProfile(clean, "structural_environment", binding_id=declaration.origin,
                    grammar=deepcopy(spec["grammar"]), tex_mechanics=deepcopy(spec.get("metadata", {})))
            return self._build_literal(declaration, opts)
        return self._missing(clean, self.catalog.environments, opts)

    def check_configuration(self, name, options, contract):
        result = self._resolve_options(name, options, contract)
        if isinstance(result, UnresolvedBindingResult):
            raise ReadingIssue(result.reason.value, result.detail)

    def _resolve_options(self, name: str, options: dict[str, Any], contract: dict[str, Any]
                         ) -> LiteralOptions | UnresolvedBindingResult:
        declarations = contract.get("reading_affecting_keys", {})
        passthrough = contract.get("non_reading_options", [])
        result = LiteralOptions()
        active, overrides, interpolations = result.active, result.catcodes, result.interpolations
        # Binding order controls conflicting assignments, not order of user keys.
        unknown = set(options) - set(declarations) - set(passthrough)
        if unknown:
            return self._unresolved(name, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                    f"Unclassified options: {sorted(unknown)}", options)
        for key, rule in declarations.items():
            if key not in options:
                continue
            value, effect = options[key], rule.get("effect")
            try:
                if rule.get("unsupported_action") == "report_unresolved":
                    raise ValueError("This reading effect requires further interpretation")
                if effect == "assign_command_and_group_delimiters":
                    chars = _characters(value, 3)
                    active[key] = chars
                    if chars:
                        overrides.update(zip(chars, (0, 1, 2)))
                elif effect == "enable_verbatim_comment":
                    chars = _characters(value, 1)
                    active[key] = chars[0] if chars else None
                    if chars:
                        overrides[chars[0]] = 14
                elif effect == "define_interpolation_delimiters":
                    pair = _delimiter_pair(value)
                    active[key] = pair
                    if pair:
                        interpolations.append(InterpolationRule(*pair))
                elif effect == "define_single_escape_char":
                    chars = None if value == "" else _characters(value, 1)
                    active[key] = chars[0] if chars else None
                    if chars:
                        interpolations.append(InterpolationRule(chars[0], chars[0]))
                elif effect == "toggle_math_mode_on_dollar":
                    if isinstance(value, bool):
                        enabled = value
                    elif value in ("true", "false"):
                        enabled = value == "true"
                    else:
                        raise ValueError("Expected true or false")
                    active[key] = enabled
                    if enabled:
                        interpolations.append(InterpolationRule("$", "$", "math"))
                else:
                    raise ValueError(f"Unknown reading effect {effect!r}")
                if active[key] and "profile_override" in rule and rule["profile_override"] not in result.profiles:
                    result.profiles.append(rule["profile_override"])
            except ValueError as error:
                return self._unresolved(name, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                        f"{key}: {error}", options)
        active.update({key: deepcopy(value) for key, value in options.items() if key in passthrough})
        if len(interpolations) > 1:
            return self._unresolved(name, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                    "Combined interpolation modes need precedence resolution", options)
        return result

    def _build_literal(self, declaration: ReadingDeclaration, options: dict[str, Any]
                       ) -> EffectiveReadingProfile | UnresolvedBindingResult:
        template = declaration.literal
        assert template is not None
        resolved = self._resolve_options(template.name, options, declaration.reading.get("option_resolution", {}))
        if isinstance(resolved, UnresolvedBindingResult):
            return resolved
        family, layers = template.family, template.catcode_layers
        classification = template.span_classification
        category = "comment_aware_literal" if resolved.catcodes else classification.category
        parameters = deepcopy(template.reader_parameters)
        mechanics, capture = deepcopy(template.tex_mechanics), deepcopy(template.source_capture)
        # Option profiles add lexical layers; they do not reset the base's demotions
        # or replace the construct's argument grammar and terminator.
        for family in resolved.profiles:
            profile = self.catalog.literal_profiles[family]
            layers += self.catalog.mouth.layers(family)
            category = profile["span_classification"]["category"]
            lex = profile.get("lexical_mode", {})
            parameters = overlay(parameters, lex.get("reader_parameters", {}))
            mechanics = overlay(mechanics, lex.get("tex_mechanics", {}))
            capture = overlay(capture, lex.get("source_capture", {}))
        return replace(template, family=family, catcode_layers=layers, catcode_overrides=resolved.catcodes,
            reader_parameters=parameters, tex_mechanics=mechanics, source_capture=capture,
            span_classification=SpanClassification(category, classification.semantic_role),
            active_options=resolved.active, interpolations=tuple(resolved.interpolations),
            grammar=deepcopy(template.grammar), configuration=deepcopy(template.configuration))
