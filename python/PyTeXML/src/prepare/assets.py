"""Plan prepared asset destinations and rewrite manuscript image references."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List
from collections import Counter
from ..assets import convert_asset_to_svg


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
