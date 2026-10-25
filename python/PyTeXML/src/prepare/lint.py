"""Bounded lint over established reading evidence and explicitly checked edits.

No raw-document regex scan, package execution, or guessing of missing syntax.
Policy selects repairs; the dispatcher alone owns routing and cursor resumption.
"""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from ..yaml_io import load_mapping, validate_resource_identity
from ..reading.tex_reader import CatCode, EventKind, InvalidCharacterError, ReadEvent, TexReader, TokenKind
from .emission import SourcePiece


RULE_PATH = Path(__file__).resolve().parents[2] / "resources/lint/preparation.yaml"


@lru_cache(maxsize=8)
def load_rules(path=RULE_PATH):
    path = Path(path)
    data = load_mapping(path)
    validate_resource_identity(data, path)
    if (set(data) != {"schema", "identity", "rules"} or data["schema"] != "pytexml-lint-rules/1"
            or set(data["identity"]) != {"name", "version"}
            or type(data["identity"]["version"]) is not int or data["identity"]["version"] < 1
            or not isinstance(data["rules"], list)):
        raise ValueError(f"Invalid lint catalog: {path}")
    reasons, codes = set(), set()
    for rule in data["rules"]:
        if not isinstance(rule, dict) or set(rule) != {"code", "reasons", "severity", "repair", "remediation"}:
            raise ValueError(f"Invalid lint rule fields: {path}")
        if (not isinstance(rule["code"], str) or not rule["code"] or rule["code"] in codes
                or rule["severity"] not in ("warning", "error")
                or rule["repair"] not in (None, "drop_invalid_character")
                or not isinstance(rule["remediation"], str) or not rule["remediation"]
                or not isinstance(rule["reasons"], list) or not rule["reasons"]):
            raise ValueError(f"Invalid lint rule: {path}")
        codes.add(rule["code"])
        for reason in rule["reasons"]:
            if not isinstance(reason, str) or not reason or reason in reasons:
                raise ValueError(f"Missing/duplicate lint reason: {path}")
            reasons.add(reason)
    return data


def _tokens(reader, *, recover=False):
    result = []
    while True:
        try:
            event = reader.next_event()
        except InvalidCharacterError as error:
            if not recover:
                raise
            event = reader.discard_invalid_character(error)
        if event is None:
            return result, reader.state
        if event.token is not None:
            t = event.token
            result.append((t.kind.value, t.value, t.catcode))


def checked_character_deletion(text, span, previous, reader, error):
    """A deliberately small, locally complete token-equivalence proof.

    Admit one literal invalid character between adjacent, already ordinary ASCII
    alphanumerics. This excludes control-word joins, caret decoding, physical-line
    changes, synthetic endlines and all partial scanner/header captures.
    """
    if error is None or error.span != span:
        return False
    if not isinstance(previous, ReadEvent) or previous.kind != EventKind.TOKEN:
        return False
    token = previous.token
    if (token is None or token.kind != TokenKind.CHARACTER or token.transformed
            or token.span.end != span.start or token.span.end - token.span.start != 1
            or span.end - span.start != 1 or span.end >= len(text)):
        return False
    left, middle, right = text[span.start - 1:span.end + 1]
    if middle in "\r\n" or middle != error.character or reader.catcodes[middle] != CatCode.INVALID:
        return False
    if any(not c.isascii() or not c.isalnum() or reader.catcodes[c] not in (CatCode.LETTER, CatCode.OTHER)
           for c in (left, right)):
        return False
    if token.value != left or token.catcode != reader.catcodes[left]:
        return False
    before = TexReader(left + middle + right, catcodes=reader.catcodes.copy(), endline_char=-1)
    after = TexReader(left + right, catcodes=reader.catcodes.copy(), endline_char=-1)
    before.state = after.state = previous.state_before
    # The reference is TeX's explicit invalid-character discard recovery, not a
    # claim that an erroneous source already has a valid interpretation.
    return _tokens(before, recover=True) == _tokens(after)


