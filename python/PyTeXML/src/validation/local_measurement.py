"""Compare local box dimensions, in integer scaled points, against native TeX."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from ..engine.content_builder import ContentBuilder

FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures/engine"


def build():
    return ContentBuilder({p.name: p.read_text() for p in FIXTURES.glob("local-measurement*.tex")},
                          metrics={"cmr10.tfm": (FIXTURES / "cmr10.tfm").read_bytes()}).build("local-measurement.tex")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdftex", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    native = subprocess.run([str(args.pdftex.resolve()), "-ini", "-etex", "-interaction=nonstopmode",
        "-output-directory=" + str(output), "local-measurement.tex"], cwd=FIXTURES, capture_output=True, timeout=60)
    log = (output / "local-measurement.log").read_text().replace("\r\n", "\n")
    if native.returncode or re.search(r"^!", log, re.M) or "OBS:DONE" not in log:
        raise ValueError("Native measurement failed: " + log)
    expected = re.findall(r"OBS:[a-z]+:-?\d+,-?\d+,-?\d+|OBS:DONE", log)
    result = build()
    actual = list(result.messages)
    receipt = {"schema": "pytexml-local-measurement/1",
        "status": "matched" if result.status == "completed" and actual == expected else "mismatch",
        "boundary": result.boundary, "expected": expected, "actual": actual,
        "native_version": native.stdout.decode(errors="replace").splitlines()[0],
        "executable_sha256": hashlib.sha256(args.pdftex.read_bytes()).hexdigest(),
        "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [*FIXTURES.glob("local-measurement*.tex"), FIXTURES / "cmr10.tfm"]},
        "log_sha256": hashlib.sha256(log.encode()).hexdigest(),
        "scope": "selected local dimensions; no paragraph, page, math-layout or rendering equivalence"}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", newline="\n")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
