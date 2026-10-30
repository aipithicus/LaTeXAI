"""Freeze or replay a generated, native-qualified meaning fixture set."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

from .model import check_fixtures
from .native import sha, write_json


def freeze(assay, destination):
    summary = json.loads((assay / "summary.json").read_text(encoding="utf-8"))
    if summary.get("schema") != "pytexml-meaning-assay/1" or summary.get("status") != "complete":
        raise ValueError("Only a completed assay can produce frozen fixtures")
    source = assay / "fixtures.jsonl"
    if sha(source) != summary["artifacts"]["fixtures.jsonl"]:
        raise ValueError("Fixture checksum differs from completed receipt")
    count = check_fixtures(source)
    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    if count != summary["fixture_replay_count"] or len({r["name"] for r in records}) != count:
        raise ValueError("Fixture count or name uniqueness differs from receipt")
    if any(r["basis_inventory_sha256"] != summary["basis"]["inventory_sha256"] for r in records):
        raise ValueError("Fixture basis differs from receipt")
    outcomes = dict(Counter(r["reconstruction"] for r in records))
    expected = {k: summary["reconstruction"][k] for k in ("exact", "recovered")}
    if outcomes != expected:
        raise ValueError("Fixture outcomes differ from receipt")
    destination.mkdir(parents=True, exist_ok=False)
    compressed = destination / "meanings.jsonl.gz"
    compressed.write_bytes(gzip.compress(source.read_bytes(), mtime=0))
    write_json(destination / "manifest.json", {
        "schema": "pytexml-native-meaning-fixture-set/1", "count": count,
        "reconstruction": outcomes, "basis": summary["basis"],
        "target_profile": summary["target_profile"], "lua_profile": summary["lua"],
        "probe_sources": summary["probe_sources"], "generator_code": summary["code"],
        "receipt_sha256": sha(assay / "summary.json"),
        "fixture_sha256": sha(compressed), "uncompressed_sha256": sha(source),
        "qualification": "Each generated candidate passed native pdfTeX ifx against the pinned format meaning; replay verifies PyTeXML typed tokens and printed meaning.",
        "limits": "Macro reconstruction fixtures only. No runtime installation, body execution, complete census or intrinsic eligibility claim."
    })
    return count


def check_frozen(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema"] != "pytexml-native-meaning-fixture-set/1":
        raise ValueError("Unknown fixture set schema")
    fixture = directory / "meanings.jsonl.gz"
    if sha(fixture) != manifest["fixture_sha256"]:
        raise ValueError("Frozen fixture checksum differs")
    count = check_fixtures(fixture)
    if count != manifest["count"]:
        raise ValueError("Frozen fixture count differs")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("freeze")
    export.add_argument("--assay", required=True, type=Path)
    export.add_argument("--destination", required=True, type=Path)
    replay = commands.add_parser("check")
    replay.add_argument("directory", type=Path)
    args = parser.parse_args()
    count = freeze(args.assay, args.destination) if args.command == "freeze" else check_frozen(args.directory)
    print(json.dumps({"command": args.command, "fixtures": count}))


if __name__ == "__main__":
    main()
