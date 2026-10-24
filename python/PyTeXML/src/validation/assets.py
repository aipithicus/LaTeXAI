"""Disposable SVG derivatives for the optional XeTeX rendering adapter."""
from __future__ import annotations

import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET


SVG_DRIVER = r"""\begingroup
\catcode`\@=11\relax
\global\let\Gread@pytexmlsvg\Gread@eps
\global\let\Ginclude@pytexmlsvg\Ginclude@pdf
\expandafter\gdef\csname Gin@rule@.svg\endcsname#1{{pytexmlsvg}{.svg.bb}{#1.pdf}}
\expandafter\gdef\csname Gin@rule@.SVG\endcsname#1{{pytexmlsvg}{.SVG.bb}{#1.pdf}}
\endgroup
"""


def stage_svg(data: bytes, destination: Path) -> dict:
    """Create a PDF and bounding-box sidecar beside a zero-byte SVG marker.

    graphicx resolves the marker's name, reads the small bounding-box sidecar,
    and includes the PDF via SVG_DRIVER. TeX never reads the SVG's base64 lines.
    No source filename or includegraphics argument needs rewriting.
    """
    import pymupdf

    root = ET.fromstring(data)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Expected an SVG document")
    for element in root.iter():
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1] == "href" and not value.startswith(("#", "data:")):
                raise ValueError(f"SVG depends on an external resource: {value}")
    pdf_path = destination.with_name(destination.name + ".pdf")
    box_path = destination.with_name(destination.name + ".bb")
    if any(p.exists() for p in (destination, pdf_path, box_path)):
        raise ValueError(f"Rendering derivative collides with a source file: {destination.name}")
    pymupdf.TOOLS.mupdf_warnings()  # isolate this conversion's diagnostics
    with pymupdf.open(stream=data, filetype="svg") as svg:
        pdf_bytes = svg.convert_to_pdf()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if len(pdf) != 1 or pdf[0].rect.is_empty:
            raise ValueError("SVG conversion must yield one nonempty PDF page")
        width, height = pdf[0].rect.width, pdf[0].rect.height
    warnings = pymupdf.TOOLS.mupdf_warnings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(pdf_bytes)
    box_path.write_text(f"%%BoundingBox: 0 0 {width:.8f} {height:.8f}\n", encoding="ascii", newline="\n")
    destination.touch()
    return {"source_sha256": hashlib.sha256(data).hexdigest(), "method": "pymupdf_svg_to_pdf",
            "width_pt": width, "height_pt": height, "warnings": warnings,
            "derivative_bytes": len(pdf_bytes)}
