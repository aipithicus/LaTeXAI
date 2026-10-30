"""Run the public preparation CLI with worker-owned resource evidence.

This measures the Python worker, including native libraries loaded into it.
It does not claim a process-tree peak. A killed worker cannot publish a final
high-water mark; the parent records that absence rather than inventing zero.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import runpy
import sys
import time


class CpuProfile:
    """Opt-in current-thread CPU attribution; no package-cost inference."""
    def __init__(self):
        import cProfile
        self.profile = cProfile.Profile(timer=time.thread_time)

    def start(self):
        self.profile.enable()

    def stop(self):
        self.profile.disable()

    def write(self, folder):
        import pstats
        binary = folder / "cpu-profile.prof"
        report = folder / "cpu-profile.json"
        self.profile.dump_stats(str(binary))
        stats = pstats.Stats(self.profile)
        project = Path(__file__).resolve().parents[2]
        functions = []
        for (file, line, name), (primitive, calls, own, cumulative, _) in stats.stats.items():
            path = Path(file)
            if path.is_absolute() and path.is_relative_to(project):
                file = path.relative_to(project).as_posix()
            functions.append({"file": file, "line": line, "function": name,
                "primitive_calls": primitive, "calls": calls,
                "self_cpu_seconds": own, "cumulative_cpu_seconds": cumulative})
        functions.sort(key=lambda row: (-row["self_cpu_seconds"], row["file"], row["line"], row["function"]))
        data = {"schema": "pytexml-cpu-profile/1", "method": "cProfile(time.thread_time)",
                "scope": "preparation_main_thread", "instrumented": True,
                "functions": functions}
        report.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        lines = ["# Preparation CPU profile", "",
                 "Current-thread CPU time, measured with cProfile and time.thread_time.",
                 "Instrumentation adds overhead. These are diagnostic timings, not benchmark timings.",
                 "Other threads and child processes are excluded. This is function attribution, not package attribution.", "",
                 "[All function records](cpu-profile.json) · [Raw caller graph](cpu-profile.prof)", ""]
        for title, rows in (("Largest self CPU costs", functions),
                            ("Largest inclusive CPU costs", sorted(functions, key=lambda row: -row["cumulative_cpu_seconds"]))):
            lines += [f"## {title}", "", "Inclusive costs overlap; do not add them together.", "",
                      "| Function | Calls | Self CPU seconds | Inclusive CPU seconds |",
                      "| --- | ---: | ---: | ---: |"]
            for row in rows[:20]:
                label = f"{row['file']}:{row['line']} {row['function']}".replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {label} | {row['calls']} | {row['self_cpu_seconds']:.6f} | {row['cumulative_cpu_seconds']:.6f} |")
            lines.append("")
        (folder / "cpu-profile.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return {"status": "measured", "method": data["method"], "scope": data["scope"],
                "report": report.name, "raw": binary.name, "summary": "cpu-profile.md"}


def peak_memory():
    result = {"peak_rss_bytes": None, "memory_status": "unavailable",
              "memory_scope": "preparation_worker_process", "platform": platform.platform()}
    try:
        if sys.platform == "win32":
            # PROCESS_MEMORY_COUNTERS: two DWORDs followed by eight SIZE_Ts.
            class Counters(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong),
                    *[(name, ctypes.c_size_t) for name in ("peak", "working", "peak_paged", "paged",
                        "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel.GetCurrentProcess.argtypes = []
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
            psapi.GetProcessMemoryInfo.restype = ctypes.c_int
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            value, method = counters.peak, "GetProcessMemoryInfo.PeakWorkingSetSize"
        elif sys.platform in {"linux", "darwin"}:
            import resource
            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            value *= 1 if sys.platform == "darwin" else 1024
            method = "getrusage(RUSAGE_SELF).ru_maxrss"
        else:
            result["memory_detail"] = "No admitted peak-RSS adapter for this platform"
            return result
        result.update(peak_rss_bytes=int(value), memory_status="measured", memory_method=method)
    except (OSError, ImportError, AttributeError) as error:
        result["memory_detail"] = f"{type(error).__name__}: {error}"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-cpu", action="store_true")
    parser.add_argument("receipt", type=Path)
    args, arguments = parser.parse_known_args()
    profile = CpuProfile() if args.profile_cpu else None
    started = time.perf_counter()
    cpu_started = time.process_time()
    times_started = os.times()
    try:
        if profile:
            profile.start()
        sys.argv = ["src.prepare.pipeline", *arguments]
        runpy.run_module("src.prepare.pipeline", run_name="__main__")
    finally:
        if profile:
            profile.stop()
        wall = time.perf_counter() - started
        cpu = time.process_time() - cpu_started
        times = os.times()
        data = {"schema": "pytexml-worker-performance/2",
                "worker_wall_seconds": wall,
                "cpu_seconds": cpu, "cpu_user_seconds": times.user - times_started.user,
                "cpu_system_seconds": times.system - times_started.system,
                "cpu_status": "measured", "cpu_method": "time.process_time; split: os.times",
                "cpu_clock_resolution_seconds": time.get_clock_info("process_time").resolution,
                "cpu_scope": "preparation_worker_all_threads_during_cli",
                "cpu_seconds_per_wall_second": cpu / wall if wall else None,
                "cpu_profile": {"status": "not_requested"}, **peak_memory()}
        # Capture peaks and totals before exporting the profile. Instrumentation
        # overhead during preparation remains included and is explicitly marked.
        if profile:
            try:
                data["cpu_profile"] = profile.write(args.receipt.parent)
            except OSError as error:
                data["cpu_profile"] = {"status": "failed", "detail": str(error)}
        target = args.receipt
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(target)


if __name__ == "__main__":
    main()