class PreparationLint:
    def __init__(self, policy):
        self.policy = policy
        catalog = load_rules()
        self.rules = {reason: rule for rule in catalog["rules"] for reason in rule["reasons"]}
        self.report = {"schema": "pytexml-lint/1", "mode": policy.mode,
            "catalog": {**catalog["identity"], "sha256": sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()},
            "scope": "source_visible_reading_evidence", "findings": []}
        self._records, self._spans, self._repairs = {}, {}, {}

    def record(self, session, span, reason, detail, unit_id, *, evidence=None):
        if self.policy.mode == "off" or reason not in self.rules:
            return None
        key = (unit_id, reason, (evidence or {}).get("target"))
        if key in self._records:
            return self._records[key]
        rule = self.rules[reason]
        record = {"id": f"lint-{len(self._records) + 1}", "unit_id": unit_id,
            "code": rule["code"], "severity": rule["severity"], "reason": reason, "detail": detail,
            "source": span.basis.source_id, "occurrence": span.basis.occurrence_id,
            "start": span.start, "end": span.end, "line": session.line(span),
            "location_status": "pending", "locations": [],
            "remediation": rule["remediation"], "evidence": evidence or {},
            "repair": {"name": rule["repair"], "status": "not_available"}}
        self._records[key] = record
        self._spans[record["id"]] = span
        self.report["findings"].append(record)
        return record

    def repair_boundary(self, session, boundary):
        """Return a recovery event only after proof and explicit policy admission."""
        if boundary.reason != "invalid_character" or self.policy.mode == "off":
            return None
        span = boundary.span
        record = self.record(session, span, boundary.reason, boundary.detail, boundary.unit_id)
        reader = session.dispatcher.reader
        previous = session._observations[span.basis][-1] if session._observations[span.basis] else None
        # Earlier unknown behavior can change catcodes or consume later input.
        # This first repair does not attempt to prove through those dependencies.
        failure = session.dispatcher.lexical_failure(boundary)
        if not session.frames[-1].emit:
            rejected = "retained_local_code"
        elif session.manifest.requirements or session.manifest.unresolved:
            rejected = "earlier_unresolved_or_deferred_work"
        elif not isinstance(reader, TexReader) or failure is None:
            rejected = "not_an_ordinary_character_fetch"
        elif not checked_character_deletion(session.raw(span.basis.whole), span, previous, reader, failure):
            rejected = "lexical_precondition_or_postcondition"
        else:
            rejected = None
        eligible = rejected is None
        record["repair"].update(status="proposed" if eligible else "ineligible",
            rejection_reason=rejected,
            authorized=self.policy.mode == "repair" and "drop_invalid_character" in self.policy.repairs,
            precondition="ordinary adjacent alphanumeric tokens; literal catcode-15 character; no prior unresolved/deferred work",
            postcondition="same neighboring tokens and exit mouth state as explicit invalid-character discard recovery")
        if not eligible:
            return None
        record["repair"].update(before=session.raw(span), after="", checked=True)
        if self.policy.mode != "repair" or "drop_invalid_character" not in self.policy.repairs:
            return None
        event = session.dispatcher.discard_invalid_character(boundary)
        piece = SourcePiece("", span, session.line(span), "LINT_REPAIR")
        session.pieces.append(piece)
        session._omit(span, f"Checked lint repair {record['id']}: drop_invalid_character")
        record["repair"]["status"] = "applied_in_memory"
        text = session.raw(span.basis.whole)
        self._repairs[record["id"]] = (piece.key, text[span.start - 1] + text[span.end])
        return event

    def finalize(self, pieces, locations, master):
        offsets, offset = {}, 0
        for piece in pieces:
            offsets[piece.key] = offset
            offset += len(piece.text)
        for record in self.report["findings"]:
            record.update(locations.project(self._spans[record["id"]]))
            if record["id"] in self._repairs:
                key, expected = self._repairs[record["id"]]
                if key not in offsets:
                    record["repair"]["status"] = "not_emitted"
                    continue
                position = offsets[key]
                if master[position - 1:position + 1] != expected:
                    raise ValueError(f"Lint repair {record['id']} failed its final emission postcondition")
                record["repair"]["status"] = "applied"
                record["repair"]["postcondition_verified"] = True
                record.update(location_status="mapped", locations=[{"artifact": "master.tex",
                    "start": position, "end": position, "precision": "exact"}])
            for related in record["evidence"].get("related", []):
                related.update(locations.project(self._spans[related["span_id"]]))

    def related(self, session, unit_id):
        span = session.units.records[unit_id].span
        key = "unit:" + unit_id
        self._spans[key] = span
        return {"unit_id": unit_id, "span_id": key, "source": span.basis.source_id,
                "occurrence": span.basis.occurrence_id, "start": span.start, "end": span.end,
                "location_status": "pending", "locations": []}
