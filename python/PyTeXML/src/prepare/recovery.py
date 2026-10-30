"""Occurrence-owned resource outcomes and recovery through ordinary source pieces.

Facts live in the existing dependency/requirement records. The small runtime list
only keeps source spans for final emission, so rolling back a speculative splice
cannot erase an observed failure or strand its output marker.
"""
from ..reading.contracts import ReadingIssue, ScannedArgument
from ..engine.checkpoints import Attempt, Checkpoint, LanguageState
from .checkpoints import PreparationState, snapshot
from .records import source_reference


PROGRAM_KINDS = {"input", "package", "class", "formatted_bibliography", "source_command"}
RESOURCE_ACTIONS = {
    "source_input": "input", "source_include": "input",
    "source_import": "input", "source_subimport": "input",
    "external_literal": "external_literal", "asset_reference": "asset",
    "bibliography": "bibliography", "package_load": "package",
    "document_class": "class", "class_load": "class",
}


class ResourceFailure(ReadingIssue):
    """A diagnosed source-resource outcome, never an arbitrary implementation error."""

    def __init__(self, reason, detail, *, requested=None, outcome="unresolved", search=None,
                 resolved=None):
        super().__init__(reason, detail)
        self.requested, self.outcome = requested, outcome
        self.search, self.resolved = search or {}, resolved


class RecoveryCoordinator:
    """Rollback, commit failure evidence, then resume at an established boundary.

    Handlers report failures. This owner alone decides whether to replace a
    fully scanned request or preserve its source. Later materialization uses
    request-owned participants and never rewinds the completed language pass.
    """
    def __init__(self, session):
        self.session = session
        self.serial = 0
        self.committed = []

    def next_identity(self):
        self.serial += 1
        return f"resource-{self.serial}"

    def begin(self, *participants, language=False, preparation=False, boundary="resource_request"):
        return Attempt(Checkpoint(*([LanguageState(self.session.dispatcher)] if language else []),
            *([PreparationState(self.session)] if preparation else []), *participants, boundary=boundary))

    def recover(self, attempt, command, error, **options):
        if command.unit_id in attempt.recoveries:
            return attempt.recoveries[command.unit_id]
        session = self.session
        evidence = session.units.evidence(command.unit_id)
        record = options.pop("record", None)
        if record is None:
            resolved = getattr(error, "resolved", None) or getattr(getattr(error, "file_event", None), "resolved", None)
            record = next((r for r in reversed(session.manifest.dependencies)
                           if r["unit_id"] == command.unit_id and r.get("outcome") == "present"
                           and (resolved is not None and r.get("target") == resolved
                                or getattr(error, "requested", None) is not None
                                and r.get("requested") == error.requested)
                           and (options.get("kind") is None or r["kind"] == options["kind"])), None)
        record = snapshot(record)
        attempt.rollback()
        session.units.retain_evidence(evidence)
        # A caller must supply a continuation only after scanning the complete
        # request. Unknown boundaries are handled by whole-input retention.
        attempt.resume()
        if attempt.retention_required:
            options["retain"] = True
        if not isinstance(error, ResourceFailure) or (command.action not in RESOURCE_ACTIONS and "kind" not in options):
            session.diagnose(command.span, error.reason, error.detail, unit_id=command.unit_id,
                causes=error.causes, evidence=getattr(error, "evidence", None))
            if command.action not in RESOURCE_ACTIONS:
                options.setdefault("kind", "source_command")
            options["retain"] = True
            failure = ResourceFailure(error.reason, error.detail, resolved=getattr(error, "resolved", None))
        else:
            failure = error
        if record is not None:
            existing = next((r for r in session.manifest.dependencies if r["item_id"] == record["item_id"]), None)
            if existing is None:
                session.manifest.dependencies.append(record)
            else:
                record = existing
        result = _record_recovery(session, command, failure, record=record, **options)
        result["recovery"]["checkpoint"] = attempt.checkpoint.boundary
        event = getattr(error, "file_event", None)
        if event is not None:
            from .preservation import retain_source
            retain_source(session, session.store.root / event.resolved,
                          import_dir=getattr(error, "import_dir", None))
            event.invalidate_retained_effects(session.dispatcher)
            session.manifest.file_events.append({**event.record("retained"), "reason": error.reason})
        elif not isinstance(error, ResourceFailure) and failure.resolved is not None:
            from .preservation import retain_source
            retain_source(session, session.store.root / failure.resolved,
                          import_dir=getattr(error, "import_dir", None))
        attempt.recoveries[command.unit_id] = result
        requirement = next(r for r in session.manifest.requirements if r.get("item_id") == result["item_id"])
        causes = {span: cause for span, cause in session.units.uncertainty.items()
                  if cause.id in result["cause_ids"]}
        units = {unit.id: unit for unit in session.units.evidence(command.unit_id)}
        for cause in causes.values():
            units.update((unit.id, unit) for unit in session.units.evidence(cause.unit_id))
        self.committed.append((command, result, requirement, tuple(units.values()), causes,
            tuple(c for c in session.manifest.recovery_contexts
                  if c["id"] in result["recovery"]["assumptions"])))
        return result

    def restore_committed(self):
        """Reconcile durable failures after an enclosing speculative rollback."""
        session = self.session
        def keep(rows, record, key):
            index = next((i for i, row in enumerate(rows) if row.get(key) == record[key]), None)
            if index is None:
                rows.append(record)
            else:
                rows[index] = record
        for command, record, requirement, units, causes, assumptions in self.committed:
            keep(session.manifest.dependencies, record, "item_id")
            keep(session.manifest.requirements, requirement, "id")
            session.units.retain_evidence(units)
            session.units.uncertainty.update(causes)
            for assumption in assumptions:
                keep(session.manifest.recovery_contexts, assumption, "id")
            ids = tuple(a["id"] for a in assumptions)
            if any(identifier not in session.context.recovery_contexts for identifier in ids):
                session.context.invalidate_meanings(session.context.meaning_names(), command.span)
                session.dispatcher.defer_effects(command.span, reason=record["causes"][0]["reason"],
                                                detail=record["causes"][0]["detail"])
                session.dispatcher.loads.invalidate(command.unit_id)
                session.context.recovery_contexts = tuple(dict.fromkeys((*session.context.recovery_contexts, *ids)))


