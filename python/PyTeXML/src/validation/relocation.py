"""Qualify a prepared payload without staging any raw manuscript sources.

The compiler's installed bundle/cache and fonts remain validation dependencies.
Its filesystem dependency receipt must contain only staged payload/driver files
and temporary build products. This qualifies the exercised render, not unknown
branches or all possible macro invocations.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import tempfile

from ..source_io import SourceStore
from .render import RenderConfig, compiler_environment, render_one


def _words(text):
    """Decode Makefile whitespace escapes without destroying Windows paths."""
    word, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] in " \t\r\n#":
            index += 1
            char = text[index]
            if char in "\r\n":
                index += 1
                continue
            word.append(char)
        elif char.isspace():
            if word:
                yield "".join(word)
                word = []
        else:
            word.append(char)
        index += 1
    if word:
        yield "".join(word)


def audit_dependencies(rules, cwd, staged, build):
    if not rules.is_file():
        return {"status": "missing_receipt", "inputs": [], "outside": []}
    text = rules.read_text(encoding="utf-8")
    if " : " not in text:
        return {"status": "unsupported_receipt", "inputs": [], "outside": [], "raw": text}
    inputs, outside, missing = [], [], []
    for name in dict.fromkeys(_words(text.split(" : ", 1)[1])):
        path = (cwd / name).resolve()
        if path.is_relative_to(build) and not path.is_file():
            # Tectonic's Makefile writer prefixes relative filesystem inputs
            # with outdir, even when they were read from the input cwd. Accept
            # this convention only when the corresponding staged file exists.
            candidate = (cwd / path.relative_to(build)).resolve()
            if candidate.is_relative_to(staged) and candidate.is_file():
                path = candidate
        if (path.is_relative_to(staged) or path.is_relative_to(build)) and not path.is_file():
            missing.append(name)
        elif path.is_relative_to(staged):
            inputs.append({"path": path.relative_to(staged).as_posix(), "role": "payload_or_driver"})
        elif path.is_relative_to(build):
            inputs.append({"path": path.relative_to(build).as_posix(), "role": "build_product"})
        else:
            outside.append(str(path))
    return {"status": "external_dependencies" if outside else "unresolved_receipt" if missing else
            "qualified" if inputs else "empty_receipt", "raw_receipt": text,
            "inputs": inputs, "outside": outside, "missing": missing}


def qualify_relocation(prepared_dir, output_dir, config, *, raw_dirs=(), output_format="pdf"):
    config.validate()
    prepared, output = Path(prepared_dir).resolve(), Path(output_dir).resolve()
    raw_dirs = tuple(Path(p).resolve() for p in raw_dirs)
    for source in (prepared, *raw_dirs):
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("Qualification output must be separate from input trees")
    hidden = sorted({p for root in raw_dirs for p in SourceStore(root, [prepared]).files})
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "pytexml-relocation/1", "status": "failed",
              "raw_source_staged": False, "hidden_raw_files": len(hidden),
              "compiler": str(config.tectonic.resolve()), "only_cached": config.only_cached,
              "bundle": config.bundle, "format": output_format,
              "scope": "The exercised compilation with only prepared payload files; engine bundle/cache and configured fonts are allowed. XDV qualification does not establish PDF rendering."}
    with tempfile.TemporaryDirectory(prefix=".relocated-", dir=output) as directory:
        work = Path(directory)
        env, report["fonts"] = compiler_environment(config, work)
        for variable in ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS", "TEXMFHOME", "TEXMFOUTPUT"):
            env.pop(variable, None)
        report["render"] = render_one(prepared, "master.tex", "prepared", output, work, config, env,
                                      dependency_audit=True, hidden_inputs=hidden, output_format=output_format)
        report["status"] = "qualified" if report["render"]["status"] in {"rendered", "compiled"} else "incomplete"
    report["temporary_inputs_removed"] = True
    (output / "relocation.json").write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--raw-source", type=Path, action="append", default=[])
    parser.add_argument("--tectonic", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--bundle")
    parser.add_argument("--font-dir", type=Path, action="append", default=[])
    parser.add_argument("--format", choices=("pdf", "xdv"), default="pdf")
    args = parser.parse_args()
    report = qualify_relocation(args.prepared, args.output, RenderConfig(args.tectonic,
        timeout_seconds=args.timeout, bundle=args.bundle, font_dirs=tuple(args.font_dir)),
        raw_dirs=args.raw_source, output_format=args.format)
    print(json.dumps({"status": report["status"], "report": str(args.output / "relocation.json")}))
    return 0 if report["status"] == "qualified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
