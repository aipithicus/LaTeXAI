"""Prepare master.tex from one cached, reading-aware source traversal."""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Tuple
from .session import PreparationSession
from .manifest import PreflightManifest
from .provenance import ProvenanceLedger
from .bibliography import prepare_bibliography
from .assets import batch_convert_assets_to_svg


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
    emit_provenance: bool = True,
) -> Tuple[str, PreflightManifest, Path, Optional[ProvenanceLedger]]:
    """Publish prepared source, with explicit partial status when knowledge is missing.

    Dependency discovery, input insertion and protected spans share one traversal.
    Unresolved reading limits edits, not publication. Legacy regex cleanup options require
    future declarative contracts and are rejected when explicitly requested.
    """
    p_dir = Path(project_dir).resolve()
    if not p_dir.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")
    out_dir = Path(output_dir).resolve() if output_dir else p_dir / "extracted"
    if p_dir.is_relative_to(out_dir):
        raise ValueError("Output directory must not contain or equal the source project")
    if execute_probe:
        raise ValueError("External execution probes are not part of preparation")
    if drop_commands or keep_content_commands or drop_environments or clean_styles:
        raise ValueError("Custom cleanup requires reading-aware policy contracts; regex cleanup is retired")
    if output_file:
        secondary = Path(output_file).resolve()
        if secondary.is_relative_to(p_dir) and not secondary.is_relative_to(out_dir):
            raise ValueError("An additional output inside the project must stay in the output directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "preparation.log"
    session = None
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write("STARTED\n")
        log.flush()
        try:
            # Invalidate the previous entrypoint before a rerun can fail.
            (out_dir / "master.tex").unlink(missing_ok=True)
            session = PreparationSession(p_dir, root_tex=root_tex, engine=engine, excluded_dirs=[out_dir])
            if output_file:
                secondary = Path(output_file).resolve()
                if session.store.contains(secondary):
                    raise ValueError("output_file must not overwrite an original source")
            session.run()
            manifest = session.manifest
            pieces = prepare_bibliography(session.pieces, session, out_dir)
            if manifest.active_images and not convert_images_to_svg:
                raise ValueError("Active images require SVG conversion for a standalone extraction package")
            if manifest.active_images:
                mapping = batch_convert_assets_to_svg([Path(i.abs_path) for i in manifest.active_images], out_dir, p_dir)
                rewritten = []
                for piece in pieces:
                    if piece.target is not None:
                        arg = piece.command.argument("target")
                        a, b = arg.span.start - piece.span.start, arg.span.end - piece.span.start
                        piece = piece.rewritten(piece.text[:a] + mapping[piece.target] + piece.text[b:], "REWRITE_IMAGE")
                    rewritten.append(piece)
                pieces = rewritten
            if session.bibliography_pieces is not None:
                spans = {p.span for p in session.bibliography_pieces}
                prepared_bbl = ''.join(p.text for p in pieces if p.span in spans)
                (out_dir / "bibliography.bbl").write_text(prepared_bbl, encoding="utf-8", newline="\n")
            dependencies = [Path(s.abs_path) for s in manifest.local_styles] + [p_dir / p for p in manifest.code_inputs]
            if dependencies and not copy_local_dependencies:
                raise ValueError("Local code dependencies must be emitted for a standalone extraction package")
            # Local code remains source-preserving until its own emission contract
            # exists. The cache also supplies payload bytes; no reopen/copy pass.
            for source in dependencies:
                target = out_dir / source.relative_to(p_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(session.payload_text(source), encoding="utf-8", newline="\n")
            master_tex_content = "".join(p.text for p in pieces)
            ledger = ProvenanceLedger.build_from_pieces(pieces, session.tombstones) if emit_provenance else None
            if ledger:
                ledger.save(out_dir / "master.provenance.json")
            manifest.entrypoint = "master.tex"
            pending_preparation = bool(manifest.unresolved) or any(r["stage"] == "preparation" for r in manifest.requirements)
            manifest.preparation_status = "partial" if pending_preparation else "complete"
            if pending_preparation:
                manifest.source_dependency_closure = "unresolved"
            if manifest.unresolved or manifest.requirements:
                manifest.dependency_closure = "unresolved"
                manifest.unclassified_files = sorted(set(manifest.unclassified_files +
                    manifest.dormant_tex_files + manifest.dormant_styles + manifest.dormant_images))
                manifest.dormant_tex_files = []
                manifest.dormant_styles = []
                manifest.dormant_images = []
            manifest.source_reads = list(session.store.read_paths)
            if emit_manifest_json:
                (out_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8", newline="\n")
            (out_dir / "master.tex").write_text(master_tex_content, encoding="utf-8", newline="\n")
            if output_file:
                secondary.parent.mkdir(parents=True, exist_ok=True)
                secondary.write_text(master_tex_content, encoding="utf-8", newline="\n")
            for warning in [i.dimension_error for i in manifest.active_images if i.dimension_error] + manifest.bibliography.preparation_warnings:
                log.write(f"WARNING: {warning}\n")
            for diagnostic in manifest.unresolved:
                log.write(f"UNRESOLVED: {diagnostic['source']}:{diagnostic['line']} "
                          f"[{diagnostic['reason']}] {diagnostic['detail']}\n")
            for requirement in manifest.requirements:
                log.write(f"DEFERRED ({requirement['stage']}): {requirement['source']}:{requirement['line']} "
                          f"[{requirement['reason']}] {requirement['detail']}\n")
            for surveyed in manifest.source_survey:
                if surveyed["status"] != "observed":
                    log.write(f"SURVEY: {surveyed['source']}: {surveyed.get('error', surveyed['status'])}\n")
            log.write("PARTIAL\n" if pending_preparation else "SUCCESS\n")
            return master_tex_content, manifest, out_dir, ledger
        except Exception as exc:
            if session is not None and emit_manifest_json:
                session.manifest.entrypoint = None
                session.manifest.preparation_status = "failed"
                session.manifest.dependency_closure = "unresolved"
                session.manifest.source_reads = list(session.store.read_paths)
                (out_dir / "manifest.json").write_text(session.manifest.to_json(), encoding="utf-8", newline="\n")
            log.write(f"FAILED\n{type(exc).__name__}: {exc}\n")
            raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare a standalone LaTeX extraction package")
    parser.add_argument("project_dir")
    parser.add_argument("output_dir", nargs="?")
    parser.add_argument("root_tex", nargs="?")
    args = parser.parse_args()
    text, manifest, output, ledger = preprocess_paper(args.project_dir, output_dir=args.output_dir, root_tex=args.root_tex)
    print(f"Prepared {manifest.root_file} -> {output / 'master.tex'} "
          f"({len(text):,} characters; {manifest.preparation_status})")
