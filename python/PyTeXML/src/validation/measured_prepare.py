"""Run the public preparation CLI with worker-owned peak-memory evidence.

This measures the Python worker, including native libraries loaded into it.
It does not claim a process-tree peak. A killed worker cannot publish a final
high-water mark; the parent records that absence rather than inventing zero.
"""
import ctypes
import json
from pathlib import Path
import platform
import runpy
import sys
from time import perf_counter


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
    receipt, *arguments = sys.argv[1:]
    started = perf_counter()
    try:
        sys.argv = ["src.prepare.pipeline", *arguments]
        runpy.run_module("src.prepare.pipeline", run_name="__main__")
    finally:
        data = {"schema": "pytexml-worker-performance/1",
                "worker_wall_seconds": perf_counter() - started, **peak_memory()}
        target = Path(receipt)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(target)


if __name__ == "__main__":
    main()
