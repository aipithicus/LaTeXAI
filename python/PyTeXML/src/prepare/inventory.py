"""Assemble the preparation manifest from discovery and resource inspection."""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Set
from ..assets import IMAGE_EXTENSIONS, ImageAssetInfo, characterize_image
from .bibliography import _characterize_bibliography
from .discovery import (
    CODE_EXTENSIONS, excluded_path, project_files, find_root_tex,
    _static_scan_active_paths, probe_style_file, extract_package_declarations,
)
from .implicit_graphics import detect_implicit_graphics
from .manifest import PreflightManifest, StyleFileInfo


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


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.prepare.inventory <project_dir> [root_tex_name]")
        sys.exit(1)

    proj = sys.argv[1]
    root = sys.argv[2] if len(sys.argv) > 2 else None
    manifest = preflight_inventory(proj, root)
    print(manifest.to_json(indent=2))
