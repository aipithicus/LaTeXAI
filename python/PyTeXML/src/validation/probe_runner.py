"""Reusable Web2C probe runs with paired staging and retained per-pass evidence.

The manuscript bytes are unchanged. Native TeX remains an observation tool;
matching auxiliary files/opens is scoped evidence, not zero perturbation proof.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from ..source_io import SourceStore
from .checkpoint_state import basis_for, observations, observer_source, validate_plan
from .primitive_census import profile, lexical_candidates
from .tex_trace import parse

AUXILIARY = {".aux", ".toc", ".out", ".lof", ".lot"}
BYPRODUCTS = AUXILIARY | {".log", ".fls", ".blg", ".synctex"}
RESERVED = {"pytexml-observe.tex", "pytexmlprobe.sty"}
HOOKS = {"body": "begindocument/end", "afterlastpage": "enddocument/afterlastpage",
         "afteraux": "enddocument/afteraux", "end": "enddocument/end"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def log_metadata(path):
    errors, packages, listing, decoded, banner = [], None, False, True, None
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                banner = line.rstrip() if banner is None else banner
                decoded &= "\ufffd" not in line
                if line.startswith("! "):
                    errors.append(line[2:].rstrip("\r\n"))
                if line.strip() == "*File List*":
                    packages, listing = [], True
                elif listing and re.fullmatch(r"\s*\*{5,}\s*", line):
                    listing = False
                elif listing:
                    packages.append(line.rstrip("\r\n"))
    return {"diagnostics": errors, "decoded": decoded, "banner": banner, "package_list_raw": packages}


def recorder(path, *, cwd, project, build):
    """Ordered opens, including repetitions. Hashes describe pass-end bytes."""
    records, issues = [], []
    if not path.is_file():
        return {"records": [], "issues": ["missing_recorder"], "status": "incomplete"}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("PWD "):
            cwd = Path(line[4:])
            records.append({"kind": "PWD", "path": str(cwd), "line": number})
            continue
        match = re.fullmatch(r"(INPUT|OUTPUT) (.+)", line)
        if not match:
            issues.append({"line": number, "raw": line})
            continue
        target = (cwd / match[2]).resolve()
        relative = ("project/" + target.relative_to(project).as_posix() if target.is_relative_to(project)
                    else "build/" + target.relative_to(build).as_posix() if target.is_relative_to(build)
                    else target.as_posix())
        exists = target.is_file()
        records.append({"kind": match[1], "path": relative, "resolved": str(target), "line": number,
                        "sha256": digest(target) if exists else None, "hash_at": "pass_end",
                        "status": "observed" if exists else "missing_at_pass_end"})
        if match[1] == "INPUT" and not exists:
            issues.append({"line": number, "kind": "missing_input_at_pass_end", "path": relative})
    return {"records": records, "issues": issues, "status": "complete" if not issues else "incomplete"}


def latex_probe(plan, *, trace):
    hooks = plan.get("hooks", {name: HOOKS[name] for name in plan["checkpoints"] if name in HOOKS})
    result = [r"\ProvidesPackage{pytexmlprobe}[selected native observations]",
              r"\input{pytexml-observe.tex}", r"\listfiles"]
    for label, hook in hooks.items():
        if label not in plan["checkpoints"] or not re.fullmatch(r"[A-Za-z/]+", hook):
            raise ValueError("Invalid checkpoint hook")
        result.append(r"\AddToHook{" + hook + r"}{\PyTeXMLCheckpoint{" + label + "}}")
    if trace:
        result.append(r"\tracingcommands=3\relax")
    if "preamble" in plan["checkpoints"]:
        result.append(r"\PyTeXMLCheckpoint{preamble}")
    return "\n".join(result) + "\n"


def run_probe(source, entry, executable, output, plan, *, mode="latex", passes=1, timeout=120,
              initial_state, initial_aux=None, expected_ok=0, trace=True, parse_trace=False):
    source, executable, output = Path(source).resolve(), Path(executable).resolve(), Path(output).resolve()
    validate_plan(plan)
    if mode not in {"latex", "initex"} or type(passes) is not int or passes < 1:
        raise ValueError("Choose latex or initex and a positive pass count")
    if not math.isfinite(timeout) or timeout <= 0 or not executable.is_file():
        raise ValueError("An explicit executable and finite positive timeout are required")
    if output.exists():
        raise ValueError("Probe output must be a new directory")
    if not re.fullmatch(r"[A-Za-z0-9_./ -]+\.tex", entry) or Path(entry).is_absolute() or ".." in Path(entry).parts:
        raise ValueError("Entry must be a relative TeX filename without TeX syntax")
    store = SourceStore(source, excluded_dirs=[output])
    if store.inventory_errors:
        raise ValueError(f"Source inventory failed: {store.inventory_errors}")
    if not store.contains(source / entry):
        raise ValueError("Entry is not in the source inventory")
    files = {p.relative_to(source).as_posix(): store.read_bytes(p) for p in store.files
             if p.suffix.lower() not in BYPRODUCTS}
    if any(Path(name).name in RESERVED for name in files):
        raise ValueError("Project contains a reserved probe filename")
    auxiliary = {}
    if initial_aux is not None:
        aux_store = SourceStore(Path(initial_aux))
        if aux_store.inventory_errors:
            raise ValueError("Initial auxiliary inventory failed")
        auxiliary = {p.relative_to(aux_store.root).as_posix(): aux_store.read_bytes(p)
                     for p in aux_store.files if p.suffix in AUXILIARY}
    nonce = secrets.token_hex(8)
    observer = observer_source(plan, nonce)
    package = latex_probe(plan, trace=trace) if mode == "latex" else ""
    env = {**os.environ, "PATH": str(executable.parent) + os.pathsep + os.environ.get("PATH", ""),
           "max_print_line": "10000", "error_line": "254", "half_error_line": "238"}
    output.mkdir(parents=True)
    manifest = {"schema": "pytexml-probe-run/1", "status": "running", "nonce": nonce, "plan": plan,
                "mode": mode, "passes_requested": passes, "timeout_seconds": timeout,
                "executable": str(executable), "executable_sha256": digest(executable),
                "observer_sha256": hashlib.sha256(observer.encode()).hexdigest(),
                "package_sha256": hashlib.sha256(package.encode()).hexdigest(),
                "print_environment": {k: env[k] for k in ("max_print_line", "error_line", "half_error_line")},
                "search_environment": {k: env[k] for k in sorted(env) if k.startswith(("TEX", "MIKTEX"))},
                "source": str(source), "entry": entry, "arms": {},
                "source_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                "scope": "Same staged manuscript bytes, initial auxiliaries, jobname and pass count; selected observations only."}
    write_json(output / "manifest.json", manifest)
    deadline = time.monotonic() + timeout
    try:
        for arm in ("baseline", "probed"):
            root = output / arm
            project, build = root / "project", root / "build"
            project.mkdir(parents=True)
            build.mkdir()
            for name, data in files.items():
                target = project / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for name, data in auxiliary.items():
                target = build / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            # The explicit-source INITEX mode uses the same input/call sites in
            # both arms; its baseline observer is a named no-op.
            observer_dir = (project / entry).parent
            (observer_dir / "pytexml-observe.tex").write_text(
                observer if arm == "probed" else "\\def\\PyTeXMLCheckpoint#1{}\n", encoding="ascii", newline="\n")
            if mode == "latex" and arm == "probed":
                (observer_dir / "pytexmlprobe.sty").write_text(package, encoding="ascii", newline="\n")
            arm_receipt = {"passes": []}
            manifest["arms"][arm] = arm_receipt
            for number in range(1, passes + 1):
                retained = root / f"pass-{number}"
                retained.mkdir()
                # A pass's common basis includes the actual auxiliaries before
                # that pass, so divergent reruns cannot be compared as identical.
                before = {"@aux/" + p.relative_to(build).as_posix(): p.read_bytes()
                          for p in build.rglob("*") if p.is_file() and p.suffix in AUXILIARY}
                for name, data in before.items():
                    saved = retained / "initial-aux" / name.removeprefix("@aux/")
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    saved.write_bytes(data)
                current = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob("*")
                           if p.is_file() and p.name not in RESERVED}
                basis = basis_for({**current, **before}, entry, initial_state=initial_state, pass_number=number)
                job = Path(entry).stem
                command = [str(executable), "-interaction=nonstopmode", "-no-shell-escape", "-recorder",
                           "-output-directory=" + str(build), "-jobname=" + job]
                if mode == "initex":
                    command += ["-ini", "-etex", ('\\tracingcommands=3 ' if trace and arm == "probed" else '')
                                + '\\input "' + Path(entry).name + '" ']
                else:
                    command += [(r"\RequirePackage{pytexmlprobe}" if arm == "probed" else "")
                                + '\\input{"' + Path(entry).name + '"}']
                attempt = {"number": number, "status": "running", "command": command, "basis": basis}
                arm_receipt["passes"].append(attempt)
                write_json(output / "manifest.json", manifest)
                started = time.monotonic()
                with (retained / "console.txt").open("wb") as console:
                    try:
                        process = subprocess.run(command, cwd=observer_dir, env=env, stdout=console,
                                                 stderr=subprocess.STDOUT, timeout=max(.001, deadline - time.monotonic()), check=False)
                        attempt["returncode"] = process.returncode
                    except subprocess.TimeoutExpired:
                        attempt["returncode"], attempt["error"] = None, "timeout"
                attempt["elapsed_seconds"] = time.monotonic() - started
                for suffix in (".log", ".fls"):
                    path = build / (job + suffix)
                    if path.is_file():
                        (retained / (job + suffix)).write_bytes(path.read_bytes())
                log_path = retained / (job + ".log")
                metadata = log_metadata(log_path)
                complete = bool(metadata["banner"]) and metadata["decoded"] and metadata["diagnostics"] == ["OK."] * expected_ok and attempt["returncode"] == (1 if expected_ok else 0)
                attempt.update({**metadata, "log_sha256": digest(log_path) if log_path.is_file() else None,
                                "auxiliary": {p.relative_to(build).as_posix(): digest(p) for p in build.rglob("*")
                                              if p.is_file() and p.suffix in AUXILIARY}})
                for name in attempt["auxiliary"]:
                    saved = retained / "auxiliary" / name
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    saved.write_bytes((build / name).read_bytes())
                closure = recorder(retained / (job + ".fls"), cwd=observer_dir, project=project, build=build)
                write_json(retained / "files.json", closure)
                complete &= closure["status"] == "complete"
                attempt["input_sequence"] = [{k: r[k] for k in ("path", "sha256", "status")} for r in closure["records"]
                                             if r["kind"] == "INPUT" and Path(r["path"]).name not in RESERVED]
                if arm == "probed":
                    if log_path.is_file():
                        with log_path.open(encoding="utf-8", errors="replace") as lines:
                            state = observations(lines, plan, nonce, basis, producer={"engine": str(executable), "sha256": manifest["executable_sha256"]},
                                                 completed=complete, wrap_column=10000)
                    else:
                        state = observations([], plan, nonce, basis, producer={}, completed=False)
                    write_json(retained / "checkpoints.json", state)
                    complete &= state["status"] == "complete"
                    if trace and log_path.is_file():
                        with log_path.open(encoding="utf-8", errors="replace") as lines:
                            census = profile(lines, nonce=nonce, checkpoints=plan["checkpoints"], completed=complete)
                        paths = [r["resolved"] for r in closure["records"] if r["kind"] == "INPUT"
                                 and Path(r["path"]).suffix in {".tex", ".sty", ".cls", ".def", ".ltx"}
                                 and Path(r["path"]).name not in RESERVED]
                        census["lexical_candidates"] = lexical_candidates(paths, {"the", "number", "csname", "expandafter"})
                        write_json(retained / "profile.json", census)
                        complete &= census["status"] == "complete"
                    if parse_trace:
                        try:
                            parsed = parse(log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else "",
                                           expected_ok=expected_ok, marked=False, strict=False, wrap_column=10000)
                            write_json(retained / "trace.json", parsed)
                            complete &= not parsed["issues"]
                        except ValueError as error:
                            attempt["parser_error"] = str(error)
                            complete = False
                attempt["status"] = "complete" if complete else "incomplete"
                write_json(retained / "receipt.json", attempt)
                write_json(output / "manifest.json", manifest)
                if not complete:
                    break
        arms = manifest["arms"]
        complete = all(len(a["passes"]) == passes and all(p["status"] == "complete" for p in a["passes"]) for a in arms.values())
        comparisons = [{"pass": l["number"], "auxiliary_equal": l["auxiliary"] == r["auxiliary"],
                        "ordered_inputs_equal": l["input_sequence"] == r["input_sequence"]}
                       for l, r in zip(arms["baseline"]["passes"], arms["probed"]["passes"])]
        manifest.update({"status": "complete" if complete else "incomplete", "noninterference": {
            "status": "not_assessed" if not complete else "observed_equal" if all(c["auxiliary_equal"] and c["ordered_inputs_equal"] for c in comparisons) else "observed_difference",
            "passes": comparisons, "scope": "Auxiliary hashes and ordered recorder inputs, excluding the declared observer files; not a universal non-interference claim."}})
    except (OSError, ValueError) as error:
        manifest.update(status="incomplete", error=str(error))
        for arm in manifest["arms"].values():
            for attempt in arm["passes"]:
                if attempt["status"] == "running":
                    attempt.update(status="incomplete", error=str(error))
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--initial-state", required=True)
    parser.add_argument("--initial-aux", type=Path)
    parser.add_argument("--mode", choices=("latex", "initex"), default="latex")
    parser.add_argument("--passes", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--expected-ok", type=int, default=0)
    parser.add_argument("--no-trace", action="store_true")
    parser.add_argument("--parse-trace", action="store_true")
    args = parser.parse_args()
    receipt = run_probe(args.source, args.entry, args.executable, args.output, json.loads(args.plan.read_text()),
                        mode=args.mode, passes=args.passes, timeout=args.timeout, initial_state=args.initial_state,
                        initial_aux=args.initial_aux, expected_ok=args.expected_ok, trace=not args.no_trace, parse_trace=args.parse_trace)
    print(json.dumps({"status": receipt["status"], "output": str(args.output), "noninterference": receipt.get("noninterference")}))
    return 0 if receipt["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
