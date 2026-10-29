"""Prepare master.tex from one cached, reading-aware source traversal."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
from uuid import uuid4
from ..event_log import EventLogger, JsonlSink
from .session import PreparationSession
from .manifest import PreflightManifest
from .provenance import ProvenanceLedger
from .bibliography import prepare_bibliography
from .assets import batch_convert_assets_to_svg, rewrite_image_references
from .locations import finalize_locations
from .publication import OutputTransaction
from .events import JOURNAL, RETAINED_HISTORY, log_manifest


@dataclass(frozen=True, slots=True)
class _PreparationRequest:
    """Validated public settings used by the builder; publication paths stay outside."""
    project: Path
    root_tex: str | None
    engine: str
    convert_images_to_svg: bool
    copy_local_dependencies: bool
    emit_manifest_json: bool
    emit_provenance: bool | None
    policy: str | Path
    engine_profile: str


def preprocess_paper(
    project_dir: str,
    output_dir: Optional[str] = None,
    output_file: Optional[str] = None,
    root_tex: Optional[str] = None,
    execute_probe: bool = False,
    engine: str = "pytexml",
    drop_commands: Optional[List[str]] = None,
    keep_content_commands: Optional[List[str]] = None,
    drop_environments: Optional[List[str]] = None,
    convert_images_to_svg: bool = True,
    copy_local_dependencies: bool = True,
    clean_styles: bool = False,
    emit_manifest_json: bool = True,
    emit_provenance: Optional[bool] = None,
    policy: str = "prepare",
    logger: EventLogger | None = None,
    engine_profile: str = "etex",
) -> Tuple[str, PreflightManifest, Path, Optional[ProvenanceLedger]]:
    """Build in isolation and publish a complete payload, with failure rollback.

    emit_provenance=None follows policy.provenance.emit_ledger; an explicit bool
    overrides it. Manifest locations are always finalized, independently of it.
    """
    project = Path(project_dir).resolve()
    destination = Path(output_dir).resolve() if output_dir else project / "extracted"
    if not project.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")
    if project.is_relative_to(destination):
        raise ValueError("Output directory must not contain or equal the source project")
    secondary = Path(output_file).resolve() if output_file else None
    if secondary is not None:
        if secondary.is_relative_to(project) and not secondary.is_relative_to(destination):
            raise ValueError("An additional output inside the project must stay in the output directory")
    previous_payload = (destination / "master.tex").is_file()
    with OutputTransaction(destination, retained=RETAINED_HISTORY) as transaction:
        sink = JsonlSink(destination / JOURNAL) if logger is None else None
        attempt = uuid4().hex
        log = (logger or EventLogger(sink, run_id=attempt)).bind(
            stage="preparation", attempt_id=attempt, output_dir=str(destination))
        published = False
        manifest = None
        try:
            log.emit("attempt.started", "Preparation started", flush=True)
            # Preserve attempt history for rejected legacy requests, without
            # forwarding unsupported knobs into the preparation machinery.
            if execute_probe:
                raise ValueError("External execution probes are not part of preparation")
            if drop_commands or keep_content_commands or drop_environments or clean_styles:
                raise ValueError("Custom cleanup requires reading-aware policy contracts; regex cleanup is retired")
            request = _PreparationRequest(
                project=project, root_tex=root_tex, engine=engine,
                convert_images_to_svg=convert_images_to_svg, copy_local_dependencies=copy_local_dependencies,
                emit_manifest_json=emit_manifest_json, emit_provenance=emit_provenance, policy=policy,
                engine_profile=engine_profile)
            text, manifest, ledger = _prepare_paper(
                request, transaction.stage, excluded_dirs=(destination, transaction.workspace), logger=log)
            log.emit("payload.prepared", "Payload built in staging",
                     data={"preparation_status": manifest.preparation_status}, flush=True)
            if secondary is not None:
                transaction.secondary(secondary, text)
            log.emit("publication.started", "Publishing prepared payload", flush=True)
            transaction.publish()
            published = True
            log.emit("attempt.published", "Prepared payload published", flush=True,
                data={"preparation_status": manifest.preparation_status,
                      "materialization_status": manifest.materialization_status,
                      "artifacts": manifest.prepared_artifacts})
        except BaseException as error:
            if not published:
                try:
                    if manifest is not None and emit_manifest_json and not transaction.recovery_needed:
                        manifest.mark_failed()
                        (transaction.stage / "manifest.json").write_text(
                            manifest.to_json(), encoding="utf-8", newline="\n")
                    transaction.failure()
                except Exception as diagnostic_error:
                    error.add_note(f"Could not retain failure manifest: {diagnostic_error}")
            else:
                error.add_note("The prepared payload was already published; this failure does not undo publication.")
            if sink is not None:
                sink.path = transaction.retained_paths[JOURNAL]
            try:
                log.emit("attempt.failed", "Preparation attempt failed", level="error", error=error, flush=True,
                    data={"payload_published": published,
                          "previous_payload_preserved": previous_payload and not published and not transaction.recovery_needed,
                          "recovery_needed": transaction.recovery_needed,
                          "recovery_directories": [str(p) for p in transaction.temporary] if transaction.recovery_needed else []})
            except Exception as logging_error:
                if logging_error is not error:
                    error.add_note(f"Could not append failure event: {logging_error}")
            raise
    return text, manifest, destination, ledger


def _prepare_paper(request: _PreparationRequest, out_dir: Path, *,
                   excluded_dirs: tuple[Path, ...], logger: EventLogger):
    """Build in an owned staging directory; the caller alone publishes outputs.

    Dependency discovery, input insertion and protected spans share one traversal.
    Unresolved reading limits edits, not publication. Settings and destination
    confinement are checked at the public boundary; source-dependent checks stay here.
    """
    p_dir = request.project
    session = None
    try:
        logger.emit("phase.started", data={"phase": "reading"})
        session = PreparationSession(p_dir, root_tex=request.root_tex, engine=request.engine,
                                     excluded_dirs=(out_dir, *excluded_dirs), policy=request.policy,
                                     engine_profile=request.engine_profile)
        emit_provenance = (session.policy.provenance.emit_ledger if request.emit_provenance is None
                           else request.emit_provenance)
        session.run()
        manifest = session.manifest
        logger.emit("phase.completed", data={"phase": "reading", "source_reads": len(session.store.read_paths)})
        logger.emit("phase.started", data={"phase": "bibliography"}, flush=True)
        pieces = prepare_bibliography(session.pieces, session, out_dir)
        logger.emit("phase.completed", data={"phase": "bibliography"})
        logger.emit("phase.started", data={"phase": "assets"}, flush=True)
        images = manifest.active_images + manifest.candidate_images
        if images and not request.convert_images_to_svg:
            raise ValueError("Referenced images require SVG conversion for a standalone extraction package")
        if images:
            uses = session.surviving_assets(pieces)
            mapping = batch_convert_assets_to_svg(uses, out_dir, p_dir)
            session.rebase_asset_payloads(uses, mapping)
            pieces = rewrite_image_references(pieces, mapping, uses)
            manifest.record_asset_payloads(mapping)
        logger.emit("phase.completed", data={"phase": "assets"})
        logger.emit("phase.started", data={"phase": "emission"}, flush=True)
        if session.bibliography_pieces is not None:
            keys = {p.key for p in session.bibliography_pieces}
            prepared_bbl = ''.join(p.text for p in pieces if p.key in keys)
            (out_dir / "bibliography.bbl").write_text(prepared_bbl, encoding="utf-8", newline="\n")
        dependencies = [Path(s.abs_path) for s in manifest.local_styles] + [p_dir / p for p in manifest.code_inputs]
        if (dependencies or session.literal_payloads or session.retained_resources) and not request.copy_local_dependencies:
            raise ValueError("Local code dependencies must be emitted for a standalone extraction package")
        # Local code remains source-preserving until its own emission contract
        # exists. The cache also supplies payload bytes; no reopen/copy pass.
        payloads = {}
        for source in dependencies:
            target = out_dir / source.relative_to(p_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = session.payload_text(source)
            payloads[source.relative_to(p_dir).as_posix()] = (source, payload)
            target.write_text(payload, encoding="utf-8", newline="\n")
        for source, relative in session.literal_payloads.items():
            target = out_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = session.store.document(source).text
            payloads[relative] = (source, payload)
            target.write_text(payload, encoding="utf-8", newline="")
        for relative, source in session.retained_resources.items():
            target = out_dir / relative
            payload = session.store.document(source).text
            if target.exists() and target.read_bytes() != payload.encode("utf-8"):
                raise ValueError(f"Retained resource conflicts with prepared artifact {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8", newline="")
            payloads[relative] = (source, payload)
        master_tex_content = "".join(p.text for p in pieces)
        locations = finalize_locations(session, pieces, master_tex_content, payloads)
        session.lint.finalize_repairs(pieces, master_tex_content)
        ledger = ProvenanceLedger.build_from_pieces(pieces, locations.tombstones,
            source_coverage=locations.source_coverage, artifact=locations.artifacts['master.tex'],
            rle_compression=session.policy.provenance.rle_compression) if emit_provenance else None
        if ledger:
            ledger.save(out_dir / "master.provenance.json")
        manifest.entrypoint = "master.tex"
        manifest.refresh_status()
        if manifest.source_dependency_closure != "complete":
            manifest.unclassified_files = sorted(set(manifest.unclassified_files +
                manifest.dormant_tex_files + manifest.dormant_styles + manifest.dormant_images))
            manifest.dormant_tex_files = []
            manifest.dormant_styles = []
            manifest.dormant_images = []
        manifest.source_reads = list(session.store.read_paths)
        if request.emit_manifest_json:
            (out_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8", newline="\n")
        (out_dir / "master.tex").write_text(master_tex_content, encoding="utf-8", newline="\n")
        logger.emit("phase.completed", data={"phase": "emission"})
        log_manifest(logger, manifest)
        return master_tex_content, manifest, ledger
    except BaseException as exc:
        if session is not None:
            session.manifest.source_reads = list(session.store.read_paths)
            session.pending_units()
            session.manifest.mark_failed()
            try:
                if request.emit_manifest_json:
                    (out_dir / "manifest.json").write_text(session.manifest.to_json(), encoding="utf-8", newline="\n")
            except Exception as diagnostic_error:
                if diagnostic_error is not exc:
                    exc.add_note(f"Could not write failure manifest: {diagnostic_error}")
            try:
                log_manifest(logger, session.manifest)
            except Exception as diagnostic_error:
                if diagnostic_error is not exc:
                    exc.add_note(f"Could not log preparation diagnostics: {diagnostic_error}")
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare a standalone LaTeX extraction package")
    parser.add_argument("project_dir")
    parser.add_argument("output_dir", nargs="?")
    parser.add_argument("root_tex", nargs="?")
    parser.add_argument("--engine-profile", choices=("etex", "pdftex"), default="etex")
    args = parser.parse_args()
    text, manifest, output, ledger = preprocess_paper(args.project_dir, output_dir=args.output_dir,
                                                    root_tex=args.root_tex, engine_profile=args.engine_profile)
    print(f"Prepared {manifest.root_file} -> {output / 'master.tex'} "
          f"({len(text):,} characters; {manifest.preparation_status})")
