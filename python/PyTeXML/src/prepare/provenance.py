"""Emission-time diagnostic provenance.

Preparation emits version 3 decoded-character intervals, including source
occurrence identities and mixed-source lines. IDENTITY segments have affine
offset correspondence; transformations relate whole ranges. Legacy line-ledger
read/write helpers below remain for existing version 1 diagnostic artifacts.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class SourceLine:
    """Represents a single line of text with its origin file and line number."""
    text: str
    src_file: str
    src_line: int
    op: str = "IDENTITY"
    payload: Optional[str] = None


@dataclass
class Tombstone:
    """Records deleted/pruned ranges of source code that produce no output."""
    src_file: str
    src_start: int
    src_end: int
    op: str
    reason: str = ""
    # Version 3 tombstones use character intervals, scoped to an input occurrence.
    # Legacy line-ledger readers leave these fields unset.
    occurrence: Optional[int] = None
    source_lines: Optional[Tuple[int, int]] = None

    def to_tuple(self, file_pool: Dict[str, int], op_pool: Dict[str, int]) -> List[Any]:
        return [
            file_pool[self.src_file],
            self.src_start,
            self.src_end,
            op_pool[self.op],
            self.reason
        ]


@dataclass
class ProvenanceRun:
    """A contiguous interval mapping between master.tex and a source file."""
    gen_start: int
    gen_end: int
    src_file: str
    src_start: int
    src_end: int
    op: str = "IDENTITY"
    payload: Optional[str] = None

    def to_tuple(self, file_pool: Dict[str, int], op_pool: Dict[str, int]) -> List[Any]:
        t = [
            self.gen_start,
            self.gen_end,
            file_pool[self.src_file],
            self.src_start,
            self.src_end,
            op_pool[self.op]
        ]
        if self.payload is not None:
            t.append(self.payload)
        return t


class ProvenanceLedger:
    """
    Compact RLE source provenance ledger.
    Supports backward trace (master -> source) and forward trace (source -> master/tombstone).
    """

    def __init__(
        self,
        sources: Optional[List[str]] = None,
        operations: Optional[List[str]] = None,
        runs: Optional[List[ProvenanceRun]] = None,
        tombstones: Optional[List[Tombstone]] = None
    ):
        self.sources: List[str] = sources or []
        self.operations: List[str] = operations or []
        self.runs: List[ProvenanceRun] = runs or []
        self.tombstones: List[Tombstone] = tombstones or []
        self.segments = None
        self.master_length = 0
        self.master_line_starts = []
        self.version = 1
        self.replacements = []
        self.source_coverage = []
        self.artifact = None

        self._gen_starts: List[int] = [r.gen_start for r in self.runs]
        self._source_index: Dict[str, List[ProvenanceRun]] = {}
        self._tombstone_index: Dict[str, List[Tombstone]] = {}
        self._reindex()

    def _reindex(self) -> None:
        self._gen_starts = [r.gen_start for r in self.runs]
        self._source_index = {}
        for r in self.runs:
            self._source_index.setdefault(r.src_file, []).append(r)

        self._tombstone_index = {}
        for t in self.tombstones:
            self._tombstone_index.setdefault(t.src_file, []).append(t)

    @classmethod
    def build_from_lines(
        cls,
        lines: List[SourceLine],
        tombstones: Optional[List[Tombstone]] = None
    ) -> ProvenanceLedger:
        """Compresses a sequence of tagged SourceLines into an interval ledger."""
        if not lines:
            return cls(sources=[], operations=[], runs=[], tombstones=tombstones or [])

        sources_set: Dict[str, int] = {}
        ops_set: Dict[str, int] = {}

        def _get_id(d: Dict[str, int], key: str) -> int:
            if key not in d:
                d[key] = len(d)
            return d[key]

        runs: List[ProvenanceRun] = []
        cur_gen_start = 1
        cur_src_file = lines[0].src_file
        cur_src_start = lines[0].src_line
        cur_src_prev = lines[0].src_line
        cur_op = lines[0].op
        cur_payload = lines[0].payload

        _get_id(sources_set, cur_src_file)
        _get_id(ops_set, cur_op)

        for idx in range(1, len(lines)):
            l = lines[idx]
            gen_line = idx + 1
            _get_id(sources_set, l.src_file)
            _get_id(ops_set, l.op)

            is_sequential = (
                l.src_file == cur_src_file and
                l.src_line == cur_src_prev + 1 and
                l.op == cur_op and
                l.payload == cur_payload
            )

            if is_sequential:
                cur_src_prev = l.src_line
            else:
                runs.append(ProvenanceRun(
                    gen_start=cur_gen_start,
                    gen_end=idx,
                    src_file=cur_src_file,
                    src_start=cur_src_start,
                    src_end=cur_src_prev,
                    op=cur_op,
                    payload=cur_payload
                ))
                cur_gen_start = gen_line
                cur_src_file = l.src_file
                cur_src_start = l.src_line
                cur_src_prev = l.src_line
                cur_op = l.op
                cur_payload = l.payload

        runs.append(ProvenanceRun(
            gen_start=cur_gen_start,
            gen_end=len(lines),
            src_file=cur_src_file,
            src_start=cur_src_start,
            src_end=cur_src_prev,
            op=cur_op,
            payload=cur_payload
        ))

        if tombstones:
            for t in tombstones:
                _get_id(sources_set, t.src_file)
                _get_id(ops_set, t.op)

        # Reconstruct canonical lists
        source_list = [k for k, _ in sorted(sources_set.items(), key=lambda x: x[1])]
        op_list = [k for k, _ in sorted(ops_set.items(), key=lambda x: x[1])]

        ledger = cls(
            sources=source_list,
            operations=op_list,
            runs=runs,
            tombstones=tombstones or []
        )
        return ledger


    def resolve_master_line(self, master_line: int) -> Optional[Dict[str, Any]]:
        """
        Backward Lookup: Given a line number in master.tex, returns its source origin.
        Operates in O(log N) time via binary search.
        """
        if self.segments is not None:
            if not 1 <= master_line <= len(self.master_line_starts):
                return None
            start = self.master_line_starts[master_line - 1]
            end = self.master_line_starts[master_line] if master_line < len(self.master_line_starts) else self.master_length
            origins = [s for s in self.segments if s['generated'][0] < end and s['generated'][1] > start]
            return {"origins": origins} if origins else None
        if not self.runs:
            return None

        idx = bisect.bisect_right(self._gen_starts, master_line) - 1
        if idx < 0:
            return None

        r = self.runs[idx]
        if not (r.gen_start <= master_line <= r.gen_end):
            return None

        offset = master_line - r.gen_start
        return {
            "source_file": r.src_file,
            "source_line": r.src_start + offset,
            "operation": r.op,
            "details": r.payload
        }

    def resolve_source_line(self, src_file: str, src_line: int) -> Dict[str, Any]:
        """
        Forward Lookup: Given a source file and line, checks if it survived into master.tex,
        or retrieves the tombstone explaining why it was pruned/stripped.
        """
        if self.segments is not None:
            matches = [s for s in self.segments if s['source_file'] == src_file
                       and s['source_lines'][0] <= src_line <= s['source_lines'][1]]
            if matches:
                return {"status": "ACTIVE", "occurrences": matches}
        # 1. Check active runs
        runs = self._source_index.get(src_file, [])
        for r in runs:
            if r.src_start <= src_line <= r.src_end:
                offset = src_line - r.src_start
                return {
                    "status": "ACTIVE",
                    "master_line": r.gen_start + offset,
                    "operation": r.op,
                    "details": r.payload
                }

        # 2. Check tombstones
        tombstones = self._tombstone_index.get(src_file, [])
        for t in tombstones:
            start, end = t.source_lines or (t.src_start, t.src_end)
            if start <= src_line <= end:
                return {
                    "status": "PRUNED",
                    "operation": t.op,
                    "reason": t.reason
                }

        return {"status": "NOT_FOUND"}

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the ledger into a compact string-pooled matrix."""
        if self.segments is not None:
            result = {"version": self.version, "coordinate_domain": "decoded_unicode_codepoints",
                    "segments": self.segments, "master_length": self.master_length,
                    "master_line_starts": self.master_line_starts,
                    "sources": self.sources, "operations": self.operations,
                    "tombstones": [vars(t) for t in self.tombstones]}
            if self.version >= 3:
                result.update(artifact=self.artifact, replacements=self.replacements, source_coverage=self.source_coverage,
                    intervals="zero_based_half_open", tombstones=[{
                        "source_file": t.src_file, "occurrence": t.occurrence, "source": [t.src_start, t.src_end],
                        "source_lines": list(t.source_lines) if t.source_lines else None,
                        "operation": t.op, "reason": t.reason} for t in self.tombstones])
            return result
        file_pool = {name: idx for idx, name in enumerate(self.sources)}
        op_pool = {name: idx for idx, name in enumerate(self.operations)}

        return {
            "version": 1,
            "sources": self.sources,
            "operations": self.operations,
            "runs": [r.to_tuple(file_pool, op_pool) for r in self.runs],
            "tombstones": [t.to_tuple(file_pool, op_pool) for t in self.tombstones]
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProvenanceLedger:
        if data.get("version") in (2, 3):
            tombstones = ([Tombstone(t['source_file'], *t['source'], t['operation'], t['reason'],
                           t['occurrence'], tuple(t['source_lines']) if t['source_lines'] else None)
                           for t in data.get('tombstones', [])] if data['version'] == 3 else
                          [Tombstone(**t) for t in data.get('tombstones', [])])
            result = cls(sources=data['sources'], operations=data['operations'],
                         tombstones=tombstones)
            result.version = data['version']
            result.segments = data['segments']
            result.master_length = data['master_length']
            result.master_line_starts = data['master_line_starts']
            result.replacements = data.get('replacements', [])
            result.source_coverage = data.get('source_coverage', [])
            result.artifact = data.get('artifact')
            return result
        sources = data.get("sources", [])
        ops = data.get("operations", [])
        raw_runs = data.get("runs", [])
        raw_tombstones = data.get("tombstones", [])

        runs: List[ProvenanceRun] = []
        for r in raw_runs:
            gen_start, gen_end, f_idx, s_start, s_end, op_idx = r[:6]
            payload = r[6] if len(r) > 6 else None
            runs.append(ProvenanceRun(
                gen_start=gen_start,
                gen_end=gen_end,
                src_file=sources[f_idx],
                src_start=s_start,
                src_end=s_end,
                op=ops[op_idx],
                payload=payload
            ))

        tombstones: List[Tombstone] = []
        for t in raw_tombstones:
            f_idx, s_start, s_end, op_idx = t[:4]
            reason = t[4] if len(t) > 4 else ""
            tombstones.append(Tombstone(
                src_file=sources[f_idx],
                src_start=s_start,
                src_end=s_end,
                op=ops[op_idx],
                reason=reason
            ))

        return cls(sources=sources, operations=ops, runs=runs, tombstones=tombstones)

    def save(self, filepath: Path) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(self.to_json(indent=2))

    @classmethod
    def load(cls, filepath: Path) -> ProvenanceLedger:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def summary(self) -> Dict[str, Any]:
        if self.segments is not None:
            return {"total_master_lines": len(self.master_line_starts), "total_runs": len(self.segments),
                    "total_tombstones": len(self.tombstones), "sources_count": len(self.sources),
                    "compression_ratio": round(len(self.master_line_starts) / max(1, len(self.segments)), 2)}
        total_gen_lines = self.runs[-1].gen_end if self.runs else 0
        op_counts: Dict[str, int] = {}
        for r in self.runs:
            op_counts[r.op] = op_counts.get(r.op, 0) + (r.gen_end - r.gen_start + 1)

        return {
            "total_master_lines": total_gen_lines,
            "total_runs": len(self.runs),
            "total_tombstones": len(self.tombstones),
            "sources_count": len(self.sources),
            "compression_ratio": round(total_gen_lines / max(len(self.runs), 1), 2),
            "operation_lines": op_counts
        }

    @classmethod
    def build_from_pieces(cls, pieces, tombstones=None, *, source_coverage=(), artifact=None, rle_compression=True):
        """Character intervals support mixed-source lines and repeated inputs.

        A rewritten segment relates whole extents; it does not claim an affine
        character mapping. Only IDENTITY segments permit offset interpolation.
        """
        ledger = cls(tombstones=tombstones or [])
        ledger.version = 3
        ledger.source_coverage = list(source_coverage)
        ledger.artifact = artifact
        ledger.segments = []
        replacements = {}
        text = ''.join(p.text for p in pieces)
        ledger.master_length = len(text)
        ledger.master_line_starts = ([0] + [m.end() for m in re.finditer(r"\r\n|\r|\n", text)
                                           if m.end() < len(text)]) if text else []
        offset = 0
        for p in pieces:
            if not p.text:
                continue
            span = p.span
            segment = {'generated': [offset, offset + len(p.text)], 'source_file': span.basis.source_id,
                       'occurrence': span.basis.occurrence_id, 'source': [span.start, span.end],
                       'source_lines': [p.source_line, p.source_end_line or p.source_line],
                       'operation': p.operation,
                       'mapping': ('copy' if len(p.mapping.runs) == 1 and p.mapping.runs[0].kind == 'copy'
                                   else 'insert' if span.start == span.end else 'replace')}
            if segment['mapping'] == 'copy' and len(p.text) != span.end - span.start:
                raise ValueError('Copy segment changes source length')
            if p.operation == 'IDENTITY' and segment['mapping'] != 'copy':
                raise ValueError('Identity emission requires copy correspondence')
            if p.derivations:
                segment['derivations'] = [{'source': s.basis.source_id,
                    'occurrence': s.basis.occurrence_id, 'start': s.start, 'end': s.end}
                    for s in p.derivations]
            for source in p.replaces:
                key = (source.basis.source_id, source.basis.occurrence_id, source.start, source.end)
                ranges = replacements.setdefault(key, [])
                if ranges and ranges[-1][1] == offset:
                    ranges[-1][1] = offset + len(p.text)
                else:
                    ranges.append([offset, offset + len(p.text)])
            if rle_compression and ledger.segments and p.operation == 'IDENTITY':
                previous = ledger.segments[-1]
                if (previous['operation'] == 'IDENTITY' and previous['source_file'] == segment['source_file']
                    and previous['occurrence'] == segment['occurrence'] and previous['source'][1] == span.start):
                    previous['generated'][1] = segment['generated'][1]
                    previous['source'][1] = span.end
                    previous['source_lines'][1] = segment['source_lines'][1]
                else:
                    ledger.segments.append(segment)
            else:
                ledger.segments.append(segment)
            offset += len(p.text)
        ledger.sources = list(dict.fromkeys(s['source_file'] for s in ledger.segments))
        ledger.operations = list(dict.fromkeys(s['operation'] for s in ledger.segments))
        for i, segment in enumerate(ledger.segments, 1):
            segment['id'] = f'segment-{i}'
        ledger.replacements = [{'source_file': source, 'occurrence': occurrence, 'source': [start, end],
                                'generated': ranges, 'operation': 'REPLACE'}
                               for (source, occurrence, start, end), ranges in replacements.items()]
        return ledger
