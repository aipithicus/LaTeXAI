"""Qualify driver events, shipout writes and trace parsing with native probes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .local_measurement import FIXTURES
from .tex_trace import parse, differences
from ..engine.content_builder import ContentBuilder
from ..engine.semantic_drivers import DRIVER, SOURCE_SHA256

INIT = r"\catcode123=1 \catcode125=2 \catcode35=6 \catcode64=11 "


def python_driver():
    sources = {"main.tex": INIT + r"\input hpdftex.def \setbox0=\hbox{\input semantic-driver-source.tex }\copy0\end",
               "semantic-driver-source.tex": (FIXTURES / "semantic-driver-source.tex").read_text(),
               "hpdftex.def": (FIXTURES / "drivers/hpdftex.def").read_text()}
    return ContentBuilder(sources, semantic_drivers={"hpdftex.def": DRIVER}).build("main.tex")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    def run(executable, source, *, latex=False, ok=0):
        command = [str((args.bin / executable).resolve()), "-interaction=nonstopmode", "-output-directory=" + str(output),
                   "-jobname=" + Path(source).stem]
        command += ([r"\RequirePackage{probe}\input{" + source + "}"] if latex else ["-ini", "-etex", source])
        process = subprocess.run(command, cwd=FIXTURES, capture_output=True, timeout=60,
                                 env={**os.environ, "max_print_line": "10000"})
        log = (output / (Path(source).stem + ".log")).read_text().replace("\r\n", "\n")
        if process.returncode != (1 if ok else 0) or re.findall(r"^! (.*)$", log, re.M) != ["OK."] * ok:
            raise ValueError("Native probe failed: " + log)
        return log, process.stdout.decode(errors="replace").splitlines()[0]
    driver_log, version = run("pdflatex.exe", "semantic-driver-native.tex", latex=True, ok=2)
    trace = parse(driver_log, expected_ok=2)
    if len(trace["boxes"]) != 1:
        raise ValueError("Missing driver showbox observation")
    commands = [c["command"] for c in trace["commands"]]
    if not any(c.startswith(r"\count") for c in commands) or r"\number" not in commands:
        raise ValueError("Missing canonical primitive trace observations")
    if any(c.startswith((r"\mycount", r"\mythe", r"\mynumber")) for c in commands):
        raise ValueError("Alias leaked into a canonical command report")
    if not any(m["header"].startswith(r"\wrap") for m in trace["macro_calls"]):
        raise ValueError("Missing macro trace")
    driver = python_driver()
    # Messages contain only literal observations after expansion. Match at the
    # start of a log line, excluding the macro replacement text in the trace.
    expected_messages = [m.strip() for m in re.findall(r"^ *OBS:(?:ALIAS:\d+|NUMBER:\d+|ANCHOR:[01]|SCOPE:\d+|DONE)\b", driver_log, re.M)]
    events = []
    def walk(node):
        yield node
        for child in node.children:
            yield from walk(child)
    box = driver.context.state_cells.read("box:0") if driver.status == "completed" else None
    if box:
        events = [dict(n.attributes) for n in walk(box) if n.kind == "driver_event"]
    semantic = {"messages": list(driver.messages),
                "anchors": [e["destination"] for e in events if e["action"] == "anchor_start"],
                "links": [e["destination"] for e in events if e["action"] == "link_start"]}
    expected = {"messages": expected_messages,
                "anchors": re.findall(r"\\pdfdest name\{([^}]+)\}", driver_log),
                "links": []}
    # Restrict to showbox payload, so macro traces cannot masquerade as nodes.
    dump = re.search(r"> \\box0=\n(.*?)\n! OK\.", driver_log, re.S)[1]
    expected["anchors"] = re.findall(r"\\pdfdest name\{([^}]+)\}", dump)
    expected["links"] = re.findall(r"/URI\(([^)]+)\)|goto name\{([^}]+)\}", dump)
    expected["links"] = [a or b for a, b in expected["links"]]
    lifecycle_log, _ = run("pdftex.exe", "lifecycle.tex")
    lifecycle = ContentBuilder({p.name: p.read_text() for p in FIXTURES.glob("lifecycle*.tex")}).build("lifecycle.tex")
    actual_writes = [n["attributes"]["text"] for n in lifecycle.content["lifecycle"]
                     if n["attributes"]["stream"] == 16]
    expected_writes = re.findall(r"^OBS:WRITE:[^\s]+", lifecycle_log, re.M)
    expected = {"driver": expected, "writes": expected_writes,
                "auxiliary": (output / "references.aux").read_text(),
                "reference": re.findall(r"OBS:REFERENCE:[a-z.]+:\d+", lifecycle_log)}
    actual = {"driver": semantic, "writes": actual_writes,
              "auxiliary": lifecycle.content["virtual_outputs"].get("references.aux", {}).get("text"),
              "reference": [m for m in lifecycle.messages if m.startswith("OBS:REFERENCE:")]}
    diff = differences(expected, actual)
    receipt = {"schema": "pytexml-semantic-native/1",
        "status": "matched" if not diff and driver.status == lifecycle.status == "completed" else "mismatch",
        "differences": diff, "driver_boundary": driver.boundary, "lifecycle_boundary": lifecycle.boundary,
        "actual": actual, "expected": expected,
        "native_version": version, "driver_sha256": SOURCE_SHA256,
        "executables": {name: hashlib.sha256((args.bin / name).read_bytes()).hexdigest() for name in ("pdftex.exe", "pdflatex.exe")},
        "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    [*FIXTURES.glob("semantic-driver*.tex"), *FIXTURES.glob("lifecycle*.tex"), FIXTURES / "probe.sty"]},
        "logs": {"driver": hashlib.sha256(driver_log.encode()).hexdigest(), "lifecycle": hashlib.sha256(lifecycle_log.encode()).hexdigest()},
        "trace_counts": {k: len(v) for k, v in trace.items()},
        "trace_coverage": {"canonical_count_alias": True, "canonical_number_alias": True,
                           "the_inside_message_reported": r"{\the}" in driver_log.split("PYTEXML:BEGIN\n", 1)[1].split("OBS:ALIAS:7", 1)[0],
                           "complete_primitive_census": False},
        "scope": "plain links/anchors, active-anchor state, grouping, alias reports and selected write timing; not full hyperref or page-layout compatibility"}
    (output / "trace.json").write_text(json.dumps(trace, indent=2) + "\n", newline="\n")
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", newline="\n")
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["status"] == "matched" else 1


if __name__ == "__main__":
    raise SystemExit(main())
