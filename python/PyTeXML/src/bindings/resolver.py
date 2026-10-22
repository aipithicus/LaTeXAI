"""Resolve declarative reading contracts without expanding manuscript macros.

Bindings and literal profiles are loaded once per resolver. Package activation
is document-local and ordered; resolving an occurrence performs no file I/O.
The result contains immediate lexical effects plus explicit argument/literal
grammar for the future dispatcher. It does not scan source or execute factories,
configuration commands, interpolation bodies, or dynamic TeX assignments.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re
from typing import Any, Iterator

from ..reading.tex_reader import CatCode, CatcodeTable
from ..reading.character_rules import CatcodeLayer, compile_layer
from ..reading.mouth_profiles import MouthBaseline, MouthProfiles, load_mapping




BINDINGS_DIR = Path(__file__).resolve().parents[2] / "bindings"
PROFILES_DIR = Path(__file__).resolve().parents[2] / "profiles"


class ExecutionMode(str, Enum):
    ACTIVE_EXECUTION = "active_execution"
    ARGUMENT_SCANNING = "argument_scanning"
    STORED_DEFINITION = "stored_definition"
    SKIPPED_BRANCH = "skipped_branch"


class UnresolvedReason(str, Enum):
    UNKNOWN_CONSTRUCT = "unknown_construct"
    PACKAGE_NOT_LOADED = "package_not_loaded"
    UNSUPPORTED_READING_OPTION = "unsupported_reading_option"
    ARGUMENTS_REQUIRED = "arguments_required"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    CONFLICTING_DEFINITIONS = "conflicting_definitions"


@dataclass(frozen=True, slots=True)
class UnresolvedBindingResult:
    occurrence_name: str
    reason: UnresolvedReason
    detail: str
    raw_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TerminatorRule:
    exact_string: str
    regex_pattern: str
    matching_domain: str = "stream"
    requires_column_zero: bool = False
    trailing_content_allowed: bool = True
    trailing_line_behavior: str = "preserve_trailing_content"
    boundary_mode: str = "raw_delimiter"


@dataclass(frozen=True, slots=True)
class StateManagementRule:
    guard_variable: str | None = None
    repeated_call_behavior: str = "normal"
    saved_parameters: dict[str, list[str]] = field(default_factory=dict)
    restores_parameters: dict[str, list[str]] = field(default_factory=dict)
    exit_behavior: str = "normal"
    scope: str = "local"


@dataclass(frozen=True, slots=True)
class SpanClassification:
    category: str
    semantic_role: str


@dataclass(frozen=True, slots=True)
class InterpolationRule:
    """A delimiter pair consumed by a literal dispatcher, not a global catcode change."""
    opening: str
    closing: str
    mode: str = "tex"


@dataclass(frozen=True, slots=True)
class EffectiveReadingProfile:
    """Resolved data for one occurrence; applying it is not argument/body execution."""
    name: str
    family: str
    catcode_overrides: dict[str, int] = field(default_factory=dict)
    catcode_layers: tuple[CatcodeLayer, ...] = ()
    reader_parameters: dict[str, Any] = field(default_factory=dict)
    tex_mechanics: dict[str, Any] = field(default_factory=dict)
    terminator: TerminatorRule | None = None
    state_management: StateManagementRule | None = None
    span_classification: SpanClassification | None = None
    source_capture: dict[str, Any] = field(default_factory=dict)
    active_options: dict[str, Any] = field(default_factory=dict)
    grammar: dict[str, Any] = field(default_factory=dict)
    interpolations: tuple[InterpolationRule, ...] = ()
    action: str | None = None
    binding_id: str = ""


@dataclass
class _ScopeSnapshot:
    catcodes: CatcodeTable
    endlinechar: int
    expl3_active: bool
    expl3_saved_catcodes: dict[str, CatCode]
    expl3_saved_endlinechar: int

    def copy(self) -> _ScopeSnapshot:
        return _ScopeSnapshot(self.catcodes.copy(), self.endlinechar,
                              self.expl3_active, dict(self.expl3_saved_catcodes),
                              self.expl3_saved_endlinechar)


class ReaderContext:
    """Immediate lexical state; source dispatch and global assignments live above it.

    Literal callers establish a lexical_scope(), enter the resolved profile, and
    restore it on exit. A live TexReader can share catcodes; the caller must also
    synchronize endline_char before it loads subsequent physical lines.
    """

    def __init__(self, *, baseline: MouthBaseline, catcodes: CatcodeTable | None = None,
                 endlinechar: int | None = None,
                 mode: ExecutionMode = ExecutionMode.ACTIVE_EXECUTION):
        self.baseline = baseline
        self.catcodes = catcodes.copy() if catcodes is not None else baseline.new_catcodes()
        self.endlinechar = baseline.endlinechar if endlinechar is None else endlinechar
        self.mode = mode
        self.expl3_active = False
        self.expl3_saved_catcodes: dict[str, CatCode] = {}
        self.expl3_saved_endlinechar = self.endlinechar
        self._scope_stack: list[_ScopeSnapshot] = []

    def _snapshot(self) -> _ScopeSnapshot:
        return _ScopeSnapshot(self.catcodes.copy(), self.endlinechar,
                              self.expl3_active, dict(self.expl3_saved_catcodes),
                              self.expl3_saved_endlinechar)

    def _restore(self, saved: _ScopeSnapshot) -> None:
        self.catcodes.restore_from(saved.catcodes)
        self.endlinechar = saved.endlinechar
        self.expl3_active = saved.expl3_active
        self.expl3_saved_catcodes = dict(saved.expl3_saved_catcodes)
        self.expl3_saved_endlinechar = saved.expl3_saved_endlinechar

    def copy(self) -> ReaderContext:
        ctx = ReaderContext(baseline=self.baseline, mode=self.mode)
        ctx._restore(self._snapshot())
        ctx._scope_stack = [saved.copy() for saved in self._scope_stack]
        return ctx

    @contextmanager
    def execution_mode(self, mode: ExecutionMode) -> Iterator[None]:
        previous = self.mode
        self.mode = mode
        try:
            yield
        finally:
            self.mode = previous

    @contextmanager
    def argument_scanning(self) -> Iterator[None]:
        with self.execution_mode(ExecutionMode.ARGUMENT_SCANNING):
            yield

    @contextmanager
    def stored_definition(self) -> Iterator[None]:
        with self.execution_mode(ExecutionMode.STORED_DEFINITION):
            yield

    @contextmanager
    def skipped_branch(self) -> Iterator[None]:
        with self.execution_mode(ExecutionMode.SKIPPED_BRANCH):
            yield

    def push_scope(self) -> None:
        self._scope_stack.append(self._snapshot())

    def pop_scope(self) -> bool:
        if not self._scope_stack:
            return False
        self._restore(self._scope_stack.pop())
        return True

    @contextmanager
    def lexical_scope(self) -> Iterator[None]:
        self.push_scope()
        try:
            yield
        finally:
            self.pop_scope()

    def apply_profile(self, profile: EffectiveReadingProfile) -> bool:
        """Apply immediate effects, not a literal scanner or command's full behavior.

        Refuse unresolved results and interpolation plans rather than silently
        presenting them as completely applied. In inactive modes nothing changes.
        """
        if not isinstance(profile, EffectiveReadingProfile):
            raise TypeError("Only a resolved reading profile can be applied")
        if self.mode != ExecutionMode.ACTIVE_EXECUTION:
            return False
        if profile.interpolations:
            raise ValueError("Interpolation requires a literal dispatcher")
        if profile.state_management and profile.state_management.scope != "local":
            raise ValueError("Global assignments require the execution dispatcher")
        unknown = set(profile.reader_parameters) - {"endlinechar"}
        if unknown:
            raise ValueError(f"Unsupported reader parameters: {sorted(unknown)}")

        action = profile.action
        if action == "push_lexical_scope":
            self.push_scope()
            return True
        if action == "pop_lexical_scope":
            return self.pop_scope()
        if action == "expl3_lexical_exit":
            if self.expl3_active:
                for char, code in self.expl3_saved_catcodes.items():
                    self.catcodes[char] = code
                self.endlinechar = self.expl3_saved_endlinechar
                self.expl3_saved_catcodes = {}
                self.expl3_active = False
            return True
        if action == "expl3_lexical_enter" and not self.expl3_active:
            if profile.state_management is None:
                raise ValueError("ExplSyntaxOn requires a state management contract")
            chars = profile.state_management.saved_parameters.get("catcodes", [])
            self.expl3_saved_catcodes = {char: self.catcodes[char] for char in chars}
            self.expl3_saved_endlinechar = self.endlinechar
            self.expl3_active = True

        # Repeated ExplSyntaxOn reapplies effects, without overwriting the baseline.
        for layer in profile.catcode_layers:
            self.catcodes.apply_layer(layer)
        for char, code in profile.catcode_overrides.items():
            self.catcodes[char] = code
        if "endlinechar" in profile.reader_parameters:
            self.endlinechar = profile.reader_parameters["endlinechar"]
        return True


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
    """One in-memory registry with ordered document-local package activation."""

    def __init__(self, bindings_dir: Path | None = None, profiles_dir: Path | None = None):
        self.bindings_dir = bindings_dir or BINDINGS_DIR
        self.profiles_dir = profiles_dir or PROFILES_DIR
        self.profiles: dict[str, dict[str, Any]] = {}
        self.engine_bindings: dict[str, dict[str, Any]] = {}
        self.package_bindings: dict[str, dict[str, Any]] = {}
        self.active_packages: list[str] = []
        self._lexical_layers: dict[str, CatcodeLayer] = {}
        self._load_all()

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        return load_mapping(path)

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
                self._lexical_layers[origin] = compile_layer(reading.get("lexical_mode", {}), origin)
                for section in ("environments", "environment_overrides", "commands", "command_overrides"):
                    for spec in reading.get(section, []):
                        if "profile" in spec:
                            self.mouth.profile(spec["profile"])
                            key = f"{origin}/{spec['name']}"
                            self._lexical_layers[key] = compile_layer(spec.get("lexical_mode", {}), key)

    def new_context(self, baseline: str = "latex_ascii", **kwargs: Any) -> ReaderContext:
        """Bootstrap from already loaded YAML; subsequent reading performs no I/O."""
        return ReaderContext(baseline=self.mouth.baseline(baseline), **kwargs)

    def load_package(self, package_name: str) -> bool:
        """Activate once; a repeated request must not reorder prior definitions."""
        clean = package_name.strip()
        if clean not in self.package_bindings:
            return False
        if clean not in self.active_packages:
            self.active_packages.append(clean)
        return True

    def is_package_active(self, package_name: str) -> bool:
        return package_name.strip() in self.active_packages

    def _active_bindings(self) -> Iterator[tuple[str, dict[str, Any]]]:
        for name in reversed(self.active_packages):
            yield f"packages/{name}", self.package_bindings[name]["reading"]
        for name, data in self.engine_bindings.items():
            yield f"engine/{name}", data["reading"]

    @staticmethod
    def _unresolved(name: str, reason: UnresolvedReason, detail: str,
                    options: dict[str, Any]) -> UnresolvedBindingResult:
        return UnresolvedBindingResult(name, reason, detail, deepcopy(options))

    def _missing(self, name: str, sections: tuple[str, ...],
                 options: dict[str, Any]) -> UnresolvedBindingResult:
        for pkg, data in self.package_bindings.items():
            if pkg in self.active_packages:
                continue
            if any(spec.get("name", spec.get("command")) == name
                   for section in sections for spec in data["reading"].get(section, [])):
                return self._unresolved(name, UnresolvedReason.PACKAGE_NOT_LOADED,
                                        f"'{name}' requires package '{pkg}'", options)
        return self._unresolved(name, UnresolvedReason.UNKNOWN_CONSTRUCT,
                                f"No active binding for '{name}'", options)

    def resolve_command(self, name: str, options: dict[str, Any] | None = None
                        ) -> EffectiveReadingProfile | UnresolvedBindingResult:
        """Resolve command identity. The caller consumes stars/arguments using grammar."""
        clean = name if name.startswith("\\") else f"\\{name}"
        opts = dict(options or {})
        sections = ("catcode_mutators", "grouping", "command_overrides",
                    "commands", "factories", "inclusions", "conditionals")
        for origin, reading in self._active_bindings():
            for section in sections:
                for spec in reading.get(section, []):
                    if spec.get("name", spec.get("command")) != clean:
                        continue
                    action = spec.get("action")
                    if section == "catcode_mutators":
                        if action == "assign_catcode_dynamic":
                            return self._unresolved(clean, UnresolvedReason.ARGUMENTS_REQUIRED,
                                                    "TeX assignment arguments require a token scanner", opts)
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
                        return EffectiveReadingProfile(clean, "grouping", action=action, binding_id=origin)
                    if section in {"commands", "command_overrides"} and spec.get("family") in {
                            "inline_verbatim", "external_verbatim_file"}:
                        return self._build_literal(clean, spec, reading, origin, opts, environment=False)
                    return self._unresolved(clean, UnresolvedReason.UNSUPPORTED_OPERATION,
                                            "This operation requires the execution/argument dispatcher", opts)
        return self._missing(clean, sections, opts)

    def resolve_group(self, catcode: int) -> EffectiveReadingProfile | UnresolvedBindingResult:
        """Category-driven lookup; argument delimiters must not call this as execution."""
        for origin, reading in self._active_bindings():
            for spec in reading.get("grouping", []):
                if spec.get("trigger") == "token_category" and spec.get("catcode") == catcode:
                    return EffectiveReadingProfile(spec["name"], "grouping",
                                                   action=spec["action"], binding_id=origin)
        return self._unresolved(str(catcode), UnresolvedReason.UNKNOWN_CONSTRUCT,
                                "No group action for this category", {})

    def resolve_environment(self, name: str, options: dict[str, Any] | None = None
                            ) -> EffectiveReadingProfile | UnresolvedBindingResult:
        clean, opts = name.strip(), dict(options or {})
        sections = ("environment_overrides", "environments")
        for origin, reading in self._active_bindings():
            for section in sections:
                for spec in reading.get(section, []):
                    if spec.get("name") == clean:
                        return self._build_literal(clean, spec, reading, origin, opts, environment=True)
        return self._missing(clean, sections, opts)

    def _profile(self, name: str) -> dict[str, Any]:
        return self.mouth.profile(name)

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
        layers = self.mouth.layers(profile_name) + tuple(
            layer for layer in (self._lexical_layers[origin], self._lexical_layers[f"{origin}/{name}"])
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
