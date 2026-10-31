"""Merkle indexing of ordered causal records with explicit relationship identity.

Index construction and validation are linear in record/edge volume. Reusing an
index prunes equal blocks; aligned single-leaf changes take a logarithmic walk.
Insertions/unequal lengths use an explicit linear fallback, never an O(depth)
claim for arbitrary graph edits. Equal observations are not whole-engine proof.
"""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time
from types import MappingProxyType
from collections.abc import Mapping

from ..engine.causal import digest


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def normalized_records(record):
    if record.get("schema") != "pytexml-causal-record/1":
        raise ValueError("Unknown causal record schema")
    identities, versions = {}, {}
    for kind, values in (("event", record["events"]), ("version", record["versions"])):
        for index, value in enumerate(values):
            identity = value["id"]
            if identity in identities:
                raise ValueError("Duplicate causal occurrence identity")
            identities[identity] = {"kind": kind, "index": index}
            if kind == "version":
                actual = digest(value["value"])
                if actual != value["sha256"]:
                    raise ValueError("State version hash does not match its value")
                versions[identity] = actual
    def reference(identity):
        if identity not in identities:
            raise ValueError("Dangling causal relationship: " + str(identity))
        return {**identities[identity], **({"value_sha256": versions[identity]} if identity in versions else {})}
    edges = {identity: [] for identity in identities}
    for edge in record["edges"]:
        reference(edge["source"])
        edges[edge["source"]].append({"relation": edge["relation"], "target": reference(edge["target"])})
    for event in record["events"]:
        yield {"kind": "event", **{k: v for k, v in event.items() if k not in {"id", "source"}},
               "relationships": edges[event["id"]]}
    for version in record["versions"]:
        yield {"kind": "version", **{k: v for k, v in version.items() if k != "id"},
               "relationships": edges[version["id"]]}
    yield {"kind": "observables", "state": record["state"], "output": record["output"],
           "frontier": {key: reference(identity) for key, identity in record["frontier"].items()},
           "status": record["status"], "gaps": record["gaps"], "coverage": record["coverage"]}


@dataclass(frozen=True)
class Index:
    records: tuple
    levels: tuple
    source: dict
    build_seconds: float

    @property
    def root(self):
        return self.levels[-1][0]

    @classmethod
    def build(cls, record):
        started = time.perf_counter()
        records = tuple(normalized_records(record))
        width = 1 << (max(1, len(records)) - 1).bit_length()
        leaves = tuple(digest({"leaf": item}) for item in records) + (digest({"padding": True}),) * (width - len(records))
        levels = [leaves]
        while len(levels[-1]) > 1:
            previous = levels[-1]
            levels.append(tuple(digest({"left": previous[i], "right": previous[i + 1]})
                                for i in range(0, len(previous), 2)))
        return cls(tuple(freeze(r) for r in records), tuple(levels), freeze(record), time.perf_counter() - started)


def compare(left, right):
    """Reuse Index instances across repeated comparisons; JSON input is verified."""
    left = left if isinstance(left, Index) else Index.build(left)
    right = right if isinstance(right, Index) else Index.build(right)
    visited, pruned, first = 0, 0, None
    aligned = len(left.records) == len(right.records)
    if aligned:
        def walk(level, position):
            nonlocal visited, pruned
            visited += 1
            if left.levels[level][position] == right.levels[level][position]:
                pruned += 1
                return None
            if level == 0:
                return position
            found = walk(level - 1, position * 2)
            return found if found is not None else walk(level - 1, position * 2 + 1)
        first = walk(len(left.levels) - 1, 0)
    else:
        for position in range(max(len(left.records), len(right.records))):
            visited += 1
            if (position >= min(len(left.records), len(right.records)) or
                    left.levels[0][position] != right.levels[0][position]):
                first = position
                break
            pruned += 1
    complete = all(i.source["status"] in {"completed", "dumped"} and not i.source["gaps"]
                   and all(e["status"] != "open" for e in i.source["events"]) for i in (left, right))
    difference = None
    if first is not None:
        difference = {"record_index": first,
                      "expected": thaw(left.records[first]) if first < len(left.records) else None,
                      "actual": thaw(right.records[first]) if first < len(right.records) else None}
        if first < len(right.source["events"]):
            difference.update(event_id=right.source["events"][first]["id"], source=thaw(right.source["events"][first]["source"]))
    return {"schema": "pytexml-record-diff/1", "status": "incomplete" if not complete else "matched" if first is None else "different",
            "record_equal": left.root == right.root,
            "state_equal": left.source["state"] == right.source["state"],
            "output_equal": left.source["output"] == right.source["output"],
            "first_difference": difference,
            "merkle": {"left_root": left.root, "right_root": right.root, "visited": visited, "pruned": pruned,
                       "algorithm": "aligned_tree" if aligned else "linear_unequal_length",
                       "left_records": len(left.records), "right_records": len(right.records),
                       "index_build_seconds": [left.build_seconds, right.build_seconds]},
            "scope": "Ordered recorded operations, relationships and selected state/output; dependency coverage remains explicit and partial."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.left.read_text(encoding="utf-8")), json.loads(args.right.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "merkle": result["merkle"]}))
    return 0 if result["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
