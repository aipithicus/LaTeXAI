"""Output-aware project enumeration and the existing static dependency discovery."""
from __future__ import annotations
import os
from pathlib import Path
import re
from typing import Iterable, Iterator, List, Optional, Set
from ..assets import IMAGE_EXTENSIONS
from ..source_io import SourceDecodingError, open_source
from .manifest import PackageUsage, StyleFileInfo


CODE_EXTENSIONS = {
    ".py", ".c", ".cpp", ".h", ".java", ".rs", ".go", ".js", ".ts",
    ".json", ".csv", ".tsv", ".txt", ".sh", ".yaml", ".yml", ".xml"
}


def excluded_path(path: Path, project_dir: Path, excluded_dirs: Iterable[Path] = ()) -> bool:
    roots = [project_dir / name for name in (".git", "artifacts", "build", "extracted")]
    roots.extend(Path(p) for p in excluded_dirs)
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in roots)


def project_files(project_dir: Path, excluded_dirs: Iterable[Path] = ()) -> Iterator[Path]:
    """Enumerate deterministically without descending into generated output."""
    for directory, dirs, files in os.walk(project_dir):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not excluded_path(base / d, project_dir, excluded_dirs))
        for name in sorted(files):
            path = base / name
            if not excluded_path(path, project_dir, excluded_dirs):
                yield path


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
