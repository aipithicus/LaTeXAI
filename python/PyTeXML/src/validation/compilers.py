"""Explicit compiler adapters and observed profile compatibility.

Reference engines are instruments. No adapter hides or redefines primitives to
make an engine appear compatible with an emulation profile.
"""
from dataclasses import dataclass
import hashlib
import re
import subprocess
import time
from types import MappingProxyType

from ..engine.profiles import engine_profile


def tectonic_command(config, source, build, output_format, rules=None, hidden=()):
    command = [str(config.compiler.resolve()), "-X", "compile", "--untrusted", "--keep-logs",
               "--print", "--outdir", str(build)]
    if output_format != "pdf":
        command += ["--outfmt", output_format]
    if config.only_cached:
        command.append("--only-cached")
    if config.bundle:
        command += ["--bundle", config.bundle]
    if rules is not None:
        command += ["--makefile-rules", str(rules)]
        for path in hidden:
            command += ["--hide", str(path)]
    return command + [str(source)]


def web2c_command(config, source, build, output_format, rules=None, hidden=()):
    if output_format != "pdf" or rules is not None or hidden:
        raise ValueError("Native TeX rendering supports paired PDF observations; filesystem closure auditing is not yet implemented")
    return [str(config.compiler.resolve()), "-interaction=nonstopmode", "-halt-on-error",
            "-no-shell-escape", "-recorder", "-output-directory=" + str(build), str(source)]


@dataclass(frozen=True, slots=True)
class CompilerBackend:
    name: str
    output: str
    command: object


BACKENDS = MappingProxyType({
    "tectonic": CompilerBackend("tectonic", "pdf", tectonic_command),
    "pdftex": CompilerBackend("pdftex", "pdf", web2c_command),
    "etex": CompilerBackend("etex", "dvi", web2c_command),
})


def compile_document(config, source, build, log_path, env, output_format, rules=None, hidden=()):
    """Native formats need reruns; bound the entire compilation, not each pass."""
    command = BACKENDS[config.backend].command(config, source, build, output_format, rules, hidden)
    deadline = time.monotonic() + config.timeout_seconds
    passes, previous = [], None
    limit = 1 if config.backend == "tectonic" else 4
    for number in range(1, limit + 1):
        # Keep the final pass as diagnostic evidence. Earlier unresolved-reference
        # warnings are stale after successful convergence.
        with log_path.open("wb") as log:
            result = subprocess.run(command, cwd=source.parent, env=env, stdout=log,
                stderr=subprocess.STDOUT,
                timeout=config.timeout_seconds if limit == 1 else max(0.001, deadline - time.monotonic()), check=False)
        state = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in build.iterdir()
                 if p.suffix in {".aux", ".toc", ".out", ".lof", ".lot"} and p.is_file()}
        passes.append({"number": number, "returncode": result.returncode, "auxiliary_hashes": state})
        if result.returncode or limit == 1 or state == previous or not state:
            return result, passes, result.returncode == 0
        previous = state
    return result, passes, False


def probe_profile(config, work, env):
    """Test the actual executable/format's names, including negative exposure."""
    profile = engine_profile(config.engine_profile)
    expected = {"eTeXversion": True, **{name: True for name in sorted(profile.extensions)},
                **{name: False for name in sorted(profile.absent)}}
    source = work / "profile-probe.tex"
    source.write_text("\n".join(
        "\\ifdefined\\" + name + "\\immediate\\write16{PYTEXML-PROFILE " + name
        + "=present}\\else\\immediate\\write16{PYTEXML-PROFILE " + name + "=absent}\\fi"
        for name in expected) +
        "\n\\expandafter\\ifx\\csname @@end\\endcsname\\relax\\end"
        "\\else\\csname @@end\\endcsname\\fi\n", encoding="ascii", newline="\n")
    command = BACKENDS[config.backend].command(config, source, work, "pdf")
    result = subprocess.run(command, cwd=work, env=env, capture_output=True,
                            timeout=config.timeout_seconds, check=False)
    transcript = result.stdout + result.stderr
    log = work / "profile-probe.log"
    if log.is_file():
        transcript += log.read_bytes()
    observed = {name.decode("ascii"): value == b"present" for name, value in
                re.findall(rb"PYTEXML-PROFILE ([A-Za-z]+)=(present|absent)", transcript)}
    mismatches = {name: {"expected": present, "observed": observed.get(name)}
                  for name, present in expected.items() if observed.get(name) != present}
    return {"profile": profile.record(), "backend": config.backend, "returncode": result.returncode,
            "observed": observed, "mismatches": mismatches,
            "status": "matched" if result.returncode == 0 and not mismatches else "mismatch",
            "scope": "Primitive exposure in the configured executable and format; not complete semantic equivalence",
            "transcript": transcript.decode("utf-8", errors="replace")}
