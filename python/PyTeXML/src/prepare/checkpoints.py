"""Preparation's participant in the shared checkpoint protocol.

Source acquisition (cached bytes, occurrence bases and attempted observations)
is evidence, not an execution effect. Recovery records are committed separately
by the coordinator. Everything below is private work owned by a command.
"""
from copy import copy
from dataclasses import fields, is_dataclass


def snapshot(value, memo=None):
    memo = {} if memo is None else memo
    if id(value) in memo:
        return memo[id(value)]
    if isinstance(value, dict):
        result = {}
        memo[id(value)] = result
        result.update((key, snapshot(item, memo)) for key, item in value.items())
        return result
    if isinstance(value, list):
        result = []
        memo[id(value)] = result
        result.extend(snapshot(item, memo) for item in value)
        return result
    if isinstance(value, set):
        return set(value)
    if is_dataclass(value) and not value.__dataclass_params__.frozen:
        result = copy(value)
        memo[id(value)] = result
        for field in fields(value):
            setattr(result, field.name, snapshot(getattr(value, field.name), memo))
        return result
    return value  # Immutable source identities/tokens and service objects.


class PreparationState:
    # These sequences contain immutable observations. Copy their containers in
    # C, without walking every earlier output character at every command.
    _sequences = ("pieces", "tombstones", "commands", "bibliography_pieces")
    _fields = (
        "frames", "active", "styles", "images",
        "candidate_images", "asset_uses", "candidate_sources", "_implicit", "code",
        "retained_search_dirs", "retained_resources", "tested_resources", "literal_payloads",
        "payload_edits", "package_options", "forwarded_options", "class_options",
        "graphic_paths", "graphic_extensions", "includeonly",
        "bibliography_context", "bibliography_knowledge", "bibliography_observed",
        "bibliography_may_skip", "_ended_document",
    )
    _evidence = {"input_occurrences", "recovery_contexts"}

    def __init__(self, session):
        self.session = session
        self.sequences = {}
        for name in self._sequences:
            value = getattr(session, name)
            self.sequences[name] = list(value) if value is not None else None
        self.saved = snapshot({
            "values": {name: getattr(session, name) for name in self._fields},
            "manifest": {f.name: getattr(session.manifest, f.name)
                         for f in fields(session.manifest) if f.name not in self._evidence
                         and not isinstance(getattr(session.manifest, f.name), list)},
            "lint_records": session.lint._records, "lint_repairs": session.lint._repairs})
        # Fact rows are completed by their creating command and appended. Later
        # location/materialization projection is outside the reading pass. Keep
        # the row identities (also used by the recovery journal), while restoring
        # each list's membership. Live mutable summaries remain in `saved`.
        self.records = {f.name: list(value) for f in fields(session.manifest)
                        if f.name not in self._evidence
                        and isinstance(value := getattr(session.manifest, f.name), list)}

    def restore(self):
        for name, value in self.sequences.items():
            setattr(self.session, name, list(value) if value is not None else None)
        saved = snapshot(self.saved)
        for name, value in saved["values"].items():
            setattr(self.session, name, value)
        for name, value in saved["manifest"].items():
            setattr(self.session.manifest, name, value)
        for name, value in self.records.items():
            setattr(self.session.manifest, name, list(value))
        self.session.lint.report = self.session.manifest.lint
        self.session.lint._records, self.session.lint._repairs = saved["lint_records"], saved["lint_repairs"]

    def after_restore(self):
        self.session.recovery.restore_committed()
