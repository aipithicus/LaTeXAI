"""Compare final source-derived bindings with a fixed, qualified native corpus.

The caller owns source execution and selects the state boundary. This module
does not install reference meanings, infer demand, or treat unqualified names
as matching. Transient bindings need observations at their own state boundary.
"""
from collections import Counter
from enum import Enum
import gzip
import hashlib
import json

from .native import sha
from ...engine.meanings import meaning_key
from ...reading.contracts import UncertainMeaning


def load_reference(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema"] != "pytexml-native-meaning-fixture-set/1":
        raise ValueError("Unknown reference schema")
    path = directory / "meanings.jsonl.gz"
    if sha(path) != manifest["fixture_sha256"]:
        raise ValueError("Reference checksum differs")
    rows = [json.loads(s) for s in gzip.decompress(path.read_bytes()).decode().splitlines()]
    meanings = {row["name"]: row for row in rows}
    if len(meanings) != len(rows) or len(meanings) != manifest["count"]:
        raise ValueError("Reference names/count differ")
    for row in rows:
        if row["schema"] != "pytexml-native-meaning-fixture/1" or row["basis_inventory_sha256"] != manifest["basis"]["inventory_sha256"]:
            raise ValueError("Reference record basis/schema differs")
    return manifest, meanings


def compare_derived(derived, reference, *, inventory_sha256, state_boundary):
    """Compare every supplied final CS binding; caller must exclude seed state."""
    manifest, meanings = reference
    if manifest["basis"]["inventory_sha256"] != inventory_sha256:
        raise ValueError("Derived and native reference bases differ")
    if not state_boundary:
        raise ValueError("A named derivation state boundary is required")
    records = []
    for name, value in sorted(derived.items()):
        row = {"name": name}
        expected = meanings.get(name)
        if expected is None:
            row["status"] = "no_qualified_reference"
        elif value is None:
            row["status"] = "missing"
        elif isinstance(value, UncertainMeaning) or getattr(value, "uncertain", None) is not None:
            row["status"] = "uncertain"
        else:
            key = meaning_key(value, None)
            if key is None:
                row["status"] = "uncomparable"
            elif key[0] != "macro":
                row.update(status="mismatch", reason="different_meaning_kind", actual_kind=key[0])
            else:
                typed = json.loads(json.dumps(key, default=lambda v: v.value if isinstance(v, Enum) else v))
                digest = hashlib.sha256(json.dumps(typed, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
                equal = digest == expected["semantic_sha256"] and typed == expected["semantic_key"]
                row.update(status="match" if equal else "mismatch", actual_semantic_sha256=digest)
                if not equal:
                    row.update(reason="different_macro_descriptor", actual_semantic_key=typed,
                               expected_semantic_key=expected["semantic_key"])
        if expected is not None:
            row["expected_semantic_sha256"] = expected["semantic_sha256"]
        records.append(row)
    counts = Counter(row["status"] for row in records)
    denominator = len(meanings)
    return {"schema": "pytexml-derived-meaning-comparison/1", "state_boundary": state_boundary,
        "reference_boundary": "pinned_native_format_start", "basis_inventory_sha256": inventory_sha256,
        "reference_fixture_sha256": manifest["fixture_sha256"], "derived_names": len(records),
        "counts": dict(counts), "qualified_reference_macros": denominator,
        "matched_share_of_qualified_reference": counts["match"] / denominator if denominator else None,
        "derived_with_qualified_reference": sum(r["name"] in meanings for r in records),
        "scope": "Caller-supplied final source bindings; qualified macro reference only, not full census or behavioral coverage. Boundary/context differences may cause mismatches.",
        "records": records}
