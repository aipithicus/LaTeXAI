"""Image metadata and individual asset-to-SVG conversion."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

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


IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".tif", ".tiff", ".bmp", ".webp"
}


VECTOR_EXTENSIONS = {".pdf", ".eps", ".svg"}


@dataclass
class ImageAssetInfo:
    rel_path: str
    abs_path: str
    ext: str
    is_vector: bool
    size_bytes: int
    width: Optional[float] = None
    height: Optional[float] = None
    unit: str = "px"  # "px" for raster, "pt" for vector
    dpi: Optional[Tuple[float, float]] = None
    color_mode: Optional[str] = None
    converted_from_eps: bool = False
    dimension_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def _probe_raster_image(path: str) -> Dict[str, Any]:
    """Inspects raster image dimensions and color mode via PIL if available."""
    info: Dict[str, Any] = {"width": None, "height": None, "dpi": None, "color_mode": None, "unit": "px"}
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as img:
            info["width"], info["height"] = img.size
            info["color_mode"] = img.mode
            dpi = img.info.get("dpi")
            if dpi and isinstance(dpi, tuple):
                info["dpi"] = (float(dpi[0]), float(dpi[1]))
    except Exception:
        pass
    return info


def _probe_pdf_dimensions(path: str) -> Dict[str, Any]:
    """Inspects PDF MediaBox dimensions in points without heavy PDF dependencies."""
    info: Dict[str, Any] = {"width": None, "height": None, "unit": "pt"}
    try:
        with open(path, "rb") as f:
            header = f.read(8192)
            match = re.search(
                rb"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]",
                header
            )
            if match:
                x1, y1, x2, y2 = map(float, match.groups())
                info["width"] = abs(x2 - x1)
                info["height"] = abs(y2 - y1)
    except Exception:
        pass
    return info


def _probe_eps_dimensions(path: str) -> Dict[str, Any]:
    """Inspects EPS BoundingBox in points."""
    info: Dict[str, Any] = {"width": None, "height": None, "unit": "pt"}
    try:
        with open(path, "r", encoding="latin1") as f:
            for line in f:
                if line.startswith("%%BoundingBox:"):
                    parts = line.split()[1:]
                    if len(parts) >= 4:
                        x1, y1, x2, y2 = map(float, parts[:4])
                        info["width"] = abs(x2 - x1)
                        info["height"] = abs(y2 - y1)
                    break
                if not line.startswith("%") and line.strip():
                    break
    except Exception:
        pass
    return info


def characterize_image(rel_path: str, abs_path: str) -> ImageAssetInfo:
    ext = os.path.splitext(rel_path)[1].lower()
    is_vector = ext in VECTOR_EXTENSIONS
    size_bytes = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0

    width = None
    height = None
    unit = "pt" if is_vector else "px"
    dpi = None
    color_mode = None

    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
        r_info = _probe_raster_image(abs_path)
        width, height = r_info["width"], r_info["height"]
        unit = r_info["unit"]
        dpi = r_info["dpi"]
        color_mode = r_info["color_mode"]
    elif ext == ".pdf":
        v_info = _probe_pdf_dimensions(abs_path)
        width, height = v_info["width"], v_info["height"]
    elif ext == ".eps":
        v_info = _probe_eps_dimensions(abs_path)
        width, height = v_info["width"], v_info["height"]

    is_converted_eps = "-eps-converted-to.pdf" in rel_path

    return ImageAssetInfo(
        rel_path=rel_path.replace("\\", "/"),
        abs_path=abs_path.replace("\\", "/"),
        ext=ext,
        is_vector=is_vector,
        size_bytes=size_bytes,
        width=width,
        height=height,
        unit=unit,
        dpi=dpi,
        color_mode=color_mode,
        converted_from_eps=is_converted_eps,
        dimension_error=(None if width is not None and height is not None else
                         f"Dimensions unavailable for {rel_path}"),
    )


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
        with fitz.open(str(pdf_path)) as doc:
            if not 0 <= page_index < len(doc):
                raise ValueError(f"Requested page {page_index + 1}; PDF has {len(doc)} pages")
            svg_text = doc[page_index].get_svg_image()

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


def convert_asset_to_svg(src_path: Path, dst_svg_path: Path, *, page_index: int = 0) -> bool:
    """Converts any supported asset (PDF, PNG, JPG, EPS) to SVG."""
    ext = src_path.suffix.lower()
    if page_index != 0 and ext != ".pdf":
        raise ValueError("Page selection is supported only for PDF assets")

    if ext == ".svg":
        # Already SVG, copy directly
        dst_svg_path.parent.mkdir(parents=True, exist_ok=True)
        with open(src_path, "rb") as src, open(dst_svg_path, "wb") as dst:
            dst.write(src.read())
        return True

    if ext == ".pdf":
        return pdf_to_svg(src_path, dst_svg_path, page_index)

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
