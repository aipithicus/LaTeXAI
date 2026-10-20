r"""
Pre-flight project dependency inventory & asset characterization for LaTeX extractor.

Key Capabilities:
  - Dynamic Root Detection: Never assumes 'main.tex'; finds root .tex by analyzing
    \documentclass, inclusion graphs, magic comments, and matching .bbl basenames.
  - Image Asset Characterization: Probes active vs. dormant images, formats, dimensions
    (px for raster, pt for vector), DPI, color modes, and byte sizes.
  - Bibliography Diagnostics: Detects classic BibTeX/natbib vs biblatex vs embedded,
    identifies required backend (bibtex/biber), and checks .bbl availability.
  - Source Topology: Maps active sub-tex files vs unreferenced/dormant drafts.
  - Local Package Scoping: Isolates project-local styles (.sty, .cls) from system TeX Live.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from .source_io import SourceDecodingError, open_source, project_files, excluded_path
except ImportError:
    from source_io import SourceDecodingError, open_source, project_files, excluded_path

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".tif", ".tiff", ".bmp", ".webp"
}
VECTOR_EXTENSIONS = {".pdf", ".eps", ".svg"}
CODE_EXTENSIONS = {
    ".py", ".c", ".cpp", ".h", ".java", ".rs", ".go", ".js", ".ts",
    ".json", ".csv", ".tsv", ".txt", ".sh", ".yaml", ".yml", ".xml"
}

# -----------------------------------------------------------------------------
# Asset & Manifest Data Models
# -----------------------------------------------------------------------------

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


@dataclass
class BibliographyInfo:
    kind: str  # "CLASSIC_BIBTEX", "BIBLATEX", "EMBEDDED", "NONE"
    backend: Optional[str]  # "bibtex", "biber", or None
    bbl_path: Optional[str]
    bbl_exists: bool
    bbl_needed: bool
    bib_files: List[str] = field(default_factory=list)
    missing_bib_files: List[str] = field(default_factory=list)
    citations_count: int = 0
    prepared_bbl: Optional[str] = None
    canonical_bib: Optional[str] = None
    preparation_backend: Optional[str] = None
    preparation_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class StyleFileInfo:
    rel_path: str
    abs_path: str
    is_active: bool
    size_bytes: int
    declared_commands: List[str] = field(default_factory=list)
    declared_environments: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class PackageUsage:
    name: str
    options: List[str] = field(default_factory=list)
    is_local: bool = False
    local_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ImplicitGraphicInfo:
    kind: str  # "assetless_float", "morphism_grid", "tikzcd", "amscd", "xymatrix", "tikzpicture", "picture", etc.
    category: str  # "ASSETLESS_FLOAT", "COMMUTATIVE_DIAGRAM", "PROGRAMMATIC_DRAWING", "SPECIALIZED_CANVAS"
    file: str  # relative path of .tex file
    line_number: int  # 1-indexed
    is_floating: bool
    is_math_mode: bool
    preview: str
    environment_name: Optional[str] = None
    package_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class PreflightManifest:
    root_file: str
    base_name: str
    project_dir: str
    engine: str

    # Bibliography
    bibliography: BibliographyInfo

    # Canonical package entrypoint; root_file above records source discovery.
    entrypoint: Optional[str] = None

    # Assets
    active_images: List[ImageAssetInfo] = field(default_factory=list)
    dormant_images: List[str] = field(default_factory=list)

    # TeX and Code Source Topology
    active_tex_files: List[str] = field(default_factory=list)
    dormant_tex_files: List[str] = field(default_factory=list)

    # Package & Style Architecture
    packages_declared: List[PackageUsage] = field(default_factory=list)
    local_styles: List[StyleFileInfo] = field(default_factory=list)
    dormant_styles: List[str] = field(default_factory=list)
    code_inputs: List[str] = field(default_factory=list)

    # Implicit / Programmatic Graphics
    implicit_graphics: List[ImplicitGraphicInfo] = field(default_factory=list)
    implicit_graphics_count: int = 0
    has_implicit_graphics: bool = False
    has_commutative_diagrams: bool = False

    # Environment flags
    has_tikz: bool = False
    has_tikz_external: bool = False
    has_minted: bool = False
    has_listings: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# -----------------------------------------------------------------------------
# Dynamic Root Document Discovery
# -----------------------------------------------------------------------------

def find_root_tex(project_dir: str, excluded_dirs: Optional[List[Path]] = None) -> str:
    """
    Discovers the true root .tex file in a repository without assuming 'main.tex'.
    
    Resolution Order:
      1. Magic comment `% !TEX root = <filename>` in any .tex file
      2. Content analysis: identifies files with `\\documentclass` and `\\begin{document}`
      3. Discards subfiles (`% auto-ignore`, subfiles package, or files included by others)
      4. Disambiguation via matching `.bbl` basename or common filenames
    """
    p_dir = Path(project_dir).resolve()
    excluded_dirs = excluded_dirs or []
    tex_files = [p for p in project_files(p_dir, excluded_dirs) if p.suffix.lower() == ".tex"]

    if not tex_files:
        raise FileNotFoundError(f"No .tex files found in {project_dir}")

    # 1. Check for Magic Comments (% !TEX root = ...)
    for tex in tex_files:
        try:
            with open_source(tex) as f:
                head = [next(f, "") for _ in range(15)]
            for line in head:
                m = re.search(r"%\s*!TEX\s+root\s*=\s*([^\s]+)", line, re.IGNORECASE)
                if m:
                    target = m.group(1).strip()
                    resolved = (tex.parent / target).resolve()
                    if (resolved.is_file() and resolved.is_relative_to(p_dir)
                            and not excluded_path(resolved, p_dir, excluded_dirs)):
                        return resolved.relative_to(p_dir).as_posix()
        except SourceDecodingError:
            raise
        except Exception:
            continue

    # 2. Filter candidates based on \documentclass and \begin{document}
    candidates: List[Path] = []
    includes_found: Set[str] = set()

    for tex in tex_files:
        try:
            with open_source(tex) as f:
                content = f.read()

            # Ignore files flagged by arXiv or template as auto-ignore
            if re.search(r"^\s*%\s*auto-ignore", content, re.MULTILINE | re.IGNORECASE):
                continue

            # Track files included by this file
            for inc in re.findall(r"\\(?:input|include|subfile)\s*\{([^}]+)\}", content):
                inc_name = inc.strip()
                if not inc_name.endswith(".tex"):
                    inc_name += ".tex"
                includes_found.add((p_dir / inc_name).resolve())

            # A root document must declare \documentclass and have \begin{document}
            has_docclass = bool(re.search(r"\\documentclass(\[[^\]]*\])?\{[^}]+\}", content))
            has_begindoc = bool(re.search(r"\\begin\{document\}", content))

            if has_docclass and has_begindoc:
                # Exclude subfiles package children if marked
                if not re.search(r"\\documentclass(\[[^\]]*\])?\{subfiles\}", content):
                    candidates.append(tex)
        except SourceDecodingError:
            raise
        except Exception:
            continue

    # 3. If candidates were included by another file, they are sub-documents
    unincluded_candidates = [c for c in candidates if c.resolve() not in includes_found]
    if unincluded_candidates:
        candidates = unincluded_candidates

    # If exactly 1 candidate, we're done
    if len(candidates) == 1:
        return candidates[0].relative_to(p_dir).as_posix()

    # 4. Disambiguation: Check for matching .bbl file
    for c in candidates:
        if c.with_suffix(".bbl").is_file():
            return c.relative_to(p_dir).as_posix()

    # 5. Check common conventional names
    for c in candidates:
        if c.stem.lower() in ("main", "paper", "ms", "article", "index"):
            return c.relative_to(p_dir).as_posix()

    # 6. Prefer candidate located in root directory over nested subdirectories
    root_level_candidates = [c for c in candidates if c.parent == p_dir]
    if len(root_level_candidates) == 1:
        return root_level_candidates[0].relative_to(p_dir).as_posix()

    if candidates:
        return candidates[0].relative_to(p_dir).as_posix()

    # Fallback to the first .tex file found in the root dir
    root_tex = [p for p in tex_files if p.parent == p_dir]
    if root_tex:
        return root_tex[0].relative_to(p_dir).as_posix()

    return tex_files[0].relative_to(p_dir).as_posix()


# -----------------------------------------------------------------------------
# Asset Introspection Helpers
# -----------------------------------------------------------------------------

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


def _extract_graphicspaths(content: str, p_dir: Path) -> List[Path]:
    """Extracts all search directories declared in \\graphicspath{{dir1/}{dir2/}}."""
    search_dirs = [p_dir]
    m = re.search(r"\\graphicspath\s*\{((?:\{[^}]+\}\s*)+)\}", content)
    if m:
        raw_dirs = re.findall(r"\{([^}]+)\}", m.group(1))
        for d in raw_dirs:
            cleaned = d.strip().strip("/\\")
            cand = (p_dir / cleaned).resolve()
            if cand.exists() and cand.is_dir():
                search_dirs.append(cand)
    return search_dirs


def _resolve_asset_file(raw_target: str, search_dirs: List[Path]) -> Optional[Path]:
    """Resolves an asset target across search directories and common extensions."""
    raw = raw_target.strip().replace("\\", "/")
    # Try literal path
    for s_dir in search_dirs:
        cand = (s_dir / raw).resolve()
        if cand.exists() and cand.is_file():
            return cand

    # Try common extensions
    for s_dir in search_dirs:
        for ext in (".png", ".pdf", ".jpg", ".jpeg", ".eps", ".svg", ".tif", ".tiff", ".py", ".c", ".csv", ".json", ".txt"):
            cand = (s_dir / f"{raw}{ext}").resolve()
            if cand.exists() and cand.is_file():
                return cand

    return None


def _static_scan_active_paths(p_dir: Path, root_name: str, excluded_dirs: Optional[List[Path]] = None) -> Set[Path]:
    """
    Robust multi-stage scanner for headless environments:
      Stage 1: Preamble directory extraction (\\graphicspath).
      Stage 2: Primary forward walk across extended command taxonomy.
      Stage 3: Secondary check via reverse correlation probe.
    """
    visited_tex: Set[Path] = set()
    excluded_dirs = excluded_dirs or []
    found_paths: Set[Path] = set()
    collected_text_fragments: List[str] = []
    graphic_search_dirs: List[Path] = [p_dir]

    EXTENDED_ASSET_PATTERNS = [
        # Standard graphics & PGF
        re.compile(r"\\(?:includegraphics|pgfimage|pgfdeclareimage)(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}"),
        # SVG / Inkscape
        re.compile(r"\\includesvg(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}"),
        # Legacy EPS
        re.compile(r"\\(?:epsfig|psfig)\s*\{[^}]*file=([^,}]+)[^}]*\}"),
        # Code and verbatim input listings
        re.compile(r"\\(?:lstinputlisting|verbatiminput|inputminted|tcbinputlisting)(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}"),
    ]

    def walk_tex(tex_file: Path):
        if (tex_file in visited_tex or not tex_file.exists()
                or excluded_path(tex_file, p_dir, excluded_dirs)):
            return
        visited_tex.add(tex_file)
        found_paths.add(tex_file)

        try:
            with open_source(tex_file) as f:
                content = f.read()
        except SourceDecodingError:
            raise
        except Exception:
            return

        collected_text_fragments.append(content)

        # Stage 1: Discover \graphicspath if declared
        for g_dir in _extract_graphicspaths(content, p_dir):
            if g_dir not in graphic_search_dirs:
                graphic_search_dirs.append(g_dir)

        # Walk \input, \include, \subfile
        for inc in re.findall(r"\\(?:input|include|subfile)\s*\{([^}]+)\}", content):
            inc_name = inc.strip()
            if not inc_name.endswith(".tex"):
                cand = (p_dir / f"{inc_name}.tex").resolve()
                if cand.exists():
                    walk_tex(cand)
                    continue
            cand = (p_dir / inc_name).resolve()
            if cand.exists():
                walk_tex(cand)

        # Stage 2: Forward asset pattern matching across extended taxonomy
        for pat in EXTENDED_ASSET_PATTERNS:
            for m in pat.finditer(content):
                target_raw = m.group(1).strip()
                resolved = _resolve_asset_file(target_raw, graphic_search_dirs)
                if resolved and not excluded_path(resolved, p_dir, excluded_dirs):
                    found_paths.add(resolved)

    root_p = (p_dir / root_name).resolve()
    walk_tex(root_p)

    # Scan for local .sty packages
    for content in collected_text_fragments:
        for pkg in re.findall(r"\\usepackage(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}", content):
            for p in pkg.split(","):
                p = p.strip()
                cand = (p_dir / f"{p}.sty").resolve()
                if cand.is_file() and not excluded_path(cand, p_dir, excluded_dirs):
                    found_paths.add(cand)

    # Stage 3: Secondary Check - Reverse Correlation Probe
    # Cross-references unclassified disk files with tokens in the source text
    full_source_text = "\n".join(collected_text_fragments)
    all_disk_files = list(project_files(p_dir, excluded_dirs))

    for f in all_disk_files:
        if f in found_paths:
            continue
        rel = f.relative_to(p_dir).as_posix()
        if rel.startswith((".git/", "artifacts/", "build/", "extracted/")):
            continue

        stem = f.stem
        # Skip trivial or ultra-short basenames to avoid false-positive token collisions
        if len(stem) < 3:
            continue

        # Look for stem in source inside braces or preceded by path separators:
        # e.g., {stem}, /stem, or "stem"
        escaped_stem = re.escape(stem)
        reverse_pat = re.compile(rf"([/{{,\"\s]){escaped_stem}([}}\",\s\.]|\.[a-zA-Z]{{3,4}})")
        if reverse_pat.search(full_source_text):
            found_paths.add(f.resolve())

    return found_paths


def probe_style_file(rel_path: str, abs_path: str, is_active: bool) -> StyleFileInfo:
    """Extracts custom macros and environments declared in a local .sty / .cls file."""
    size_bytes = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0
    commands: List[str] = []
    environments: List[str] = []

    try:
        with open_source(abs_path) as f:
            content = f.read()

        for m in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([a-zA-Z]+)\}?", content):
            cmd = f"\\{m.group(1)}"
            if cmd not in commands:
                commands.append(cmd)
        for m in re.finditer(r"\\def\s*\\([a-zA-Z]+)", content):
            cmd = f"\\{m.group(1)}"
            if cmd not in commands:
                commands.append(cmd)
        for m in re.finditer(r"\\DeclareMathOperator\*?\s*\{?\\([a-zA-Z]+)\}?", content):
            cmd = f"\\{m.group(1)}"
            if cmd not in commands:
                commands.append(cmd)
        for m in re.finditer(r"\\(?:new|renew)environment\*?\s*\{([^}]+)\}", content):
            env = m.group(1).strip()
            if env not in environments:
                environments.append(env)
    except SourceDecodingError:
        raise
    except Exception:
        pass

    return StyleFileInfo(
        rel_path=rel_path.replace("\\", "/"),
        abs_path=abs_path.replace("\\", "/"),
        is_active=is_active,
        size_bytes=size_bytes,
        declared_commands=commands,
        declared_environments=environments,
    )


def extract_package_declarations(p_dir: Path, active_tex_paths: List[Path]) -> List[PackageUsage]:
    """Scans all active .tex files for \\usepackage and \\RequirePackage declarations."""
    packages: List[PackageUsage] = []
    seen: Set[str] = set()

    for tex_path in active_tex_paths:
        try:
            with open_source(tex_path) as f:
                content = f.read()
        except SourceDecodingError:
            raise
        except Exception:
            continue

        pat = re.compile(r"\\(?:usepackage|RequirePackage)(?:\s*\[([^\]]*)\])?\s*\{([^}]+)\}")
        for m in pat.finditer(content):
            opts_raw = m.group(1) or ""
            options = [o.strip() for o in opts_raw.split(",") if o.strip()]
            names_raw = m.group(2) or ""
            for name in names_raw.split(","):
                name = name.strip()
                if not name or name in seen:
                    continue
                seen.add(name)

                local_sty = p_dir / f"{name}.sty"
                local_cls = p_dir / f"{name}.cls"
                is_local = local_sty.exists() or local_cls.exists()
                local_path = (local_sty if local_sty.exists() else local_cls).name if is_local else None

                packages.append(PackageUsage(
                    name=name,
                    options=options,
                    is_local=is_local,
                    local_path=local_path,
                ))

    return packages



# -----------------------------------------------------------------------------
# Upfront Detection of Implicit Rendered Graphics (No Hardcoding Whack-a-Mole)
# -----------------------------------------------------------------------------

FLOAT_ENVIRONMENTS = {"figure", "figure*", "wrapfigure", "sidewaysfigure", "SCfigure", "marginfigure"}
MATH_ENVIRONMENTS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "split", "displaymath", "math", "subequations"
}

COMMUTATIVE_DIAGRAM_ENVS = {
    "tikzcd": "tikz-cd",
    "CD": "amscd",
    "xymatrix": "xy",
    "diagram": "diagrams",
    "xy": "xy",
    "pbdiagram": "pb-diagram",
}

DRAWING_ENVS = {
    "tikzpicture": "tikz",
    "picture": "latex",
    "pgfpicture": "pgf",
    "pspicture": "pstricks",
    "asy": "asymptote",
    "gnuplot": "gnuplottex",
}

SPECIALIZED_CANVAS_ENVS = {
    "circuitikz": "circuitikz",
    "forest": "forest",
    "bytefield": "bytefield",
    "chemfig": "chemfig",
    "blochsphere": "blochsphere",
    "feynman": "feynmf",
    "feynhand": "feynhand",
}

IMAGE_INCLUDE_RE = re.compile(
    r"\\(?:includegraphics|pgfimage|pgfdeclareimage|epsfig|psfig|includesvg)\b"
)

ARROW_TOKEN_RE = re.compile(
    r"\\(?:arrow|ar\b|xrightarrow|xleftarrow|twoheadrightarrow|hookrightarrow|dashrightarrow|mapsto|to\b)|@[><VA]{3}"
)


def detect_implicit_graphics(p_dir: Path, active_tex_files: List[str]) -> List[ImplicitGraphicInfo]:
    """
    Ascertains an upfront inventory of implicit rendered graphics (assetless figures,
    programmatic vector drawings, commutative diagrams, and morphism grids)
    without relying solely on fragile package hardcoding.
    """
    results: List[ImplicitGraphicInfo] = []

    for rel_tex in active_tex_files:
        tex_path = (p_dir / rel_tex).resolve()
        if not tex_path.is_file():
            continue

        try:
            with open_source(tex_path) as f:
                lines = f.readlines()
        except SourceDecodingError:
            raise
        except Exception:
            continue

        env_stack: List[Tuple[str, int]] = []
        local_float_envs = set(FLOAT_ENVIRONMENTS)
        in_definition: bool = False
        def_brace_depth: int = 0
        def_env_name: Optional[str] = None

        in_float: bool = False
        float_start_line: int = 0
        float_env: Optional[str] = None
        float_has_image: bool = False
        float_inner_envs: List[str] = []
        float_lines: List[str] = []

        math_depth: int = 0

        for idx, line in enumerate(lines, start=1):
            clean_line = re.sub(r"(?<!\\)%.*", "", line).strip()
            if not clean_line:
                continue

            # Track \newenvironment / \renewenvironment templates
            new_env_m = re.search(r"\\(?:newenvironment|renewenvironment)\*?\s*\{([^}]+)\}", clean_line)
            if new_env_m:
                in_definition = True
                def_env_name = new_env_m.group(1).strip()
                def_brace_depth = 0

            if in_definition:
                def_brace_depth += clean_line.count("{") - clean_line.count("}")
                if r"\begin{figure" in clean_line and def_env_name:
                    local_float_envs.add(def_env_name)
                if def_brace_depth <= 0:
                    in_definition = False
                    def_env_name = None
                continue

            dollar_count = len(re.findall(r"(?<!\\)\$", clean_line))
            if dollar_count % 2 != 0:
                math_depth = 1 if math_depth == 0 else 0

            is_math_mode = (
                math_depth > 0 or
                any(env in MATH_ENVIRONMENTS for env, _ in env_stack) or
                r"\[" in clean_line or
                r"\(" in clean_line
            )

            # Check \begin{...}
            begins = re.findall(r"\\begin\{([^}]+)\}", clean_line)
            for env in begins:
                env_stack.append((env, idx))
                if env in local_float_envs and not in_float:
                    in_float = True
                    float_start_line = idx
                    float_env = env
                    float_has_image = False
                    float_inner_envs = []
                    float_lines = [clean_line]
                elif in_float:
                    float_inner_envs.append(env)


                if env in COMMUTATIVE_DIAGRAM_ENVS:
                    results.append(ImplicitGraphicInfo(
                        kind=env,
                        category="COMMUTATIVE_DIAGRAM",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=is_math_mode,
                        preview=clean_line[:120],
                        environment_name=env,
                        package_hint=COMMUTATIVE_DIAGRAM_ENVS[env]
                    ))
                elif env in DRAWING_ENVS:
                    results.append(ImplicitGraphicInfo(
                        kind=env,
                        category="PROGRAMMATIC_DRAWING",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=is_math_mode,
                        preview=clean_line[:120],
                        environment_name=env,
                        package_hint=DRAWING_ENVS[env]
                    ))
                elif env in SPECIALIZED_CANVAS_ENVS:
                    results.append(ImplicitGraphicInfo(
                        kind=env,
                        category="SPECIALIZED_CANVAS",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=is_math_mode,
                        preview=clean_line[:120],
                        environment_name=env,
                        package_hint=SPECIALIZED_CANVAS_ENVS[env]
                    ))

            if in_float:
                float_lines.append(clean_line)
                if IMAGE_INCLUDE_RE.search(clean_line):
                    float_has_image = True

            # Standalone macros like \xymatrix{...} or \tikz{...}
            if r"\xymatrix" in clean_line and not any(env == "xymatrix" for env, _ in env_stack):
                results.append(ImplicitGraphicInfo(
                    kind="xymatrix",
                    category="COMMUTATIVE_DIAGRAM",
                    file=rel_tex,
                    line_number=idx,
                    is_floating=in_float,
                    is_math_mode=True,
                    preview=clean_line[:120],
                    environment_name="xymatrix",
                    package_hint="xy"
                ))

            if re.search(r"\\tikz\s*(?:\[[^\]]*\])?\s*\{", clean_line):
                results.append(ImplicitGraphicInfo(
                    kind="tikz_inline",
                    category="PROGRAMMATIC_DRAWING",
                    file=rel_tex,
                    line_number=idx,
                    is_floating=in_float,
                    is_math_mode=is_math_mode,
                    preview=clean_line[:120],
                    environment_name="tikz",
                    package_hint="tikz"
                ))

            # Morphism grid heuristic: table cells with arrow morphisms in math mode
            if is_math_mode and "&" in clean_line and r"\\" in clean_line and ARROW_TOKEN_RE.search(clean_line):
                if not any(r.file == rel_tex and r.line_number == idx for r in results):
                    results.append(ImplicitGraphicInfo(
                        kind="morphism_grid",
                        category="COMMUTATIVE_DIAGRAM",
                        file=rel_tex,
                        line_number=idx,
                        is_floating=in_float,
                        is_math_mode=True,
                        preview=clean_line[:120],
                        environment_name="math_grid",
                        package_hint="amscd/tikz-cd/xy"
                    ))

            # Check \end{...}
            ends = re.findall(r"\\end\{([^}]+)\}", clean_line)
            for env in ends:
                if in_float and env == float_env:
                    if not float_has_image:
                        non_trivial_inner = [e for e in float_inner_envs if e not in ("center", "flushleft", "flushright", "minipage")]
                        inner_env_name = non_trivial_inner[0] if non_trivial_inner else "code_block"
                        preview_str = " ".join(l for l in float_lines if l)[:140]
                        results.append(ImplicitGraphicInfo(
                            kind="assetless_float",
                            category="ASSETLESS_FLOAT",
                            file=rel_tex,
                            line_number=float_start_line,
                            is_floating=True,
                            is_math_mode=False,
                            preview=preview_str,
                            environment_name=inner_env_name,
                            package_hint=DRAWING_ENVS.get(inner_env_name) or COMMUTATIVE_DIAGRAM_ENVS.get(inner_env_name)
                        ))
                    in_float = False
                    float_env = None
                    float_has_image = False
                    float_inner_envs = []
                    float_lines = []

                for s_idx in range(len(env_stack) - 1, -1, -1):
                    if env_stack[s_idx][0] == env:
                        env_stack.pop(s_idx)
                        break

    return results


# -----------------------------------------------------------------------------
# Main Pre-flight Inventory Engine
# -----------------------------------------------------------------------------

def preflight_inventory(

    project_dir: str,
    root_tex: Optional[str] = None,
    engine: str = "pytexml",
    execute_probe: bool = False,
    excluded_dirs: Optional[List[Path]] = None,
) -> PreflightManifest:
    """
    Full project characterization:
      - Automatically detects root_tex if not explicitly provided.
      - Gathers image assets, bibliography, source topology, and package/style bindings.
    """
    p_dir = Path(project_dir).resolve()
    excluded_dirs = excluded_dirs or []
    if not p_dir.exists():
        raise FileNotFoundError(f"Project directory does not exist: {project_dir}")

    # 1. Resolve root .tex file dynamically
    if root_tex is None:
        resolved_root_name = find_root_tex(str(p_dir), excluded_dirs)
    else:
        root_path = (p_dir / root_tex).resolve()
        if not root_path.is_relative_to(p_dir) or excluded_path(root_path, p_dir, excluded_dirs):
            raise ValueError(f"Root must be a source file within the project: {root_tex}")
        if not root_path.is_file():
            raise FileNotFoundError(f"Root TeX file not found: {root_path}")
        resolved_root_name = root_path.relative_to(p_dir).as_posix()

    base_name = Path(resolved_root_name).stem
    root_path = p_dir / resolved_root_name
    aux_path = root_path.with_suffix(".aux")
    bcf_path = root_path.with_suffix(".bcf")
    bbl_path = root_path.with_suffix(".bbl")

    # 2. Parse active inputs recorded via static taxonomy walk
    active_paths = _static_scan_active_paths(p_dir, resolved_root_name, excluded_dirs)
    root_resolved = root_path.resolve()
    active_paths.add(root_resolved)

    # 3. Classify Bibliography
    bib_info = _characterize_bibliography(p_dir, base_name, aux_path, bcf_path, bbl_path, active_paths)

    # 6. Categorize active files vs. local files on disk
    active_images: List[ImageAssetInfo] = []
    active_tex: List[str] = []
    active_style_paths: Set[Path] = set()
    code_inputs: List[str] = []

    active_paths_rel = set()
    for p in active_paths:
        rel = p.relative_to(p_dir).as_posix()
        active_paths_rel.add(rel)
        ext = p.suffix.lower()

        if ext in IMAGE_EXTENSIONS:
            active_images.append(characterize_image(rel, str(p)))
        elif ext == ".tex":
            active_tex.append(rel)
        elif ext in (".sty", ".cls", ".bst", ".clo"):
            active_style_paths.add(p)
        elif ext in CODE_EXTENSIONS:
            code_inputs.append(rel)

    # 7. Characterize all local .sty / .cls files (active vs dormant) and custom macros
    local_styles_info: List[StyleFileInfo] = []
    dormant_styles: List[str] = []

    all_disk_files = list(project_files(p_dir, excluded_dirs))
    for p in all_disk_files:
        ext = p.suffix.lower()
        if ext in (".sty", ".cls", ".bst", ".clo"):
            rel = p.relative_to(p_dir).as_posix()
            if rel.startswith((".git/", "artifacts/", "build/", "extracted/")):
                continue
            is_active = p in active_style_paths
            if is_active:
                local_styles_info.append(probe_style_file(rel, str(p), is_active=True))
            else:
                dormant_styles.append(rel)

    # 8. Package declarations & options across active .tex files
    active_tex_objs = [(p_dir / t).resolve() for t in active_tex]
    packages_declared = extract_package_declarations(p_dir, active_tex_objs)

    # 9. Detect dormant / unreferenced images and tex files
    dormant_images: List[str] = []
    dormant_tex: List[str] = []

    for p in all_disk_files:
        rel = p.relative_to(p_dir).as_posix()
        if rel.startswith((".git/", "artifacts/", "build/", "extracted/")) or p.suffix in (".aux", ".fls", ".log", ".out", ".toc", ".synctex.gz"):
            continue

        if rel not in active_paths_rel:
            ext = p.suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                dormant_images.append(rel)
            elif ext == ".tex":
                dormant_tex.append(rel)

    # 10. Environment & package feature detection
    has_tikz = any("tikz" in s.rel_path.lower() for s in local_styles_info) or any(pkg.name == "tikz" for pkg in packages_declared)
    has_minted = any(pkg.name == "minted" for pkg in packages_declared)
    has_listings = any(pkg.name == "listings" for pkg in packages_declared)
    has_tikz_external = any(pkg.name == "tikz" and "external" in pkg.options for pkg in packages_declared)
    # 11. Upfront detection of implicit rendered graphics (assetless floats, CD, drawings)
    implicit_graphics = detect_implicit_graphics(p_dir, sorted(active_tex))
    has_implicit = len(implicit_graphics) > 0
    has_cd = any(g.category == "COMMUTATIVE_DIAGRAM" for g in implicit_graphics)

    return PreflightManifest(
        root_file=resolved_root_name,
        base_name=base_name,
        project_dir=str(p_dir),
        engine=engine,
        bibliography=bib_info,
        active_images=active_images,
        dormant_images=sorted(dormant_images),
        active_tex_files=sorted(active_tex),
        dormant_tex_files=sorted(dormant_tex),
        packages_declared=packages_declared,
        local_styles=local_styles_info,
        dormant_styles=sorted(dormant_styles),
        code_inputs=sorted(code_inputs),
        implicit_graphics=implicit_graphics,
        implicit_graphics_count=len(implicit_graphics),
        has_implicit_graphics=has_implicit,
        has_commutative_diagrams=has_cd,
        has_tikz=has_tikz,
        has_tikz_external=has_tikz_external,
        has_minted=has_minted,
        has_listings=has_listings
    )



def _clean_bib_entry(b: str) -> str:
    b = b.strip()
    if not b:
        return ""
    return b if b.lower().endswith(".bib") else f"{b}.bib"


def _characterize_bibliography(
    p_dir: Path,
    base_name: str,
    aux_path: Path,
    bcf_path: Path,
    bbl_path: Path,
    active_paths: Set[Path]
) -> BibliographyInfo:
    """Classifies bibliography structure, multi-database declarations, and tracks citation volume."""
    bbl_exists = bbl_path.exists()
    bib_files: List[str] = []
    citations_count = 0
    root_tex = bbl_path.with_suffix(".tex")

    # 1. BibLaTeX detection via .bcf
    if bcf_path.exists():
        with open_source(bcf_path) as f:
            bcf_text = f.read()
            citations_count = len(re.findall(r"<bcf:citekey", bcf_text))
            bib_matches = re.findall(r"<bcf:datasource[^>]*>([^<]+)</bcf:datasource>", bcf_text)
            for m in bib_matches:
                cleaned = _clean_bib_entry(m)
                if cleaned and cleaned not in bib_files:
                    bib_files.append(cleaned)

        missing_bibs = [b for b in bib_files if not (p_dir / b).exists()]

        return BibliographyInfo(
            kind="BIBLATEX",
            backend="biber",
            bbl_path=bbl_path.as_posix() if bbl_exists else None,
            bbl_exists=bbl_exists,
            bbl_needed=not bbl_exists,
            bib_files=bib_files,
            missing_bib_files=missing_bibs,
            citations_count=citations_count
        )

    # 2. Classic BibTeX / Natbib detection via .aux
    if aux_path.exists():
        with open_source(aux_path) as f:
            for line in f:
                if line.startswith(r"\citation{"):
                    citations_count += 1
                elif line.startswith(r"\bibdata{"):
                    raw = line[9:].rstrip("}\n\r")
                    for b in raw.split(","):
                        cleaned = _clean_bib_entry(b)
                        if cleaned and cleaned not in bib_files:
                            bib_files.append(cleaned)

    # 3. Static fallback: scan root .tex source if .aux was missing or didn't find bibdata
    if not bib_files and root_tex.exists():
        with open_source(root_tex) as f:
            tex_content = f.read()

        # Check for multi-bib \bibliography{chaos, ref, sub/more}
        bib_matches = re.finditer(r"\\bibliography\s*\{([^}]+)\}", tex_content)
        for m in bib_matches:
            raw_inside = re.sub(r"%.*", "", m.group(1))
            for piece in raw_inside.split(","):
                cleaned = _clean_bib_entry(piece)
                if cleaned and cleaned not in bib_files:
                    bib_files.append(cleaned)

        # Check for biblatex \addbibresource
        res_matches = re.finditer(r"\\addbibresource(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}", tex_content)
        is_biblatex_source = False
        for m in res_matches:
            is_biblatex_source = True
            raw_inside = re.sub(r"%.*", "", m.group(1))
            cleaned = _clean_bib_entry(raw_inside)
            if cleaned and cleaned not in bib_files:
                bib_files.append(cleaned)

        if is_biblatex_source:
            missing_bibs = [b for b in bib_files if not (p_dir / b).exists()]
            return BibliographyInfo(
                kind="BIBLATEX",
                backend="biber",
                bbl_path=bbl_path.as_posix() if bbl_exists else None,
                bbl_exists=bbl_exists,
                bbl_needed=not bbl_exists,
                bib_files=bib_files,
                missing_bib_files=missing_bibs,
                citations_count=citations_count
            )

    if bib_files:
        missing_bibs = [b for b in bib_files if not (p_dir / b).exists()]
        return BibliographyInfo(
            kind="CLASSIC_BIBTEX",
            backend="bibtex",
            bbl_path=bbl_path.as_posix() if bbl_exists else None,
            bbl_exists=bbl_exists,
            bbl_needed=not bbl_exists,
            bib_files=bib_files,
            missing_bib_files=missing_bibs,
            citations_count=citations_count
        )

    # 4. Check for hardcoded thebibliography in root source
    if root_tex.exists():
        with open_source(root_tex) as f:
            content = f.read()
            if r"\begin{thebibliography}" in content:
                cites = len(re.findall(r"\\bibitem", content))
                return BibliographyInfo(
                    kind="EMBEDDED",
                    backend=None,
                    bbl_path=None,
                    bbl_exists=False,
                    bbl_needed=False,
                    bib_files=[],
                    missing_bib_files=[],
                    citations_count=cites
                )

    # 5. Check if matching .bbl already exists on disk
    if bbl_exists:
        return BibliographyInfo(
            kind="PRECOMPILED_BBL",
            backend=None,
            bbl_path=bbl_path.as_posix(),
            bbl_exists=True,
            bbl_needed=False,
            bib_files=[],
            missing_bib_files=[],
            citations_count=0
        )

    return BibliographyInfo(
        kind="NONE",
        backend=None,
        bbl_path=None,
        bbl_exists=False,
        bbl_needed=False,
        bib_files=[],
        missing_bib_files=[],
        citations_count=0
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python preflight.py <project_dir> [root_tex_name]")
        sys.exit(1)

    proj = sys.argv[1]
    root = sys.argv[2] if len(sys.argv) > 2 else None
    manifest = preflight_inventory(proj, root)
    print(manifest.to_json(indent=2))
