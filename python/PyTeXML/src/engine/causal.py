"""Opt-in execution evidence: occurrence identities, versioned reads and edges.

This records the implemented observation seams, not a complete TeX dependency
graph. Rollback retains attempted events and restores the live version frontier.
Source coordinates never double as event identities or semantic hashes.
"""
from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from functools import wraps
import hashlib
import json
import uuid


def semantic(value):
    from ..reading.spans import SourceSpan, SourceBasis
    from ..reading.tex_reader import Token
    from ..reading.contracts import StoredDefinition, TokenListMeaning
    from .meanings import meaning_key, token_key
    if isinstance(value, Token):
        return {"identity": semantic(token_key(value)), "expansion_suppressed": value.expansion_suppressed}
    if isinstance(value, (StoredDefinition, TokenListMeaning)):
        key = meaning_key(value, {})
        if key is not None:
            return semantic(key)
    if isinstance(value, (SourceSpan, SourceBasis)):
        return {"coordinate": "excluded"}
    if isinstance(value, Enum):
        return value.value
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {str(k): semantic(v) for k, v in sorted(value.items(), key=lambda p: str(p[0]))}
    if isinstance(value, (tuple, list)):
        return [semantic(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((semantic(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if is_dataclass(value):
        return {"type": type(value).__name__, **{f.name: semantic(getattr(value, f.name)) for f in fields(value)
                if f.name not in {"span", "origin_event", "size", "control_word"}}}
    raise TypeError(f"No semantic record codec for {type(value).__name__}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def location(span):
    return None if span is None else {"source": span.basis.source_id, "occurrence": span.basis.occurrence_id,
                                      "start": span.start, "end": span.end, "unit": "decoded_codepoint"}


class Recorder:
    def __init__(self):
        self.run_id = uuid.uuid4().hex
        self.events, self.versions, self.edges, self.stack = [], [], [], []
        self.live, self.tokens = {}, {}
        self.token_journal, self.scopes = [], []
        self.gaps = []

    def value(self, value):
        try:
            return semantic(value)
        except TypeError as error:
            self.gaps.append(str(error))
            return {"unrecorded_type": type(value).__name__}

    def edge(self, source, relation, target):
        if source is not None and target is not None:
            self.edges.append({"source": source, "relation": relation, "target": target})

    def begin(self, operation, operands=None, span=None, *, cause=None):
        identity = f"e{len(self.events)}"
        event = {"id": identity, "operation": operation, "operands": self.value(operands),
                 "source": location(span), "status": "open"}
        self.events.append(event)
        if self.stack:
            self.edge(self.stack[-1], "contains", identity)
        self.edge(identity, "consumes_token", cause)
        self.stack.append(identity)
        return event

    def end(self, event, status="committed"):
        if not self.stack or self.stack[-1] != event["id"]:
            raise ValueError("Causal operation scopes must close in order")
        self.stack.pop()
        if event["status"] != "rolled_back":
            event["status"] = status

    @contextmanager
    def event(self, operation, operands=None, span=None, *, cause=None):
        event = self.begin(operation, operands, span, cause=cause)
        try:
            yield event
        except BaseException as error:
            event["failure"] = getattr(error, "reason", type(error).__name__)
            self.end(event, "failed")
            raise
        else:
            self.end(event)

    def point(self, operation, operands=None, span=None):
        with self.event(operation, operands, span) as event:
            return event["id"]

    def token(self, token):
        if token is None:
            return None
        saved = self.tokens.get(id(token))
        if saved is not None:
            return saved[1]
        identity = self.point("token_source", token, token.span)
        self.tokens[id(token)] = (token, identity)  # Keep identity alive during the run.
        self.token_journal.append(id(token))
        return identity

    def insert(self, tokens, *, reason="expansion"):
        result = []
        producer = self.stack[-1] if self.stack else None
        for token in tokens:
            origin = self.token(token)
            copied = replace(token)
            identity = self.point("token_insert", {"token": token, "reason": reason}, token.span)
            self.edge(identity, "derived_from_token", origin)
            self.edge(identity, "produced_by", producer)
            self.tokens[id(copied)] = (copied, identity)
            self.token_journal.append(id(copied))
            result.append(copied)
        return tuple(result)

    def rebase(self, old, new):
        self.tokens[id(new)] = (new, self.token(old))
        self.token_journal.append(id(new))

    def arguments(self, arguments):
        invocation = self.stack[-1]
        for number, argument in enumerate(arguments, 1):
            tokens = [self.token(part) for part in argument]
            captured = self.point("macro_argument", {"position": number, "tokens": argument})
            self.edge(captured, "argument_of", invocation)
            for token in tokens:
                self.edge(captured, "captures_token", token)

    def write(self, key, value, *, scope="global", relation="supersedes"):
        normalized = self.value(value)
        previous = self.live.get(key)
        if scope == "global":
            for saved in self.scopes:
                saved.pop(key, None)
        elif scope == "local" and self.scopes:
            self.scopes[-1].setdefault(key, previous)
        identity = f"v{len(self.versions)}"
        self.versions.append({"id": identity, "key": key, "value": normalized,
                              "sha256": digest(normalized), "scope": scope, "status": "committed"})
        self.live[key] = identity
        self.edge(identity, relation, previous)
        self.edge(identity, "written_by", self.stack[-1] if self.stack and scope not in {"input", "unobserved"} else None)
        if self.stack and scope not in {"input", "unobserved"}:
            self.edge(self.stack[-1], "writes_version", identity)
        if scope == "restore" and self.scopes:
            self.edge(identity, "restores_from", self.scopes[-1].get(key))
        return identity

    def read(self, key, value):
        normalized = self.value(value)
        current = self.live.get(key)
        if current is None:
            current = self.write(key, value, scope="input")
        elif self.versions[int(current[1:])]["value"] != normalized:
            # A direct table update outside an instrumented writer remains
            # visible; it cannot masquerade as an established causal writer.
            self.gaps.append("unobserved_write:" + key)
            current = self.write(key, value, scope="unobserved")
        observation = self.point("state_read", {"key": key})
        self.edge(observation, "reads_version", current)

    def checkpoint(self):
        return len(self.events), len(self.versions), dict(self.live), len(self.token_journal), [dict(s) for s in self.scopes]

    def rollback(self, saved):
        events, versions, live, tokens, scopes = saved
        for event in self.events[events:]:
            event["status"] = "rolled_back"
        for version in self.versions[versions:]:
            version["status"] = "rolled_back"
        self.live = dict(live)
        self.scopes = [dict(s) for s in scopes]
        for identity in self.token_journal[tokens:]:
            self.tokens.pop(identity, None)
        del self.token_journal[tokens:]
        identity = self.point("rollback", {"events": len(self.events) - events,
                                           "versions": len(self.versions) - versions})
        for event in self.events[events:]:
            if event["id"] != identity:
                self.edge(identity, "rolls_back", event["id"])

    def receipt(self, *, status, output, state):
        return {"schema": "pytexml-causal-record/1", "run_id": self.run_id, "status": status,
                "events": self.events, "versions": self.versions, "edges": self.edges,
                "frontier": dict(self.live), "output": self.value(output), "state": self.value(state),
                "gaps": sorted(set(self.gaps)),
                "coverage": {"reads": ["resolved_meanings", "integer_cells", "token_cells", "state_cells"],
                             "writes": ["meanings", "integer_cells", "token_cells", "state_cells", "catcode_assignments", "scope_restoration"],
                             "complete_dependency_tracking": False,
                             "untracked": ["mouth catcode reads", "font metric internals", "hook/configuration internals", "external I/O"]}}

    def output_node(self, node):
        identity = self.point("output_node", {"kind": node.kind, "attributes": node.attributes, "payload": node.payload}, node.span)
        self.edge(identity, "constructed_from", node.origin_event)
        for child in node.children:
            self.edge(identity, "node_contains", self.output_node(child))
        return identity

    def seed(self, context):
        for char, value in context.catcodes._assignments.items():
            self.write("catcode:" + str(ord(char)), value, scope="input")
        for key, value in selected_state(context)["meanings"].items():
            self.write("meaning:" + key, value, scope="input")
        for namespace, values in (("integer_parameters", context.integer_parameters.values),
                                  ("token_registers", context.token_registers.values),
                                  ("state_cells", context.state_cells.values)):
            for key, cell in values.items():
                value = cell.replacement_tokens if namespace == "token_registers" else cell.value
                self.write(namespace + ":" + key, value, scope="input")


def dispatch_record(handler):
    @wraps(handler)
    def execute(host, event, *args, **kwargs):
        recorder = getattr(host.context, "recorder", None)
        if recorder is None:
            return handler(host, event, *args, **kwargs)
        token = recorder.token(event.token)
        with recorder.event("dispatch", event.token, event.span, cause=token):
            return handler(host, event, *args, **kwargs)
    return execute


def expansion_record(handler):
    @wraps(handler)
    def execute(cursor, token, definition, *args, **kwargs):
        recorder = getattr(cursor.context, "recorder", None)
        if recorder is None:
            return handler(cursor, token, definition, *args, **kwargs)
        with recorder.event("macro_expand", {"name": token.value, "definition": definition}, token.span,
                            cause=recorder.token(token)) as event:
            recorder.read("meaning:" + str(token.kind.value) + ":" + token.value, definition)
            return handler(cursor, token, definition, *args, **kwargs)
    return execute


def cell_read(table, key, value):
    recorder = getattr(table, "recorder", None)
    if recorder is not None:
        recorder.read(table.record_namespace + ":" + str(key), value)
    return value


def cell_write(table, key, value, *, global_=False, restore=False, update=False):
    recorder = getattr(table, "recorder", None)
    if recorder is not None:
        recorder.write(table.record_namespace + ":" + str(key), value,
                       scope="restore" if restore else "update" if update else "global" if global_ else "local",
                       relation="restores_after" if restore else "supersedes")


def attach(context, recorder):
    context.recorder = recorder
    for namespace in ("integer_parameters", "token_registers", "state_cells"):
        table = getattr(context, namespace)
        table.recorder, table.record_namespace = recorder, namespace


def selected_state(context):
    return {"meanings": {str(kind.value) + ":" + name: value for (kind, name), value in context._meanings.items()},
            "integers": {k: v.value for k, v in context.integer_parameters.values.items()},
            "tokens": {k: v.replacement_tokens for k, v in context.token_registers.values.items()},
            "cells": {k: v.value for k, v in context.state_cells.values.items() if k != "format_messages"},
            "lexical": {"default": context.catcodes.default, "layers": context.catcodes._layers,
                        "assignments": context.catcodes._assignments, "endlinechar": context.endlinechar},
            "scope_depth": context.scope_depth}
