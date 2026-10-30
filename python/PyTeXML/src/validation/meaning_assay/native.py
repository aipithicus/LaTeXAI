"""Bounded, sequential native probes with explicit environment and receipts."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")


def child_counters(process):
    result = {"cpu_seconds": None, "peak_rss_bytes": None,
              "scope": "native_process_excluding_children", "status": "unavailable"}
    if sys.platform != "win32":
        result["detail"] = "No per-child native counter adapter for this host"
        return result
    try:
        class Memory(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong),
                        *[(name, ctypes.c_size_t) for name in
                          ("peak", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetProcessTimes.argtypes = [ctypes.c_void_p, *([ctypes.POINTER(ctypes.c_ulonglong)] * 4)]
        kernel.GetProcessTimes.restype = ctypes.c_int
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), ctypes.c_ulong]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        values = [ctypes.c_ulonglong() for _ in range(4)]
        if not kernel.GetProcessTimes(int(process._handle), *(ctypes.byref(v) for v in values)):
            raise ctypes.WinError(ctypes.get_last_error())
        result["cpu_seconds"] = (values[2].value + values[3].value) / 1e7
        memory = Memory()
        memory.cb = ctypes.sizeof(memory)
        if not psapi.GetProcessMemoryInfo(int(process._handle), ctypes.byref(memory), memory.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        result.update(peak_rss_bytes=memory.peak, status="measured",
                      method="GetProcessTimes; GetProcessMemoryInfo.PeakWorkingSetSize")
    except OSError as error:
        result["detail"] = str(error)
    return result


class Native:
    def __init__(self, oracle, output, timeout):
        self.oracle, self.output, self.timeout = oracle, output, timeout
        self.receipts = []
        self.env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("TEX", "BIB", "BST"))}
        for name in ("TEXMFHOME", "TEXMFCONFIG", "TEXMFVAR"):
            path = output / name.lower()
            path.mkdir()
            self.env[name] = str(path)
        self.env["max_print_line"] = "1000000"

    def run(self, engine, folder, texfile, *, allow_failure=False):
        command = [str(self.oracle / "bin/windows" / (engine + ".exe")),
                   "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "-recorder", texfile]
        started = time.perf_counter()
        with (folder / "console.log").open("wb") as stream:
            process = subprocess.Popen(command, cwd=folder, env=self.env, stdout=stream, stderr=subprocess.STDOUT)
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                receipt = {"folder": str(folder.relative_to(self.output)), "status": "timeout",
                           "wall_seconds": time.perf_counter() - started, **child_counters(process)}
                receipt["outcome"] = "timeout"
                self.receipts.append(receipt)
                write_json(folder / "process.json", receipt)
                raise
            receipt = {"folder": str(folder.relative_to(self.output)), "command": command,
                       "wall_seconds": time.perf_counter() - started, "returncode": process.returncode,
                       **child_counters(process)}
        self.receipts.append(receipt)
        write_json(folder / "process.json", receipt)
        if process.returncode and not allow_failure:
            raise RuntimeError(f"Native probe failed: {folder / 'console.log'}")
        return process.returncode


def header(output):
    return "\\newwrite\\AssayOut\n\\immediate\\openout\\AssayOut=" + output + "\n\\escapechar=92 \\newlinechar=-1 \\endlinechar=-1\n"


END = "\\immediate\\closeout\\AssayOut\n\\csname @@end\\endcsname\n"


def name_hex(name):
    return name.encode("latin-1").hex()


def cs(name):
    return r"\csname\pdfunescapehex{" + name_hex(name) + r"}\endcsname"


def probe(native, names, number):
    folder = native.output / f"pdf-probe-{number}"
    folder.mkdir()
    lines = [header("meanings.tsv")]
    for index, name in enumerate(names):
        encoded = name_hex(name)
        lines.append(r"\ifcsname\pdfunescapehex{" + encoded + r"}\endcsname"
            + r"\immediate\write\AssayOut{" + str(index) + r"|\pdfescapehex{\expandafter\meaning"
            + cs(name) + r"}}\else\immediate\write\AssayOut{" + str(index) + r"|756e646566696e6564}\fi" + "\n")
    lines.append(END)
    (folder / "probe.tex").write_text("".join(lines), encoding="ascii", newline="\n")
    native.run("pdflatex", folder, "probe.tex")
    result = {}
    for line in (folder / "meanings.tsv").read_text(encoding="ascii").splitlines():
        index, meaning = line.split("|", 1)
        result[names[int(index)]] = bytes.fromhex(meaning).decode("latin-1")
    if len(result) != len(names):
        raise ValueError("Missing or duplicate native meaning records")
    return result


def validate(native, entries, regime, number, *, candidate_displays=None):
    """A fatal record is isolated and reported; subsequent records get a fresh process."""
    from .model import REGIMES
    outcomes = {}
    pending = list(entries)
    attempt = 0
    while pending:
        folder = native.output / f"validate-{regime}-{number}-{attempt}"
        folder.mkdir()
        lines = [header("validation.tsv")]
        assignments = "".join(f"\\catcode{ord(char)}={cat} " for char, cat in REGIMES[regime].items())
        for index, (name, source) in enumerate(pending):
            # The caller supplies the flags on the already-scanned definition.
            lines += [f"\\immediate\\write\\AssayOut{{S|{index}}}\n", "\\begingroup\n", assignments + "\n", source + "\n"]
            if candidate_displays is not None:
                # Compare displays in the assay's default pdfTeX context, not
                # the reconstruction regime (single-letter CS spacing depends
                # on current catcodes). Do not expose an outer macro as a raw
                # token while scanning the write's argument.
                lines.append("\\begingroup\\catcode95=8 \\catcode58=12 \\catcode64=12 "
                    + r"\immediate\write\AssayOut{D|" + str(index)
                    + r"|\pdfescapehex{\expandafter\meaning" + cs("AssayCandidate")
                    + "}}\\endgroup\n")
            lines += [r"\expandafter\ifx" + cs(name) + r"\AssayCandidate"
                      + f"\\immediate\\write\\AssayOut{{R|{index}|1}}"
                      + f"\\else\\immediate\\write\\AssayOut{{R|{index}|0}}\\fi\n", "\\endgroup\n"]
        lines.append(END)
        (folder / "probe.tex").write_text("".join(lines), encoding="ascii", newline="\n")
        code = native.run("pdflatex", folder, "probe.tex", allow_failure=True)
        started, completed = [], {}
        for line in (folder / "validation.tsv").read_text(encoding="ascii").splitlines():
            fields = line.split("|")
            if fields[0] == "S":
                started.append(int(fields[1]))
            elif fields[0] == "R":
                completed[int(fields[1])] = fields[2] == "1"
            elif fields[0] == "D" and candidate_displays is not None:
                candidate_displays[pending[int(fields[1])][0]] = bytes.fromhex(fields[2]).decode("latin-1")
        for index, value in completed.items():
            outcomes[pending[index][0]] = "equal" if value else "unequal"
        if code:
            if not started or started[-1] in completed:
                raise RuntimeError(f"Validation failed outside a candidate: {folder}")
            failed = started[-1]
            outcomes[pending[failed][0]] = "native_error"
            pending = pending[failed + 1:]
            attempt += 1
        else:
            if len(completed) != len(pending):
                raise ValueError("Incomplete native validation records")
            break
    return outcomes
