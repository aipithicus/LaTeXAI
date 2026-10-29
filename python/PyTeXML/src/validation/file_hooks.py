"""Reproducible file-event witnesses using preparation and native render adapters.

Development instrument only. Exact page pixels and ordered diagnostics augment
the adapter's content observations; they do not qualify other hook APIs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from ..prepare.pipeline import preprocess_paper
from .render import RenderConfig, render_comparison


def qualify(fixture, output, native_dir, kernel):
    import pymupdf
    contract = json.loads((fixture / "contract.json").read_text())
    observed = hashlib.sha256(kernel.read_bytes()).hexdigest()
    if observed != contract["kernel_sha256"]:
        raise ValueError("Kernel source differs from the pinned file-hook witness")
    output.mkdir(parents=True, exist_ok=False)
    _, manifest, prepared, _ = preprocess_paper(str(fixture), str(output / "prepared"),
                                                  root_tex="main.tex", engine_profile="pdftex")
    report = {"contract": contract, "kernel_sha256": observed, "file_events": manifest.file_events,
              "requirements": manifest.requirements, "renders": {}}
    for backend, compiler in (("pdftex", "pdflatex.exe"), ("etex", "latex.exe")):
        target = output / backend
        result = render_comparison(fixture, "main.tex", prepared, target,
            RenderConfig(native_dir / compiler, backend=backend, engine_profile="pdftex",
                         dvipdfmx=native_dir / "dvipdfmx.exe"))
        traces = {side: re.findall(contract["diagnostic_pattern"], (target / f"{side}.log").read_text(errors="replace"), re.M)
                  for side in ("original", "prepared")}
        observation = {"status": result["status"], "traces": traces,
            "trace_matches": all(trace == contract["trace"] for trace in traces.values()),
            "pixel_matches": False}
        if all((target / f"{side}.pdf").is_file() for side in ("original", "prepared")):
            with pymupdf.open(target / "original.pdf") as left, pymupdf.open(target / "prepared.pdf") as right:
                observation["pixel_matches"] = len(left) == len(right) and all(
                    a.rect == b.rect and a.get_pixmap(dpi=144).samples == b.get_pixmap(dpi=144).samples
                    for a, b in zip(left, right))
                rendered = "\n".join(page.get_text() for page in right)
                observation["missing_visible"] = [s for s in contract["visible_required"] if s not in rendered]
                observation["forbidden_visible"] = [s for s in contract["visible_forbidden"] if s in rendered]
                observation["visible_matches"] = not (observation["missing_visible"] or observation["forbidden_visible"])
        report["renders"][backend] = observation
    # Only prepared resources are supplied to this independent read. In particular
    # a/part.tex and b/part.tex are absent, rather than found through raw-source paths.
    _, second, _, _ = preprocess_paper(str(prepared), str(output / "reread"),
                                          root_tex="master.tex", engine_profile="pdftex")
    report["reread"] = {"unresolved": second.unresolved,
                        "raw_inputs_absent": not any(p.name != "master.tex" for p in prepared.rglob("*.tex"))}
    report["passed"] = (not manifest.unresolved and not second.unresolved
        and report["reread"]["raw_inputs_absent"] and all(r["status"] == "rendered"
        and r["trace_matches"] and r["pixel_matches"] and r.get("visible_matches")
        for r in report["renders"].values()))
    (output / "qualification.json").write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--native-dir", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parents[2] / "tests/fixtures/engine/file-hooks")
    args = parser.parse_args()
    result = qualify(args.fixture.resolve(), args.output.resolve(), args.native_dir.resolve(), args.kernel.resolve())
    print(json.dumps({"passed": result["passed"], "renders": result["renders"], "reread": result["reread"]}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