def resource_record(session, command, kind, *, requested=None, target=None,
                    outcome="present", purpose="consume", search=None):
    unit = session.units.records[command.unit_id]
    evidence = dict(unit.activity_evidence)
    if session.context.recovery_contexts:
        evidence["recovery_context_ids"] = list(session.context.recovery_contexts)
    record = {**source_reference(unit), "item_id": session.recovery.next_identity(),
        "kind": kind, "requested": requested, "target": target, "purpose": purpose,
        "outcome": outcome, "activity": unit.activity,
        "activity_evidence": evidence, "search": search or {},
        "knowledge": {"name": "established" if requested is not None else "unevaluated",
                      "contents": "not_observed", "expansion_calls": command.metadata.get("expansion_calls", [])},
        "causes": [], "affected_domains": [],
        "recovery": {"disposition": "not_needed", "original_resource":
                     "satisfied" if outcome == "present" else "unresolved"}}
    session.manifest.dependencies.append(record)
    return record


def recovery_context(session, span, unit_id, item_id, domains, *, boundary="after_scanned_request"):
    assumption = {"id": f"recovery-context-{len(session.manifest.recovery_contexts) + 1}",
        **source_reference(session.units.records[unit_id]), "item_id": item_id,
        "basis": "caller_state_before_unavailable_program",
        "assumed": ["catcodes", "reader_parameters", "structure", "unshadowed_reading_contracts"],
        "unestablished": domains, "boundary": boundary, "endlinechar": session.context.endlinechar,
        "caller_remainder": [span.end, span.basis.length]}
    session.manifest.recovery_contexts.append(assumption)
    session.context.recovery_contexts += (assumption["id"],)
    return assumption["id"]


