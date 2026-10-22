"""Plan prepared asset destinations and rewrite manuscript image references."""
from __future__ import annotations
from pathlib import Path
import re
from typing import Any, Dict, List
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

    for src_path in active_image_paths:
        if not src_path.exists():
            raise FileNotFoundError(f"Active image not found: {src_path}")

        try:
            rel = src_path.relative_to(project_dir).as_posix()
        except ValueError:
            rel = src_path.name

        # Create output destination preserving relative subdirectory
        rel_svg = str(Path(rel).with_suffix(".svg")).replace("\\", "/")
        dest_svg_path = (output_dir / rel_svg).resolve()

        success = convert_asset_to_svg(src_path, dest_svg_path)
        if not success:
            raise RuntimeError(f"SVG conversion failed for {src_path}; package preparation is incomplete")
        if success:
            path_mapping[rel] = rel_svg
            # Also map without extension for extension-less \includegraphics calls
            stem_rel = str(Path(rel).with_suffix("")).replace("\\", "/")
            path_mapping[stem_rel] = rel_svg

    return path_mapping


def rewrite_tex_image_references(tex_content: str, path_mapping: Dict[str, str]) -> str:
    """
    Rewrites \\includegraphics{...} targets in TeX source to use the converted SVG assets.
    """
    def _repl(m: re.Match) -> str:
        cmd = m.group(1)
        opt = m.group(2) or ""
        raw_path = m.group(3).strip().replace("\\", "/")
        norm_path = raw_path[2:] if raw_path.startswith("./") else raw_path

        # Check exact path or normalized path in mapping
        new_path = path_mapping.get(raw_path) or path_mapping.get(norm_path)
        if not new_path:
            # Check stem path
            stem = str(Path(norm_path).with_suffix("")).replace("\\", "/")
            new_path = path_mapping.get(stem)
        if not new_path:
            # Check basename
            bname = Path(norm_path).name
            new_path = path_mapping.get(bname) or path_mapping.get(Path(bname).stem)

        if new_path:
            return f"\\{cmd}{opt}{{{new_path}}}"
        return m.group(0)

    pat = re.compile(r"\\(includegraphics|pgfimage|pgfdeclareimage)(\[[^\]]*\])?\{([^}]+)\}")
    return pat.sub(_repl, tex_content)


def rewrite_lines_image_references(
    lines: List[Any],
    path_mapping: Dict[str, str]
) -> List[Any]:
    """
    Rewrites \\includegraphics targets across a list of SourceLine objects,
    recording line.op="REWRITE_IMAGE" for modified lines.
    """
    for l in lines:
        new_text = rewrite_tex_image_references(l.text, path_mapping)
        if new_text != l.text:
            l.text = new_text
            l.op = "REWRITE_IMAGE"
    return lines
