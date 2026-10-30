"""Compare selected pre-layout content observations with native TeX list dumps.

The fixture's observers are the only differing definitions. Native diagnostics
must be exactly five `! OK.` reports; unexpected errors invalidate the receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from ..engine.content_builder import ContentBuilder


FIXTURES = Path(__file__).resolve().parents[2] / "tests/fixtures/engine"


def fixture_build():
    config = json.loads((FIXTURES / "content-construction.inventory.json").read_text())
    sources = {name: (FIXTURES / path).read_bytes().decode() for name, path in config["sources"].items()}
    metrics = {name: (FIXTURES / path).read_bytes() for name, path in config["metrics"].items()}
    return ContentBuilder(sources, metrics=metrics).build(config["entry"])


def descendants(node):
    yield node
    for child in node.children:
        yield from descendants(child)


def observations(result):
    def box(index):
        return result.context.state_cells.read("box:" + str(index))
    def letters(node):
        return "".join(n.get("text") for n in descendants(node) if n.kind == "character")
    formula = next(n for n in descendants(box(1)) if n.kind == "math")
    atoms = []
    for node in formula.children:
        atom = {"class": node.get("class_"), "nucleus": [], "sup": [], "sub": [], "limits": node.get("limits")}
        for child in node.children:
            role = child.kind if child.kind in {"sup", "sub"} else "nucleus"
            atom[role].extend([n.get("family"), n.get("code")] for n in descendants(child) if n.kind == "math_character")
        atoms.append(atom)
    alignment = next(n for n in descendants(box(2)) if n.kind == "alignment")
    return {"messages": list(result.messages), "boxes": {str(i): letters(box(i)) for i in (0, 2, 3, 5)},
            "table": [[letters(cell) for cell in row.children] for row in alignment.children], "math": atoms,
            "box0_tail": [n.kind for n in box(0).children],
            "glue": [box(0).children[1].get("value").width, box(0).children[1].get("value").stretch_order],
            "kern": box(0).children[2].get("width"), "penalty": box(0).children[3].get("value")}


def native_observations(log):
    errors = re.findall(r"^! (.*)$", log, re.M)
    if errors != ["OK."] * 5 or "OBS:DONE" not in log:
        raise ValueError(f"Unexpected native diagnostics or incomplete execution: {errors}")
    boxes = {m[1]: m[2] for m in re.finditer(r"> \\box(\d+)=\n(.*?)\n! OK\.", log, re.S)}
    if set(boxes) != {"0", "2", "3", "5"}:
        raise ValueError("Missing native box observation")
    block = re.search(r"### math mode.*?\n(.*?)### restricted horizontal", log, re.S)
    if not block:
        raise ValueError("Missing native math list")
    atoms = []
    for line in block[1].splitlines():
        if match := re.fullmatch(r"\\math(ord|bin|op)(\\limits)?", line):
            atoms.append({"class": match[1], "nucleus": [], "sup": [], "sub": [], "limits": "limits" if match[2] else None})
        elif match := re.fullmatch(r"([.^_]*)\\fam(\d+) (.)", line):
            role = "sup" if match[1].startswith("^") else "sub" if match[1].startswith("_") else "nucleus"
            atoms[-1][role].append([int(match[2]), ord(match[3])])
    table = []
    for line in boxes["2"].splitlines():
        if line.startswith(r".\hbox"):
            table.append([])
        elif line.startswith(r"..\hbox"):
            table[-1].append("")
        elif match := re.fullmatch(r"\.\.\.\\f (.)", line):
            table[-1][-1] += match[1]
    kinds = []
    for line in boxes["0"].splitlines()[1:]:
        match = re.match(r"\.\\(f|glue|kern|penalty)\b", line)
        if match:
            kinds.append("character" if match[1] == "f" else match[1])
    if r".\glue 2.0 plus 1.0fil" not in boxes["0"] or r".\kern 3.0" not in boxes["0"] or r".\penalty 7" not in boxes["0"]:
        raise ValueError("Native quantity observations changed")
    return {"messages": re.findall(r"OBS:(?:WIDTH(?:-SCOPE)?:[^\s]+|DONE)", log),
            "boxes": {key: "".join(re.findall(r"^\.+\\f (.)$", value, re.M)) for key, value in boxes.items()},
            "table": table, "math": atoms, "box0_tail": kinds, "glue": [131072, 1], "kern": 196608, "penalty": 7}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdftex", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    native = subprocess.run([str(args.pdftex.resolve()), "-ini", "-etex", "-interaction=nonstopmode",
        "-output-directory=" + str(output), "content-construction-native.tex"], cwd=FIXTURES,
        capture_output=True, timeout=60)
    log = (output / "content-construction-native.log").read_text(encoding="utf-8").replace("\r\n", "\n")
    if native.returncode != 1:
        raise ValueError(f"Expected TeX's diagnostic exit 1, got {native.returncode}")
    expected = native_observations(log)
    result = fixture_build()
    if result.status != "completed":
        raise ValueError(result.boundary)
    actual = observations(result)
    receipt = {"schema": "pytexml-content-native/1", "status": "matched" if actual == expected else "mismatch",
        "native_version": native.stdout.decode(errors="replace").splitlines()[0],
        "executable_sha256": hashlib.sha256(args.pdftex.read_bytes()).hexdigest(),
        "log_sha256": hashlib.sha256(log.encode()).hexdigest(),
        "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURES.glob("content-construction*.tex")},
        "actual": actual, "expected": expected,
        "scope": "selected box contents, quantities, table cells, math atoms and scripts; no geometry or rendering equivalence"}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