def _record_recovery(session, command, error, *, kind=None, record=None, program_effects=True, retain=False,
                     purpose="consume"):
    """Record a failed consumption, then continue at the already-scanned boundary."""
    kind = kind or (record["kind"] if record else RESOURCE_ACTIONS[command.action])
    record = record or resource_record(session, command, kind, requested=error.requested,
        target=error.resolved, outcome=error.outcome, search=error.search, purpose=purpose)
    record["knowledge"]["lookup_outcome"] = record["outcome"]
    record.update(outcome=error.outcome)
    category = {"absent": "missing_resource", "ambiguous": "ambiguous_resolution",
                "unreadable": "resource_access", "failed": "resource_processing"}.get(
                    error.outcome, "unresolved_prerequisite")
    record["causes"] = [{"category": category, "reason": error.reason, "detail": error.detail,
        "remedy": "supply_or_repair_resource" if error.outcome in {"absent", "unreadable", "failed"}
                  else "resolve_resource_context"}]
    record["affected_domains"] = (["content", "meanings", "registers", "catcodes",
        "reader_parameters", "hooks", "options", "loads", "structure"]
        if kind in PROGRAM_KINDS else ["content", "presentation"])
    record["knowledge"].update(source_expression=session.raw(command.span),
        effects="unestablished" if kind in PROGRAM_KINDS else "item_local")
    opaque = "opaque-resources/" + (error.resolved or "")
    if opaque in session.opaque_payloads:
        record["knowledge"]["opaque_payload"] = opaque
    record["recovery"] = {"disposition": "retained_source" if retain else "tombstone",
        "original_resource": "satisfied" if error.reason == "asset_conversion" and error.outcome == "failed" else
                             "unresolved" if error.outcome == "unresolved" or purpose == "conditional_consume" else "unsatisfied",
        "assumptions": []}
    if not retain:
        record["recovery"]["marker"] = f"[PyTeXML {kind.replace('_', '-')} {error.outcome} {record['item_id']}]"
    if kind in PROGRAM_KINDS and program_effects:
        # Preserve entry lexical/structural state as an explicit recovery input.
        # Known author definitions cannot survive an unavailable program as facts.
        session.context.invalidate_meanings(session.context.meaning_names(), command.span)
        session.dispatcher.defer_effects(command.span, reason=error.reason, detail=error.detail)
        session.dispatcher.loads.invalidate(command.unit_id)
        record["recovery"]["assumptions"].append(recovery_context(session, command.span,
            command.unit_id, record["item_id"], record["affected_domains"]))
    cause = session.units.uncertainty_cause(command.span, error.reason, error.detail)
    record["cause_ids"] = [cause.id]
    requirement = session.require(command.span, error.reason, error.detail, stage="preparation",
        unit_id=command.unit_id, dependency="possible" if purpose == "conditional_consume" else "required",
        materialization="undetermined" if retain else "unavailable",
        next_step="resource_resolution")
    requirement.update({key: record[key] for key in ("item_id", "kind", "requested", "outcome",
        "knowledge", "causes", "cause_ids", "affected_domains", "recovery", "search")})
    if not retain:
        session.recovery_items.append((command, record))
    return record


def _replacement(session, command, records):
    marker = " ".join(r["recovery"]["marker"] for r in records)
    if command.action != "package_load":
        return marker
    argument = command.argument("name")
    names = command.value("name").split(",")
    failed = {r["requested"] for r in records}
    remaining = [prepared for name, prepared in
        zip(names, command.metadata.get("prepared_package_names", names)) if name.strip() not in failed]
    if remaining and len(remaining) != len(names) and isinstance(argument, ScannedArgument):
        raw = session.raw(command.span)
        start, end = argument.span.start - command.span.start, argument.span.end - command.span.start
        marker += raw[:start] + ",".join(remaining) + raw[end:]
    elif remaining:
        # An expanded argument's origin may cover its entire invocation.
        # Preserve that invocation; source offsets are not token offsets.
        marker += session.raw(command.span)
        for record in records:
            record["recovery"]["retained_invocation"] = True
    return marker


def project_recoveries(session, pieces):
    """Apply markers after every splice rollback, against surviving source maps.

    The original expression remains in the typed record. A missing resource gets
    no invented file or source extent. Retained files carry the same marker as
    the master would; repeated occurrences keep their distinct item identities.
    """
    groups = {}
    for command, record in session.recovery_items:
        groups.setdefault(command.span, []).append(record)
    result = list(pieces)
    for span, records in groups.items():
        command = next(c for c, r in session.recovery_items if c.span == span)
        marker = _replacement(session, command, records)
        located = False
        for index, piece in enumerate(result):
            ranges = piece.mapping.project(span)
            if not ranges or any(r.relation == "enclosing" for r in ranges):
                continue
            if piece.span.basis is span.basis and piece.span.start <= span.start <= span.end <= piece.span.end:
                result[index] = piece.edit_source(span, marker, "RESOURCE_TOMBSTONE")
                located = True
        path = session.documents[span.basis].path
        if path in session.code or path in session.styles:
            # A retained physical file can represent several visited occurrences.
            # Name all of them rather than overwrite one occurrence's identity.
            peers = [r for c, r in session.recovery_items if session.documents[c.span.basis].path == path
                     and (c.span.start, c.span.end) == (span.start, span.end)]
            replacement = _replacement(session, command, peers)
            if any(r["source"] == span.basis.source_id and (r["start"], r["end"]) == (span.start, span.end)
                   and r.get("purpose") == "consume" and r.get("outcome") == "present"
                   for r in session.manifest.dependencies):
                replacement = " ".join(r["recovery"]["marker"] for r in peers) + session.raw(span)
                for record in peers:
                    record["recovery"]["retained_invocation"] = True
            edits = session.payload_edits.setdefault(path, {})
            overlaps = [key for key in edits if key[0] < span.end and key[1] > span.start]
            if all(span.start <= a <= b <= span.end for a, b in overlaps):
                # The whole-request marker supersedes nested filename rebasing.
                for key in overlaps:
                    del edits[key]
                session.edit_payload(span, replacement)
                located = True
        for record in records:
            record["recovery"]["emission"] = "placed" if located else "opaque_source"
    return result
