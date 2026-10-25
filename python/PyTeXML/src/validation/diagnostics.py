"""Evidence-preserving log normalization and declarative diagnostic recognition.

No TeX package semantics live here. Unrecognized messages stay visible. A hard
wrap is inferred from the configured width, not from an arbitrary newline;
raw byte/line ranges and the inferred joins remain available for review.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from ..yaml_io import load_mapping, validate_resource_identity

RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources/validation/diagnostics"


@lru_cache(maxsize=8)
def load_rules(name="tectonic", root=RESOURCE_ROOT):
    path = Path(root) / (name + ".yaml")
    data = load_mapping(path)
    validate_resource_identity(data, path)
    version = data["identity"].get("version")
    if data.get("schema") != "pytexml-diagnostics/1" or type(version) is not int or version < 1:
        raise ValueError(f"Unsupported diagnostic schema/version: {path}")
    expected = {"schema", "identity", "normalization", "rules"} if "rules" in data else {"schema", "identity", "events"}
    if set(data) != expected or set(data["identity"]) != {"name", "version"}:
        raise ValueError(f"Unexpected diagnostic resource fields: {path}")
    codes = set()
    for rule in [*data.get("rules", []), *data.get("events", {}).values()]:
        if not isinstance(rule.get("code"), str) or rule["code"] in codes:
            raise ValueError(f"Missing/duplicate diagnostic code: {path}")
        codes.add(rule["code"])
        if not rule.get("category") or set(rule.get("remediation", {})) != {"area", "action", "verify"}:
            raise ValueError(f"Incomplete diagnostic knowledge: {rule['code']}")
        if "patterns" in rule:
            if set(rule) != {"code", "phase", "component", "severity", "role", "category", "patterns", "signature", "witnesses", "remediation"}:
                raise ValueError(f"Unexpected log rule fields: {rule['code']}")
            if (rule["phase"] not in {"tex_compilation", "pdf_generation"} or
                    rule["severity"] not in {"warning", "error"} or
                    rule["role"] not in {"primary", "supporting", "terminal"} or
                    rule["category"] not in {"source_diagnostic", "environment_limitation", "unclassified"}):
                raise ValueError(f"Invalid diagnostic vocabulary: {rule['code']}")
            if not rule["patterns"] or not rule.get("witnesses"):
                raise ValueError(f"Log rules need witnessed patterns: {rule['code']}")
            for pattern in rule["patterns"]:
                regex = re.compile(pattern)
                if regex.match("") or not set(rule["signature"]).issubset(regex.groupindex):
                    raise ValueError(f"Invalid diagnostic signature: {rule['code']}")
        elif set(rule) != {"code", "category", "remediation"} or rule["category"] not in {"payload_dependency_failure", "insufficient_evidence"}:
            raise ValueError(f"Invalid audit event: {rule['code']}")
    if "normalization" in data:
        normal = data["normalization"]
        if type(normal["wrap_columns"]) is not int or normal["wrap_columns"] <= 0:
            raise ValueError("wrap_columns must be a positive integer")
        for field in ("boundary", "wrapped_prefix", "diagnostic_start", "location"):
            re.compile(normal[field])
    return data


def rule_identity(rules):
    return {**rules["identity"], "sha256": hashlib.sha256(
        json.dumps(rules, sort_keys=True).encode()).hexdigest()}


def normalize_log(raw: bytes, configuration=None):
    """Join width-limited continuations without altering tokens or losing offsets.

    Width is measured in Unicode characters for this XeTeX console profile.
    Blank lines and known record starts are hard boundaries. A naturally ended
    line exactly at the wrap width is inherently ambiguous: joins are explicitly
    recorded as inferences rather than claimed as recovered engine metadata.
    """
    configuration = configuration or load_rules()["normalization"]
    boundary = re.compile(configuration["boundary"])
    wrapped_prefix = re.compile(configuration["wrapped_prefix"])
    records, offset = [], 0
    previous_full = False
    for number, physical in enumerate(raw.splitlines(keepends=True), 1):
        content = physical.rstrip(b"\r\n")
        text = content.decode("utf-8", errors="surrogateescape")
        join = (records and previous_full and
                text and records[-1]["text"] and not boundary.match(text))
        if join:
            record = records[-1]
            record["text"] += text
            record["line_end"] = number
            record["byte_end"] = offset + len(physical)
            record["inferred_joins"].append(number - 1)
        else:
            records.append({"text": text, "line_start": number, "line_end": number,
                            "byte_start": offset, "byte_end": offset + len(physical),
                            "inferred_joins": []})
        prefix = wrapped_prefix.match(text)
        previous_full = (len(text) == configuration["wrap_columns"] or
                         (prefix is not None and len(text) - prefix.end() == configuration["wrap_columns"]))
        offset += len(physical)
    return records


def parse_log(raw: bytes, *, log_name="compiler.log", rules=None):
    rules = rules or load_rules()
    records = normalize_log(raw, rules["normalization"])
    start = re.compile(rules["normalization"]["diagnostic_start"])
    location = re.compile(rules["normalization"]["location"])
    diagnostics, grouped = [], {}
    for record in records:
        text = record["text"]
        if not start.match(text):
            continue
        matches = [(rule, match) for rule in rules["rules"] for pattern in rule["patterns"]
                   if (match := re.search(pattern, text))]
        if not matches and not start.match(text):
            continue
        if not matches:
            severity = "warning" if text.startswith("warning:") else "error"
            matches = [({"code": "log.unclassified", "phase": "unknown", "component": "unknown",
                         "severity": severity, "role": "unclassified", "category": "unclassified",
                         "signature": [], "remediation": {"area": "investigation",
                         "action": "Inspect the retained message; add knowledge only with a witnessed fixture.",
                         "verify": "Re-run the failed check after identifying its cause."}}, None)]
        for rule, match in matches:
            details = {key: value for key, value in (match.groupdict() if match else {}).items() if value is not None}
            signature = {key: details[key] for key in rule["signature"]}
            key = (rule["code"], tuple(sorted(details.items())), text if match is None else "")
            if key not in grouped:
                diagnostic = {key: rule[key] for key in ("code", "phase", "component", "severity", "role", "category", "remediation")}
                diagnostic.update(id=f"d{len(diagnostics) + 1}", details=details, signature=signature,
                                  rule={**rules["identity"], "code": rule["code"]}, evidence=[], related=[])
                diagnostics.append(diagnostic)
                grouped[key] = diagnostic
            diagnostic = grouped[key]
            evidence = {key: record[key] for key in ("line_start", "line_end", "byte_start", "byte_end", "inferred_joins")}
            evidence.update(log=log_name, message=text,
                            raw=raw[record["byte_start"]:record["byte_end"]].decode("utf-8", errors="surrogateescape"))
            if source := location.match(text):
                # The adapter inserts one bootstrap line in its staged main.
                # Keep this location explicitly staged; callers may rebase it.
                evidence["location"] = {"file": source["file"], "line": int(source["line"]), "basis": "staged_source"}
            diagnostic["evidence"].append(evidence)
    for diagnostic in diagnostics:
        if diagnostic["role"] in {"terminal", "supporting"}:
            diagnostic["related"] = [{"id": item["id"], "relation": "same_phase"}
                for item in diagnostics if item["role"] == "primary" and item["phase"] == diagnostic["phase"]]
    return {"rules": rule_identity(rules), "parsed_bytes": len(raw),
            "log": log_name, "sha256": hashlib.sha256(raw).hexdigest(),
            "undecodable_bytes": sum(0xDC80 <= ord(c) <= 0xDCFF for c in raw.decode("utf-8", errors="surrogateescape")),
            "normalization": {"wrap_columns": rules["normalization"]["wrap_columns"],
                              "inferred_joins": sum(len(r["inferred_joins"]) for r in records)},
            "diagnostics": diagnostics}


def audit_diagnostics(audit):
    """Structured audit facts use the same data-owned explanation vocabulary."""
    rules = load_rules("relocation")
    events = [("external_input", path) for path in audit.get("outside", [])]
    events += [("missing_input", path) for path in audit.get("missing", [])]
    if audit["status"] in rules["events"]:
        events.append((audit["status"], None))
    return [{"id": f"a{index}", **rules["events"][event], "phase": "dependency_audit",
             "component": "pytexml", "severity": "error", "role": "primary",
             "details": {"path": path} if path else {}, "signature": {},
             "rule": {**rule_identity(rules), "event": event},
             "evidence": [{"check": "dependency_audit", "path": path}], "related": []}
            for index, (event, path) in enumerate(events, 1)]
