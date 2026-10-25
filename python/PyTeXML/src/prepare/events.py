"""Preparation's event vocabulary and manifest-to-diagnostic projection."""
from ..event_log import Location


JOURNAL = "preparation.jsonl"
# Historical text journals are evidence, not a second active logging format.
RETAINED_HISTORY = (JOURNAL, "preparation.log")


def record_locations(record, artifacts):
    if record.get("locations"):
        return tuple(Location(item["artifact"], start=item["start"], end=item["end"],
                              precision=item.get("precision"), sha256=artifacts.get(item["artifact"]))
                     for item in record["locations"])
    if record.get("source"):
        return (Location(record["source"], basis="source", start=record.get("start"),
                         end=record.get("end"), occurrence=record.get("occurrence"), line=record.get("line")),)
    return ()


def log_manifest(logger, manifest):
    """Record diagnostics with ids and declared coordinate bases, not full copies."""
    artifacts = {a["path"]: a["sha256"] for a in manifest.prepared_artifacts}
    for finding in manifest.lint.get("findings", []):
        logger.emit("lint.finding", finding["detail"],
            level="info" if finding["repair"]["status"] == "applied" else finding["severity"],
            data={key: finding[key] for key in ("id", "unit_id", "code", "reason", "repair", "remediation", "evidence")},
            locations=record_locations(finding, artifacts))
    for image in manifest.active_images + manifest.candidate_images:
        if image.dimension_error:
            logger.emit("asset.dimensions_unavailable", image.dimension_error, level="warning",
                        locations=(Location(image.rel_path, basis="source"),))
    for warning in manifest.bibliography.preparation_warnings:
        logger.emit("bibliography.warning", warning, level="warning")
    for code, level, records in (
        ("preparation.unresolved", "warning", manifest.unresolved),
        ("preparation.warning", "warning", manifest.warnings),
        ("requirement.deferred", "info", manifest.requirements),
    ):
        for record in records:
            logger.emit(code, record["detail"], level=level,
                data={key: record[key] for key in ("id", "unit_id", "reason", "stage", "activity",
                    "dependency", "materialization", "next_step", "location_status", "cause_ids", "effect_summary") if key in record},
                locations=record_locations(record, artifacts))
    for cause in manifest.uncertainty_causes:
        logger.emit("reading.uncertainty_cause", cause["detail"], level="info",
            data={k: cause[k] for k in ("id", "unit_id", "reason", "location_status")},
            locations=record_locations(cause, artifacts))
    for surveyed in manifest.source_survey:
        if surveyed["status"] != "observed":
            logger.emit("source.survey_unavailable", str(surveyed.get("error", surveyed["status"])),
                level="warning", data={"status": surveyed["status"]},
                locations=(Location(surveyed["source"], basis="source"),))
