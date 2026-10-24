"""Resolve reading contracts using a catalog and document-local package activation.

Resolution does not scan source or execute factories, configuration commands,
interpolation bodies, or dynamic TeX assignments.
"""
from __future__ import annotations
from copy import deepcopy
import re
from typing import Any, Iterator
from .catalog import BindingCatalog
from ..reading.context import ReaderContext
from ..reading.contracts import (
    ConditionalRule, EffectiveReadingProfile, InterpolationRule, SpanClassification,
    StateManagementRule, TerminatorRule, UnresolvedBindingResult, UnresolvedReason,
)


def _merge(*layers: dict[str, Any]) -> dict[str, Any]:
    """Recursive map overlay; results never alias loaded YAML or caller options."""
    result: dict[str, Any] = {}
    for layer in layers:
        for key, value in layer.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = _merge(result[key], value)
            else:
                result[key] = deepcopy(value)
    return result


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

    def __init__(self, catalog: BindingCatalog | None = None):
        self.catalog = catalog if catalog is not None else BindingCatalog()
        self.active_packages: list[str] = []

    def new_context(self, baseline: str = "latex_ascii", **kwargs: Any) -> ReaderContext:
        """Bootstrap from already loaded YAML; subsequent reading performs no I/O."""
        return ReaderContext(baseline=self.catalog.mouth.baseline(baseline), **kwargs)

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

    def _active_bindings(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for name in reversed(self.active_packages):
            yield f"packages/{name}", self.catalog.package_bindings[name]["reading"]
        for name, data in self.catalog.engine_bindings.items():
            yield f"engine/{name}", data["reading"]

    @staticmethod
    def _unresolved(name: str, reason: UnresolvedReason, detail: str,
                    options: dict[str, Any]) -> UnresolvedBindingResult:
        return UnresolvedBindingResult(name, reason, detail, deepcopy(options))

    def _missing(self, name: str, sections: tuple[str, ...],
                 options: dict[str, Any]) -> UnresolvedBindingResult:
        for pkg, data in self.catalog.package_bindings.items():
            if pkg in self.active_packages:
                continue
            if any(spec.get("name", spec.get("command")) == name
                   for section in sections for spec in data["reading"].get(section, [])):
                return self._unresolved(name, UnresolvedReason.PACKAGE_NOT_LOADED,
                                        f"'{name}' requires package '{pkg}'", options)
        return self._unresolved(name, UnresolvedReason.UNKNOWN_CONSTRUCT,
                                f"No active binding for '{name}'", options)

    _command_sections = ("catcode_mutators", "grouping", "command_overrides",
                         "commands", "factories", "inclusions", "conditionals")

    def _command_specs(self, clean: str) -> Iterator[tuple[str, dict[str, Any], str, dict[str, Any]]]:
        """Yield only the winning declaration, including nonconditional shadows."""
        for origin, reading in self._active_bindings():
            for section in self._command_sections:
                for spec in reading.get(section, []):
                    if spec.get("name", spec.get("command")) == clean:
                        yield origin, reading, section, spec
                        return

    def resolve_conditional(self, name: str) -> ConditionalRule | None:
        """Classify without resolving arguments/effects or expanding macros.

        None means no conditional meaning in the established binding context.
        Stored author definitions take precedence at the scanner/dispatcher.
        """
        clean = name if name.startswith("\\") else f"\\{name}"
        for _, _, section, spec in self._command_specs(clean):
            if section == "conditionals":
                return ConditionalRule(spec["role"], spec.get("evaluation"))
        return None

    def source_command_syntax(self, name: str) -> EffectiveReadingProfile | None:
        """Inspect a unique inactive package's source-argument grammar.

        This does not activate that package or establish the command's meaning.
        Preparation uses it only to capture a pending reference's full header.
        Literal/effect profiles are deliberately outside this observational API.
        """
        clean = name if name.startswith("\\") else f"\\{name}"
        candidates = []
        for package, data in self.catalog.package_bindings.items():
            for section in self._command_sections:
                for spec in data["reading"].get(section, []):
                    if spec.get("name", spec.get("command")) == clean:
                        candidates.append((package, spec))
        if len(candidates) != 1 or candidates[0][1].get("family") != "source_command":
            return None
        package, spec = candidates[0]
        return EffectiveReadingProfile(clean, "source_command", action=spec["action"],
            grammar=deepcopy(spec["grammar"]), tex_mechanics=deepcopy(spec.get("metadata", {})),
            binding_id=f"packages/{package}")

    def resolve_command(self, name: str, options: dict[str, Any] | None = None
                        ) -> EffectiveReadingProfile | UnresolvedBindingResult:
        """Resolve command identity. The caller consumes stars/arguments using grammar."""
        clean = name if name.startswith("\\") else f"\\{name}"
        opts = dict(options or {})
        for origin, reading, section, spec in self._command_specs(clean):
            action = spec.get("action")
            if spec.get("family") in {"source_command", "environment_factory"}:
                return EffectiveReadingProfile(clean, spec["family"], action=spec["action"],
                    grammar=deepcopy(spec["grammar"]), tex_mechanics=deepcopy(spec.get("metadata", {})), binding_id=origin)
            if section == "conditionals":
                if opts:
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                            "Conditional commands have no resolved options", opts)
                return EffectiveReadingProfile(
                    clean, "conditional", binding_id=origin,
                    conditional=ConditionalRule(spec["role"], spec.get("evaluation")))
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
            if section in {"commands", "command_overrides"} and spec.get("family") in {"stored_definition", "conditional_factory"}:
                if opts:
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                            "Definition declarations have no resolved options", opts)
                return EffectiveReadingProfile(
                    clean, spec["family"], binding_id=origin,
                    grammar=deepcopy(spec["grammar"]),
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
                return self._build_literal(clean, spec, reading, origin, opts, environment=False)
            return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_OPERATION,
                                    "This operation requires the execution/argument dispatcher", opts)
        return self._missing(clean, self._command_sections, opts)

    def resolve_group(self, catcode: int) -> EffectiveReadingProfile | UnresolvedBindingResult:
        """Category-driven lookup; argument delimiters must not call this as execution."""
        for origin, reading in self._active_bindings():
            for spec in reading.get("grouping", []):
                if spec.get("trigger") == "token_category" and spec.get("catcode") == catcode:
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
        sections = ("environment_overrides", "environments")
        for origin, reading in self._active_bindings():
            for section in sections:
                for spec in reading.get(section, []):
                    if spec.get("name") == clean:
                        if spec.get("family") == "structural_environment":
                            return EffectiveReadingProfile(clean, "structural_environment", binding_id=origin,
                                grammar=deepcopy(spec["grammar"]), tex_mechanics=deepcopy(spec.get("metadata", {})))
                        return self._build_literal(clean, spec, reading, origin, opts, environment=True)
        return self._missing(clean, sections, opts)

    def _profile(self, name: str) -> dict[str, Any]:
        return self.catalog.mouth.profile(name)

    def _resolve_options(self, name: str, options: dict[str, Any], contract: dict[str, Any]
                         ) -> tuple[dict[str, Any], dict[str, int], tuple[InterpolationRule, ...]] | UnresolvedBindingResult:
        declarations = contract.get("reading_affecting_keys", {})
        passthrough = contract.get("non_reading_options", [])
        active, overrides, interpolations = {}, {}, []
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
            except ValueError as error:
                return self._unresolved(name, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                        f"{key}: {error}", options)
        active.update({key: deepcopy(value) for key, value in options.items() if key in passthrough})
        if len(interpolations) > 1:
            return self._unresolved(name, UnresolvedReason.UNSUPPORTED_READING_OPTION,
                                    "Combined interpolation modes need precedence resolution", options)
        return active, overrides, tuple(interpolations)

    def _build_literal(self, name: str, spec: dict[str, Any], reading: dict[str, Any],
                       origin: str, options: dict[str, Any], *, environment: bool
                       ) -> EffectiveReadingProfile | UnresolvedBindingResult:
        profile_name = spec["profile"]
        defaults = self._profile(profile_name)
        merged = _merge(defaults, {"lexical_mode": reading.get("lexical_mode", {})}, spec)
        lex = merged.get("lexical_mode", {})
        contract = reading.get("option_resolution", {})
        resolved = self._resolve_options(name, options, contract)
        if isinstance(resolved, UnresolvedBindingResult):
            return resolved
        active, option_codes, interpolations = resolved
        layers = self.catalog.mouth.layers(profile_name) + tuple(
            layer for layer in (self.catalog.lexical_layers[origin], self.catalog.lexical_layers[f"{origin}/{name}"])
            if layer.rules or layer.assignments)
        classification = merged["span_classification"]
        category = classification.get("default_category", classification["category"])
        if interpolations:
            profile_name = "interpolated_verbatim_block"
            category = "interpolated_literal"
        elif any(code == 0 for code in option_codes.values()):
            profile_name = "semi_verbatim_block"
            category = "semi_verbatim_block"
        elif option_codes:
            category = "comment_aware_literal"

        terminator = None
        if environment:
            raw_term = merged.get("terminator", {})
            exact = raw_term.get("exact_string", defaults.get(
                "terminator_pattern", "\\end{{{name}}}").format(name=name))
            terminator = TerminatorRule(**_merge(
                {"exact_string": exact, "regex_pattern": re.escape(exact)}, raw_term))
        grammar = deepcopy(merged.get("grammar", {}))
        for key in ("syntax", "arity", "delimiter_mode", "invalid_delimiters",
                    "multiline_allowed", "starred_variant", "visible_spaces",
                    "has_optional_arguments", "options_syntax", "allow_nesting"):
            if key in merged:
                grammar[key] = deepcopy(merged[key])
        return EffectiveReadingProfile(
            name=name, family=profile_name, binding_id=origin,
            catcode_overrides=option_codes, catcode_layers=layers,
            reader_parameters=deepcopy(lex.get("reader_parameters", {})),
            tex_mechanics=deepcopy(lex.get("tex_mechanics", {})),
            source_capture=deepcopy(lex.get("source_capture", {})),
            terminator=terminator,
            span_classification=SpanClassification(category, classification["semantic_role"]),
            active_options=active, grammar=grammar, interpolations=interpolations)
