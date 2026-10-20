"""Compiled regex character sets, independent of YAML and source I/O.

Catcode-run patterns are one regex character class followed by ``+``. This
contract makes full-span membership and single-character classification agree.
Structural patterns have a different contract and do not belong in this layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterator, Mapping
import warnings


class ProfileError(ValueError):
    """An invalid or conflicting reading declaration, with its configuration origin."""


def category(value: Any, origin: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 15:
        raise ProfileError(f"{origin}: catcode must be an integer in 0..15")
    return value


def validate_reader_parameters(parameters: Any, origin: str) -> dict[str, int]:
    if not isinstance(parameters, dict) or set(parameters) - {"endlinechar"}:
        raise ProfileError(f"{origin}: expected only the supported endlinechar parameter")
    if "endlinechar" in parameters:
        value = parameters["endlinechar"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProfileError(f"{origin}: endlinechar must be an integer")
    return dict(parameters)


# Validate the *shape*, then let re compile and interpret all ranges/escapes.
# Escape literal ] as \]; nested set-operator syntax is not Python re syntax.
_CLASS_RUN = re.compile(r"\[(?:\\[^\r\n]|[^\\\]\r\n])+\]\+")


@dataclass(frozen=True, slots=True)
class CharacterRule:
    rule_id: str
    pattern: str
    catcode: int
    _compiled: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        category(self.catcode, self.rule_id)
        if not isinstance(self.pattern, str) or not _CLASS_RUN.fullmatch(self.pattern):
            raise ProfileError(
                f"{self.rule_id}: catcode_run requires one character class followed by +; "
                "use escapes inside the class, without anchors or contextual assertions")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", FutureWarning)
                compiled = re.compile(self.pattern)
        except (re.error, FutureWarning) as error:
            raise ProfileError(f"{self.rule_id}: invalid character regex: {error}") from error
        object.__setattr__(self, "_compiled", compiled)

    @staticmethod
    def _bounds(text: str, start: int, end: int | None) -> int:
        limit = len(text) if end is None else end
        if not 0 <= start <= limit <= len(text):
            raise ValueError("Span must lie within the supplied character view")
        return limit

    def fullmatch(self, text: str, start: int = 0, end: int | None = None) -> bool:
        """Whether a nonempty span belongs wholly to this regex character set."""
        limit = self._bounds(text, start, end)
        return self._compiled.fullmatch(text, start, limit) is not None

    def spans(self, text: str, start: int = 0, end: int | None = None
              ) -> Iterator[tuple[int, int]]:
        """Maximal matching runs, at unchanged offsets in the supplied view.

        The caller owns source/occurrence/context identity and any correspondence
        from preprocessed characters to raw source. This is not a token scanner.
        """
        limit = self._bounds(text, start, end)
        for match in self._compiled.finditer(text, start, limit):
            yield match.span()


@dataclass(frozen=True, slots=True)
class CatcodeLayer:
    origin: str
    rules: tuple[CharacterRule, ...] = ()
    assignments: tuple[tuple[str, int], ...] = ()

    def resolve(self, character: str) -> int | None:
        for char, code in self.assignments:
            if char == character:
                return code
        found: CharacterRule | None = None
        for rule in self.rules:
            if rule.fullmatch(character):
                if found is not None and found.catcode != rule.catcode:
                    raise ProfileError(
                        f"{self.origin}: U+{ord(character):04X} conflicts between "
                        f"{found.rule_id} ({found.catcode}) and {rule.rule_id} ({rule.catcode})")
                found = rule
        return found.catcode if found is not None else None


def compile_layer(lexical: Mapping[str, Any], origin: str) -> CatcodeLayer:
    """Compile one declaration layer; explicit assignments override its regex rules."""
    if not isinstance(lexical, dict):
        raise ProfileError(f"{origin}: lexical_mode must be a mapping")
    allowed = {"character_classes", "catcode_overrides", "default", "reader_parameters",
               "tex_mechanics", "source_capture"}
    if set(lexical) - allowed:
        raise ProfileError(f"{origin}: unknown lexical keys {sorted(set(lexical) - allowed)}")
    raw_rules = lexical.get("character_classes", [])
    if not isinstance(raw_rules, list):
        raise ProfileError(f"{origin}: character_classes must be a list")
    rules, ids = [], set()
    for spec in raw_rules:
        required = {"id", "kind", "domain", "pattern", "catcode"}
        if not isinstance(spec, dict) or set(spec) != required:
            raise ProfileError(f"{origin}: a character rule requires {sorted(required)}")
        name = spec["id"]
        if not isinstance(name, str) or not name or name in ids:
            raise ProfileError(f"{origin}: missing or duplicate character-rule id {name!r}")
        ids.add(name)
        if spec["kind"] != "catcode_run" or spec["domain"] != "mouth_characters":
            raise ProfileError(f"{origin}/{name}: expected catcode_run on mouth_characters")
        rules.append(CharacterRule(f"{origin}/{name}", spec["pattern"], spec["catcode"]))
    raw_assignments = lexical.get("catcode_overrides", {})
    if not isinstance(raw_assignments, dict):
        raise ProfileError(f"{origin}: catcode_overrides must be a mapping")
    assignments = []
    for char, code in raw_assignments.items():
        if not isinstance(char, str) or len(char) != 1:
            raise ProfileError(f"{origin}: explicit catcode target must be one character")
        assignments.append((char, category(code, origin)))
    if "default" in lexical:
        category(lexical["default"], origin)
    validate_reader_parameters(lexical.get("reader_parameters", {}), origin)
    layer = CatcodeLayer(origin, tuple(rules), tuple(assignments))
    # Diagnose the shipped ASCII domain at load time. Unicode conflicts are
    # diagnosed on lookup; no Unicode universe is expanded or stored as a table.
    for value in range(128):
        layer.resolve(chr(value))
    return layer
