"""Finalize unit locations against prepared artifacts, independently of the ledger.

The index is in memory and uses occurrence-specific source bases. Queries cost a
binary search plus the overlapping mapping runs, rather than scanning the whole
manuscript for each requirement. Only artifact locations leave this module as the
downstream address; original spans remain diagnostic information.
"""
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256

from ..reading.edit_map import MappingRun, project_run
from ..reading.spans import SpanSet
from .provenance import Tombstone


@dataclass(frozen=True, slots=True)
class _LocatedRun:
    artifact: str | None
    run: MappingRun


def _merge_locations(locations):
    result = []
    for location in sorted(locations, key=lambda p: (p["artifact"], p["start"], p["end"])):
        if result and result[-1]["artifact"] == location["artifact"] and location["start"] <= result[-1]["end"]:
            previous = result[-1]
            previous["end"] = max(previous["end"], location["end"])
            if location["precision"] == "enclosing":
                previous["precision"] = "enclosing"
        else:
            result.append(dict(location))
    return result


class PreparedLocations:
    def __init__(self):
        self.artifacts = {}
        self._runs = defaultdict(list)
        self._index = {}
        self.tombstones = []
        self.source_coverage = []

    def add(self, artifact, text, pieces):
        metadata = {"path": artifact, "sha256": sha256(text.encode("utf-8")).hexdigest(),
                    "length": len(text)}
        if artifact in self.artifacts and self.artifacts[artifact] != metadata:
            raise ValueError("One prepared artifact has conflicting contents")
        self.artifacts[artifact] = metadata
        offset = 0
        for piece in pieces:
            for run in piece.mapping.runs:
                self._runs[run.source.basis].append(_LocatedRun(artifact, run.shifted(offset)))
            for source in piece.replaces:
                self._runs[source.basis].append(_LocatedRun(artifact,
                    MappingRun(source, offset, offset + len(piece.text), "replace")))
            offset += len(piece.text)
        if offset != len(text):
            raise ValueError("Prepared pieces do not cover their artifact")
        self._index.clear()

    def _build_index(self):
        for basis, entries in self._runs.items():
            ordered = sorted(entries, key=lambda e: e.run.source.start)
            maximum, ends = -1, []
            for entry in ordered:
                maximum = max(maximum, entry.run.source.end)
                ends.append(maximum)
            self._index[basis] = (ordered, ends)

    def project(self, span):
        if not self._index:
            self._build_index()
        entries, ends = self._index.get(span.basis, ((), ()))
        locations, covered = [], []
        position = bisect_left(ends, span.start)
        for i in range(position, len(entries)):
            entry = entries[i]
            run = entry.run
            if run.source.start > span.end:
                break
            projected = project_run(run, span)
            if projected is None:
                continue
            a, b = max(span.start, run.source.start), min(span.end, run.source.end)
            if a < b:
                covered.append(span.basis.span(a, b))
            if entry.artifact is not None and (projected.start < projected.end or span.start == span.end):
                locations.append({"artifact": entry.artifact, "start": projected.start, "end": projected.end,
                                  "precision": "enclosing" if projected.relation == "enclosing" else "exact"})
        accounted = SpanSet(span.basis, covered)
        complete = accounted.covers(SpanSet(span.basis, (span,)))
        locations = _merge_locations(locations)
        if locations:
            status = ("partial" if not complete else "enclosing" if any(p["precision"] == "enclosing" for p in locations)
                      else "mapped")
        else:
            status = "omitted" if complete and span.start < span.end else "unmapped"
        return {"location_status": status, "locations": locations}

    def account(self, session):
        """Subtract actual output before accepting discard evidence as deletion.

        Scanner lookahead and preserved literal/definition bodies can contain
        discard observations without losing those characters from the artifact.
        Unknown gaps remain explicit; they are never classified from their text.
        """
        represented = {basis: SpanSet(basis, (e.run.source for e in entries if e.run.start < e.run.end))
                       for basis, entries in self._runs.items()}
        by_origin = {(b.source_id, b.occurrence_id): b for b in (*session.documents, *session.generated_sources)}
        candidates = defaultdict(list)
        for t in session.tombstones:
            basis = by_origin.get((t.src_file, t.occurrence))
            if basis is not None:
                candidates[basis].append((basis.span(t.src_start, t.src_end), t.reason))
        for basis, reader in session.readers.items():
            candidates[basis].extend(reader.discarded)
        for basis, entries in self._runs.items():
            candidates[basis].extend((e.run.source, "Emission edit removed text") for e in entries
                                     if e.run.start == e.run.end and e.run.source.start < e.run.source.end)
        self.tombstones = []
        self.source_coverage = []
        for basis in by_origin.values():
            covered = represented.get(basis, SpanSet(basis, ()))
            ordered = sorted(candidates[basis], key=lambda p: p[0].start)
            maximum, ends = -1, []
            for span, _ in ordered:
                maximum = max(maximum, span.end)
                ends.append(maximum)
            deleted = SpanSet(basis, (s for s, _ in ordered)).difference(covered)
            for lost in deleted:
                reasons = []
                for i in range(bisect_left(ends, lost.start), len(ordered)):
                    span, reason = ordered[i]
                    if span.start >= lost.end:
                        break
                    if span.end > lost.start and reason not in reasons:
                        reasons.append(reason)
                self.tombstones.append(Tombstone(basis.source_id, lost.start, lost.end, "OMIT", "; ".join(reasons),
                    basis.occurrence_id, (session.line(lost), session.line(basis.span(lost.end - 1, lost.end)))))
                self._runs[basis].append(_LocatedRun(None, MappingRun(lost, 0, 0, "replace")))
            unknown = covered.union(deleted).complement(basis.whole)
            self.source_coverage.append({"source": basis.source_id, "occurrence": basis.occurrence_id,
                "length": basis.length, "origin_kind": "generated" if basis in session.generated_sources else "source",
                "unaccounted": [[s.start, s.end] for s in unknown]})
        self._index.clear()

    def publish(self, session):
        manifest = session.manifest
        manifest.location_contract = {"version": 1, "coordinate_domain": "decoded_unicode_codepoints",
            "intervals": "zero_based_half_open", "encoding": "utf-8", "newline_translation": "none",
            "id_scope": "preparation_run"}
        manifest.prepared_artifacts = list(self.artifacts.values())
        records = {}
        for unit in session.units.records.values():
            record = {**unit.to_dict(), **self.project(unit.span)}
            records[unit.id] = record
        manifest.units = list(records.values())
        for target in (*manifest.requirements, *manifest.unresolved, *manifest.dependencies,
                       *manifest.candidate_dependencies, *manifest.resources, *manifest.source_metadata):
            unit = records[target["unit_id"]]
            target.update(location_status=unit["location_status"], locations=unit["locations"])


def finalize_locations(session, pieces, master, payloads):
    """No original file reads, and no dependency on provenance-sidecar emission."""
    locations = PreparedLocations()
    locations.add("master.tex", master, pieces)
    for path, (artifact, text) in payloads.items():
        bases = [b for b, doc in session.documents.items() if doc.path == path]
        for basis in bases:
            locations.add(artifact, text, (session.payload_piece(path, basis),))
        if not bases:
            locations.artifacts[artifact] = {"path": artifact, "sha256": sha256(text.encode("utf-8")).hexdigest(),
                                             "length": len(text)}
    locations.account(session)
    locations.publish(session)
    return locations
