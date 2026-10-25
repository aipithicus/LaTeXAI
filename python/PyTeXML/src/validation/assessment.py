"""Pure projections of qualification evidence; no independently stored verdict.

Serialized operational status fields are never inputs to these functions. Log
knowledge comes from diagnostic resources; this module only combines checks.
"""
from __future__ import annotations


def render_status(checks, output_format):
    outcome = lambda name: checks.get(name, {}).get("outcome", "not_run")
    if outcome("execution") == "timeout":
        return "timeout"
    if (outcome("execution") != "passed" or outcome("output_inspection") != "passed" or
            any(outcome(name) == "failed" for name in ("staging", "tex_compilation", "pdf_generation"))):
        return "failed"
    if outcome("dependency_audit") not in {"passed", "not_requested"}:
        return "unqualified"
    return "rendered" if output_format == "pdf" else "compiled"


def qualified(run):
    checks = run.get("checks", {})
    return (render_status(checks, run.get("format")) in {"rendered", "compiled"} and
            checks.get("dependency_audit", {}).get("outcome") == "passed")


def baseline_comparison(original, prepared, *, comparable=False):
    """Same specific failure in a paired configuration, never generic engine text."""
    def primary(run):
        checks = run.get("checks", {})
        return {(d["code"], tuple(sorted(d["signature"].items()))): d["id"]
                for d in run.get("diagnostics", []) if d["role"] == "primary"
                and d["phase"] != "dependency_audit"
                and checks.get(d["phase"], {}).get("outcome") == "failed"}
    if not comparable:
        return {"outcome": "incomparable", "matches": []}
    left, right = primary(original), primary(prepared)
    matches = [{"code": key[0], "details": dict(key[1]), "original": left[key], "prepared": right[key]}
               for key in sorted(left.keys() & right.keys())]
    if matches and left.keys() == right.keys():
        outcome = "same_failure"
    elif render_status(original["checks"], original["format"]) in {"rendered", "compiled"}:
        outcome = "baseline_passed"
    elif left and right:
        outcome = "different_failure"
    else:
        outcome = "insufficient_evidence"
    return {"outcome": outcome, "matches": matches,
            "scope": "Same configured engine/environment in this paired invocation; no claim of source fidelity."}


def summarize(report):
    """Compute UI/CLI summary every time from checks and diagnostic evidence.

    No summary is stored in receipts. Multiple findings can coexist, and an XDV
    check cannot turn a requested PDF qualification into a pass.
    """
    run = report.get("render", report.get("prepared", report))
    checks = run.get("checks", {})
    if not checks:
        return {"schema": "pytexml-assessment/1", "classification": "INDETERMINATE", "findings": [],
                "explanation": "This receipt has no structured check evidence."}
    findings = []
    for diagnostic in run.get("diagnostics", []):
        failed = checks.get(diagnostic["phase"], {}).get("outcome") == "failed"
        if failed and diagnostic["category"] in {"payload_dependency_failure", "environment_limitation"}:
            findings.append({"category": diagnostic["category"].upper(), "diagnostic": diagnostic["id"],
                             "code": diagnostic["code"], "remediation": diagnostic["remediation"]})
    baseline = (baseline_comparison(report["original"], run, comparable=report.get("paired_configuration") is True)
                if "original" in report else {"outcome": "not_run", "matches": []})
    if baseline.get("outcome") == "same_failure":
        findings.append({"category": "BASELINE_REPRODUCED", "evidence": baseline["matches"]})
    elif baseline.get("outcome") == "baseline_passed" and render_status(checks, run["format"]) == "failed":
        findings.append({"category": "PREPARED_ONLY_FAILURE", "evidence": "baseline_comparison"})
    categories = {finding["category"] for finding in findings}
    if qualified(run):
        classification = "QUALIFIED"
    else:
        classification = next((category for category in ("PAYLOAD_DEPENDENCY_FAILURE", "ENVIRONMENT_LIMITATION",
            "BASELINE_REPRODUCED", "PREPARED_ONLY_FAILURE") if category in categories), "INDETERMINATE")
    xdv = report.get("xdv_check", {})
    same_payload = bool(run.get("input_fingerprint")) and run.get("input_fingerprint") == xdv.get("input_fingerprint")
    return {"schema": "pytexml-assessment/1", "classification": classification, "format": run["format"], "findings": findings,
            "baseline_comparison": baseline,
            "nonpassing_checks": [{"check": name, **check} for name, check in checks.items()
                                  if check["outcome"] != "passed" and
                                  not (name == "pdf_generation" and run["format"] == "xdv")],
            "compilation_isolation": "qualified" if qualified(run) or (same_payload and qualified(xdv)) else "not_established",
            "pdf_qualified": run["format"] == "pdf" and qualified(run),
            "scope": "Exercised configuration only; compilation and dependency isolation do not establish manuscript fidelity."}
