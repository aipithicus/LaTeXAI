"""Candidate reconstruction and reporting classifications, not runtime bindings."""
from collections import Counter
from dataclasses import replace
from enum import Enum
import hashlib
import gzip
import json
import re

from ...bindings.catalog import BindingCatalog
from ...bindings.resolver import BindingResolver
from ...engine.meanings import meaning_key
from ...engine.token_text import meaning_text
from ...reading.definition_scanner import DefinitionScanner
from ...reading.tex_reader import TexReader, TokenKind


REGIMES = {"l3": {"_": 11, ":": 11, "@": 11},
           "latex": {"_": 8, ":": 12, "@": 11}}


def layer(name):
    if name.startswith("tex_") and name.endswith(":D"):
        return "tex_primitive_alias"
    if name.startswith("__") or re.match(r"^[lgc]__", name):
        return "private_l3"
    if ":" in name or re.match(r"^[lgcqs]_[A-Za-z]", name):
        return "public_l3"
    if "@" in name:
        return "kernel_at"
    return "public_format"


def kind(meaning):
    if re.match(r"^(?:\\(?:protected|long|outer)\s*)*macro:", meaning):
        return "macro"
    if meaning == "undefined":
        return "undefined"
    if re.match(r"^\\(?:count|dimen|skip|muskip|toks)\d+$", meaning):
        return "register"
    if re.match(r'^\\(?:char|mathchar)"', meaning):
        return "character_constant"
    if meaning.startswith(("the letter ", "the character ", "blank space ", "begin-group ", "end-group ")):
        return "character_alias"
    if meaning.startswith("select font "):
        return "font"
    return "primitive_or_other"


def macro_parts(meaning):
    if kind(meaning) != "macro":
        raise ValueError("not_macro")
    prefix, content = meaning.split("macro:", 1)
    parameters, arrow, body = content.partition("->")
    if not arrow:
        raise ValueError("missing_arrow")
    return re.findall(r"\\(protected|long|outer)", prefix), parameters, body


class Candidates:
    def __init__(self):
        knowledge = BindingResolver(BindingCatalog(), engine_profile="pdftex")
        self.display_context = knowledge.new_context()
        self.contexts = {}
        for regime, assignments in REGIMES.items():
            context = knowledge.new_context()
            context.endlinechar = -1
            for char, category in assignments.items():
                context.catcodes[char] = category
            self.contexts[regime] = context

    def parse(self, meaning, regime, source_id):
        flags, parameters, body = macro_parts(meaning)
        source = r"\def\AssayCandidate " + parameters + "{" + body + "}"
        # A physical newline/control byte can change tokenization or the probe's
        # record framing. Retain it as an explicit exception in this first assay.
        if any(ord(c) < 32 or ord(c) > 126 for c in source):
            raise ValueError("non_ascii_or_control_input")
        context = self.contexts[regime]
        reader = TexReader(source, source_id=source_id, catcodes=context.catcodes, endline_char=-1)
        opening = reader.next_token()
        assert opening.value == "def"
        definition = DefinitionScanner(reader, context).primitive(0)
        if definition.target.value != "AssayCandidate":
            raise ValueError("candidate_target_changed")
        if reader.next_token() is not None or definition.closing.end != len(source):
            raise ValueError("candidate_has_trailing_input")
        definition = replace(definition, **{flag: True for flag in flags})
        return source, definition


def references(definition):
    return Counter(t.value for t in definition.replacement_tokens if t.kind == TokenKind.CONTROL_SEQUENCE)


def active_references(definition):
    return Counter(t.value for t in definition.replacement_tokens if t.kind == TokenKind.ACTIVE_CHARACTER)


def exception_reason(attempts):
    """Report the furthest unsuccessful gate; retain every attempt separately."""
    values = list(attempts.values())
    for outcome in ("native_error", "unequal"):
        if outcome in values:
            return "native_" + outcome if outcome == "unequal" else outcome
    for outcome in ("python_meaning_display_differs", "outer_reference_in_definition",
                    "candidate_has_trailing_input"):
        if any(outcome in value for value in values):
            return outcome
    if any(value.startswith("ReadingIssue:") for value in values):
        return "scanner_rejected_candidate"
    if any("non_ascii_or_control_input" in value for value in values):
        return "non_ascii_or_control_input"
    return "no_qualified_candidate"


def descriptor(definition):
    key = json.loads(json.dumps(meaning_key(definition, None), default=lambda value: value.value if isinstance(value, Enum) else value))
    encoded = json.dumps(key, ensure_ascii=True, separators=(",", ":")).encode()
    return {"semantic_key": key, "semantic_sha256": hashlib.sha256(encoded).hexdigest(),
            "parameter_tokens": len(definition.parameter_tokens),
            "body_tokens": len(definition.replacement_tokens),
            "parameter_count": definition.parameter_count}


def check_fixtures(path):
    """Replay generated native-qualified fixtures through PyTeXML's own types."""
    candidates = Candidates()
    count = 0
    text = gzip.decompress(path.read_bytes()).decode("utf-8") if path.suffix == ".gz" else path.read_text(encoding="utf-8")
    for line in text.splitlines():
        row = json.loads(line)
        if row["schema"] != "pytexml-native-meaning-fixture/1":
            raise ValueError("Unknown meaning fixture schema")
        _, definition = candidates.parse(row["meaning"], row["regime"], "fixture:" + row["name"])
        if descriptor(definition)["semantic_key"] != row["semantic_key"]:
            raise ValueError(f"Typed meaning changed: {row['name']}")
        if meaning_text(definition, candidates.display_context) != row["meaning"]:
            raise ValueError(f"Printed meaning differs: {row['name']}")
        count += 1
    return count


def lexical_references(meaning):
    """Supplemental census candidates only; these are not certified graph edges."""
    return set(re.findall(r"\\([A-Za-z_:@]+|[^A-Za-z_:@])", meaning))
