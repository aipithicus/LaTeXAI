r"""
Asset Conversion Engine for LaTeX Extractor.

Converts heterogeneous document image assets to standardized SVG containers:
  - Vector PDF -> Native vector SVG (via PyMuPDF).
  - Raster (PNG, JPG, TIFF, WEBP) -> Self-contained embedded SVG wrapper.
  - Rewrites TeX \includegraphics references to target the generated SVGs.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None



MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def pdf_to_svg(pdf_path: Path, svg_path: Path, page_index: int = 0) -> bool:
    """Extracts a PDF page as a pure vector SVG using PyMuPDF."""
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) is required for vector PDF to SVG conversion. Run 'pip install pymupdf'.")

    try:
        doc = fitz.open(str(pdf_path))
        if page_index >= len(doc):
            page_index = 0
        page = doc[page_index]
        svg_text = page.get_svg_image()
        doc.close()

        svg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_text)
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to convert PDF {pdf_path} to SVG: {e}") from e


def raster_to_svg_wrapper(img_path: Path, svg_path: Path) -> bool:
    """
    Encapsulates a raster image (PNG, JPG, TIFF) into a clean, standalone SVG container.
    Preserves 100% pixel fidelity via base64 data URI while exposing standard SVG viewBox.
    """
    ext = img_path.suffix.lower()
    mime = MIME_MAP.get(ext, "image/png")

    try:
        if Image is None:
            raise RuntimeError("Pillow is required to determine raster image dimensions")
        with Image.open(str(img_path)) as img:
            width, height = img.size
        if width <= 0 or height <= 0:
            raise ValueError(f"Unavailable image dimensions: {width} x {height}")

        with open(img_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("ascii")

        svg_content = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            f'  <image width="{width}" height="{height}" href="data:{mime};base64,{b64_data}"/>\n'
            f'</svg>\n'
        )

        svg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_content)
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to wrap raster {img_path} in SVG: {e}") from e


def convert_asset_to_svg(src_path: Path, dst_svg_path: Path) -> bool:
    """Converts any supported asset (PDF, PNG, JPG, EPS) to SVG."""
    ext = src_path.suffix.lower()

    if ext == ".svg":
        # Already SVG, copy directly
        dst_svg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(src_path, "rb") as src, open(dst_svg_path, "wb") as dst:
            dst.write(src.read())
        return True

    if ext == ".pdf":
        return pdf_to_svg(src_path, dst_svg_path)

    if ext in MIME_MAP:
        return raster_to_svg_wrapper(src_path, dst_svg_path)

    if ext == ".eps":
        # PyMuPDF can open PS/EPS files directly if MuPDF ps support is active
        if fitz:
            try:
                return pdf_to_svg(src_path, dst_svg_path)
            except Exception:
                pass
        # EPS bytes cannot be embedded as image/png. Report an unsupported
        # conversion until a real EPS conversion backend is provided.

    return False


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
