"""Versioned, interned JSON snapshots of quiescent source-built format state.

No pickle, dynamic import or executable payload is accepted. Object sharing and
token/source identities survive the round trip. Inputs and engine code are
fingerprinted separately from the graph and checked before restoration.
"""
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path

from ..reading import contracts
from ..reading.context import ReaderContext
from ..reading.spans import SourceBasis, SourceSpan
from ..reading.tex_reader import CatCode, CatcodeTable, Token, TokenKind
from .dimensions import Glue
from .fonts import FontParameters
from .parameters import IntegerValue
from .primitive import PrimitiveMeaning
from .primitives.definitions import DefinitionSpec
from .primitives.registers import Register
from .state_cells import Cell


SCHEMA = "pytexml-format/1"
TYPES = {cls.__name__: cls for cls in (
    SourceBasis, SourceSpan, Token, CatCode, TokenKind, PrimitiveMeaning, DefinitionSpec,
    Register, Glue, FontParameters, IntegerValue, Cell, contracts.MouthBaseline,
    contracts.StoredDefinition, contracts.TokenListMeaning, contracts.CharacterCodeMeaning,
    contracts.BoundMeaning, contracts.UndefinedMeaning, contracts.ConditionalRule)}


def implementation_digest():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted([*root.joinpath("engine").rglob("*.py"), *root.joinpath("reading").rglob("*.py")]):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


class Graph:
    def __init__(self):
        self.nodes, self.seen = [], {}

    def encode(self, value):
        if value is None or type(value) in {str, int, bool}:
            return value
        if id(value) in self.seen:
            return {"ref": self.seen[id(value)]}
        index = len(self.nodes)
        self.seen[id(value)] = index
        self.nodes.append(None)
        if isinstance(value, Enum) and type(value).__name__ in TYPES:
            node = {"type": type(value).__name__, "enum": value.value}
        elif isinstance(value, (tuple, list, frozenset)):
            node = {"type": type(value).__name__, "items": [self.encode(v) for v in value]}
        elif type(value) is dict:
            node = {"type": "dict", "items": [[self.encode(k), self.encode(v)] for k, v in value.items()]}
        elif type(value).__name__ in TYPES and TYPES[type(value).__name__] is type(value) and is_dataclass(value):
            node = {"type": type(value).__name__, "fields": {f.name: self.encode(getattr(value, f.name)) for f in fields(value)}}
        else:
            raise ValueError(f"Unsupported format snapshot value: {type(value).__name__}")
        self.nodes[index] = node
        return {"ref": index}

    @staticmethod
    def decode(nodes, root):
        if not isinstance(nodes, list) or len(nodes) > 1000000:
            raise ValueError("Invalid or excessive snapshot graph")
        cache, active = {}, set()
        def value(item):
            if item is None or type(item) in {str, int, bool}:
                return item
            if not isinstance(item, dict) or set(item) != {"ref"} or type(item["ref"]) is not int:
                raise ValueError("Invalid snapshot reference")
            index = item["ref"]
            if not 0 <= index < len(nodes) or index in active:
                raise ValueError("Invalid or cyclic snapshot graph")
            if index in cache:
                return cache[index]
            active.add(index)
            node = nodes[index]
            kind = node["type"]
            if kind == "dict" and set(node) == {"type", "items"}:
                result = {value(k): value(v) for k, v in node["items"]}
            elif kind in {"list", "tuple", "frozenset"} and set(node) == {"type", "items"}:
                result = {"list": list, "tuple": tuple, "frozenset": frozenset}[kind](value(v) for v in node["items"])
            elif kind in TYPES and issubclass(TYPES[kind], Enum) and set(node) == {"type", "enum"}:
                result = TYPES[kind](node["enum"])
            elif kind in TYPES and is_dataclass(TYPES[kind]) and set(node) == {"type", "fields"}:
                if set(node["fields"]) != {f.name for f in fields(TYPES[kind])}:
                    raise ValueError("Snapshot fields do not match the engine schema")
                result = TYPES[kind](**{k: value(v) for k, v in node["fields"].items()})
            else:
                raise ValueError("Unknown snapshot node type")
            active.remove(index)
            cache[index] = result
            return result
        return value(root)


def save(context, *, sources, origins=(), next_occurrence=0):
    from .hooks import HookState
    from ..reading.configuration import ConfigurationState
    if (context.scope_depth or context.after_assignment is not None or context.after_groups or
            any(context.read_streams.streams.values()) or context.read_streams.uncertain or
            context.recovery_contexts or context._uncertain_prefixes or context.expl3_active or
            context.state_cells.default_uncertain or context.token_registers.default_uncertain or
            context._environments or context._capture_settings or
            vars(context.hooks) != vars(HookState()) or
            vars(context.configurations) != vars(ConfigurationState())):
        raise ValueError("Snapshot requires settled core state without live inputs or unresolved extensions")
    if context.baseline.name != "tex82_initex" or not context.primitive_initial_state:
        raise ValueError("Snapshot requires the explicit INITEX baseline")
    graph = Graph()
    state = {"baseline": context.baseline, "catcodes": {**context.catcodes._assignments,
                                                     **{chr(i): context.catcodes[chr(i)] for i in range(256)}},
             "endlinechar": context.endlinechar, "meanings": context._meanings,
             "integers": context.integer_parameters.values, "tokens": context.token_registers.values,
             "cells": {k: v for k, v in context.state_cells.values.items()
                       if k not in {"format_messages", "jobname", "prepared_magnification"}},
             "fonts": context.fonts.values,
             "latest_font": context.fonts.latest, "font_identifiers": context.fonts.identifiers,
             "origins": tuple(origins), "next_occurrence": next_occurrence}
    root = graph.encode(state)
    if any(node.get("fields", {}).get("uncertain") is not None for node in graph.nodes):
        raise ValueError("Snapshot cannot publish uncertain state")
    data = {"schema": SCHEMA, "implementation": implementation_digest(), "profile": context.engine_profile.record(),
            "sources": sources, "root": root, "nodes": graph.nodes}
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return json.dumps({"sha256": hashlib.sha256(payload.encode()).hexdigest(), "payload": payload}, separators=(",", ":")) + "\n"


def restore(text, *, sources):
    from .profiles import engine_profile
    if len(text) > 64000000:
        raise ValueError("Snapshot exceeds the size budget")
    envelope = json.loads(text)
    payload = envelope["payload"]
    if hashlib.sha256(payload.encode()).hexdigest() != envelope["sha256"]:
        raise ValueError("Snapshot checksum mismatch")
    data = json.loads(payload)
    if data["schema"] != SCHEMA or data["implementation"] != implementation_digest():
        raise ValueError("Snapshot schema or engine implementation changed")
    if data["sources"] != sources:
        raise ValueError("Snapshot source inventory changed")
    profile = engine_profile(data["profile"]["name"])
    if profile.record() != data["profile"]:
        raise ValueError("Snapshot primitive profile changed")
    state = Graph.decode(data["nodes"], data["root"])
    context = ReaderContext(baseline=state["baseline"], engine_profile=profile, primitive_initial_state=True,
                            catcodes=CatcodeTable(state["catcodes"], default=12), endlinechar=state["endlinechar"],
                            initial_meanings=state["meanings"])
    context.integer_parameters.values = state["integers"]
    context.token_registers.values = state["tokens"]
    context.state_cells.values = state["cells"]
    context.fonts.values, context.fonts.latest = state["fonts"], state["latest_font"]
    context.fonts.identifiers = state["font_identifiers"]
    return context, state["origins"], state["next_occurrence"]
