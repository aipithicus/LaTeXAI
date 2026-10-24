"""Plan prepared asset destinations and rewrite manuscript image references."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List
from collections import Counter
from ..assets import convert_asset_to_svg
from ..reading.contracts import ReadingIssue


def observe_environment_assets(session, region):
    """Package literal asset observations without executing an unbound body.

    The dispatcher has already protected literals, definitions and arguments.
    Only its captured command headers are eligible; no raw-text search or second
    tokenizer is involved. The environment and its reading assumptions survive.
    """
    references = []
    search_changed = False
    for observation in region.observations:
        command = observation.command
        if command.action in {"asset_search_paths", "asset_extensions"}:
            search_changed = True
        if command.action != "asset_reference":
            continue
        record = {"source": command.span.basis.source_id, "occurrence": command.span.basis.occurrence_id,
                  "start": command.span.start, "end": command.span.end, "kind": "asset",
                  "context_span": [region.span.start, region.span.end],
                  "context": region.reason, "basis": "entry_reading_and_search_state",
                  "binding": observation.binding_id, "status": "unresolved"}
        record["unit_id"] = command.unit_id
        session.manifest.candidate_dependencies.append(record)
        try:
            if not session.frames[-1].emit:
                raise ReadingIssue("package_asset", "Observed asset in retained code needs a payload rewrite contract")
            if search_changed:
                raise ReadingIssue("asset_search_context", "An unexecuted search-path/extension declaration precedes this image")
            path = session.image_path(command, provisional=True)
        except ReadingIssue as error:
            record["reason"] = error.reason
            session.require(command.span, error.reason, error.detail, stage="preparation", unit_id=command.unit_id)
            continue
        target = session.name(path)
        record.update(target=target, status="resolved")
        session.candidate_images.add(path)
        references.append((command, target))
        session.require(command.span, "observed_asset",
            "Literal image resolved for the payload under entry reading/search state; "
            "its enclosing environment remains uninterpreted", stage="preparation", unit_id=command.unit_id)
    return tuple(references)


def rewrite_image_references(pieces, mapping):
    """Apply captured filename edits; preserve all surrounding source exactly.

    Multiple observations can share one deferred envelope. Edits are applied from
    right to left in that envelope's original coordinate system. Its provenance
    remains a transformation of the whole span, not a false affine mapping.
    """
    result = []
    for piece in pieces:
        if piece.image_references:
            boundary = piece.span.end
            for command, target in sorted(piece.image_references, key=lambda ref: ref[0].span.start, reverse=True):
                arg = command.argument("target")
                if arg.span.basis is not piece.span.basis or not piece.span.start <= arg.span.start <= arg.span.end <= boundary:
                    raise ValueError("Image filename edits must be disjoint and contained in their source piece")
                piece = piece.edit_source(arg.span, mapping[target], "REWRITE_IMAGE")
                boundary = arg.span.start
        result.append(piece)
    return result


def batch_convert_assets_to_svg(
    active_image_paths: List[Path],
    output_dir: Path,
    project_dir: Path
) -> Dict[str, str]:
    """
    Converts all active images to .svg and writes them into output_dir.
    Returns a mapping of {original_relative_path: new_svg_relative_path}.
    """
    path_mapping: Dict[str, str] = {}

    active_image_paths = list(dict.fromkeys(active_image_paths))
    stems = Counter(p.relative_to(project_dir).with_suffix(".svg").as_posix().casefold() for p in active_image_paths)
    destinations = {}
    occupied = set()
    for p in active_image_paths:
        rel = p.relative_to(project_dir)
        target = rel.with_suffix(".svg").as_posix()
        if stems[target.casefold()] > 1:
            target = rel.as_posix() + ".svg"
        if target.casefold() in occupied:
            raise ValueError(f"Asset output collision: {target}")
        destinations[p] = target
        occupied.add(target.casefold())

    for src_path in active_image_paths:
        if not src_path.exists():
            raise FileNotFoundError(f"Active image not found: {src_path}")

        try:
            rel = src_path.relative_to(project_dir).as_posix()
        except ValueError:
            rel = src_path.name

        # Create output destination preserving relative subdirectory
        rel_svg = destinations[src_path]
        dest_svg_path = (output_dir / rel_svg).resolve()

        success = convert_asset_to_svg(src_path, dest_svg_path)
        if not success:
            raise RuntimeError(f"SVG conversion failed for {src_path}; package preparation is incomplete")
        if success:
            path_mapping[rel] = rel_svg

    return path_mapping
