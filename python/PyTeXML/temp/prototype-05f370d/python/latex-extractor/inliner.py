r"""
Recursive flattener & inliner for LaTeX documents with source provenance.

Capabilities:
  - Recursive inlining of \input, \include, \subimport, \import.
  - Directory stack management for relative asset and file scoping.
  - Bibliography splicing: replaces \bibliography{...} with precompiled .bbl content.
  - Truncation at \end{document} and \endinput with tombstone recording.
  - Recursion cycle protection.
  - Emits fine-grained SourceLine and Tombstone records for compact provenance ledgers.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import List, Optional, Set, Tuple

try:
    from .provenance import SourceLine, Tombstone
    from .source_io import SourceDecodingError, open_source
except ImportError:
    from provenance import SourceLine, Tombstone  # type: ignore
    from source_io import SourceDecodingError, open_source


def inline_latex_tree_provenance(
    root_tex: Path,
    project_dir: Path,
    bbl_path: Optional[Path] = None,
    dir_stack: Optional[List[Path]] = None,
    visited_files: Optional[Set[Path]] = None
) -> Tuple[List[SourceLine], List[Tombstone]]:
    """
    Recursively inlines all child LaTeX files into a list of SourceLine objects,
    preserving the exact origin file and line number for every line.
    """
    if dir_stack is None:
        dir_stack = [project_dir.resolve()]
    if visited_files is None:
        visited_files = set()

    current_dir = dir_stack[-1]
    resolved_root = root_tex.resolve()

    try:
        rel_path = resolved_root.relative_to(project_dir).as_posix()
    except ValueError:
        rel_path = resolved_root.name

    if resolved_root in visited_files:
        return [SourceLine(f"% [Recursive include cycle avoided: {rel_path}]\n", rel_path, 1, "CYCLE_AVOIDED")], []
    visited_files.add(resolved_root)

    try:
        if not resolved_root.exists():
            return [SourceLine(f"% [Missing file during inlining: {rel_path}]\n", rel_path, 1, "MISSING_FILE")], []

        try:
            with open_source(resolved_root) as f:
                raw_text = f.read()
        except SourceDecodingError:
            raise
        except Exception as e:
            return [SourceLine(f"% [Error reading {rel_path}: {e}]\n", rel_path, 1, "READ_ERROR")], []

        # Universal LF normalization on the raw source
        raw_text = re.sub(r"\r\n|[\r\x0b\x0c\x85\u2028\u2029]", "\n", raw_text)
        raw_lines = raw_text.splitlines(keepends=True)

        out_lines: List[SourceLine] = []
        tombstones: List[Tombstone] = []
        truncated = False

        bbl_rel: Optional[str] = None
        if bbl_path and bbl_path.exists():
            try:
                bbl_rel = bbl_path.relative_to(project_dir).as_posix()
            except ValueError:
                bbl_rel = bbl_path.name

        for idx, line in enumerate(raw_lines, start=1):
            if truncated:
                continue

            # Check \endinput or \end{document} truncation
            if r"\endinput" in line:
                end_idx = line.find(r"\endinput")
                kept_part = line[:end_idx]
                if kept_part.strip():
                    out_lines.append(SourceLine(kept_part + "\n", rel_path, idx, "IDENTITY"))
                if idx < len(raw_lines):
                    tombstones.append(Tombstone(rel_path, idx + 1, len(raw_lines), "TRUNCATED_AT_END", "Content following \\endinput"))
                truncated = True
                continue

            if r"\end{document}" in line:
                end_idx = line.find(r"\end{document}") + len(r"\end{document}")
                kept_part = line[:end_idx]
                out_lines.append(SourceLine(kept_part + "\n", rel_path, idx, "IDENTITY"))
                if idx < len(raw_lines):
                    tombstones.append(Tombstone(rel_path, idx + 1, len(raw_lines), "TRUNCATED_AT_END", "Content following \\end{document}"))
                truncated = True
                continue

            # Inlining \input{...} and \include{...}
            m_input = re.search(r"\\(input|include)\s*\{([^}]+)\}", line)
            if m_input:
                cmd = m_input.group(1)
                raw_target = m_input.group(2).strip()
                target_name = raw_target if raw_target.endswith(".tex") else f"{raw_target}.tex"
                target_path = (current_dir / target_name).resolve()
                if not target_path.exists():
                    target_path = (project_dir / target_name).resolve()

                if cmd == "include":
                    out_lines.append(SourceLine("\\clearpage\n", rel_path, idx, "INLINE_INPUT"))

                child_lines, child_tombs = inline_latex_tree_provenance(target_path, project_dir, bbl_path, dir_stack, visited_files)
                out_lines.extend(child_lines)
                tombstones.extend(child_tombs)

                if cmd == "include":
                    out_lines.append(SourceLine("\\clearpage\n", rel_path, idx, "INLINE_INPUT"))
                continue

            # Inlining \subimport{dir}{file} and \import{dir}{file}
            m_import = re.search(r"\\(?:sub)?import\s*\{([^}]+)\}\s*\{([^}]+)\}", line)
            if m_import:
                sub_dir_raw = m_import.group(1).strip()
                sub_file_raw = m_import.group(2).strip()
                sub_file_name = sub_file_raw if sub_file_raw.endswith(".tex") else f"{sub_file_raw}.tex"
                next_dir = (current_dir / sub_dir_raw).resolve()
                target_path = (next_dir / sub_file_name).resolve()

                dir_stack.append(next_dir)
                try:
                    child_lines, child_tombs = inline_latex_tree_provenance(target_path, project_dir, bbl_path, dir_stack, visited_files)
                finally:
                    dir_stack.pop()
                out_lines.extend(child_lines)
                tombstones.extend(child_tombs)
                continue

            # Splicing Bibliography -> .bbl
            if re.search(r"\\bibliographystyle\s*\{[^}]*\}", line):
                if bbl_path and bbl_path.is_file():
                    tombstones.append(Tombstone(rel_path, idx, idx, "STRIP_BIBSTYLE", "Bibliographystyle command stripped"))
                    continue

            if re.search(r"\\bibliography\s*\{[^}]*\}", line):
                if bbl_path and bbl_path.exists():
                    try:
                        with open_source(bbl_path) as f:
                            bbl_lines = f.read().splitlines(keepends=True)
                        for b_idx, b_line in enumerate(bbl_lines, start=1):
                            out_lines.append(SourceLine(b_line, bbl_rel or "bibliography.bbl", b_idx, "SPLICE_BIB"))
                    except SourceDecodingError:
                        raise
                    except Exception:
                        raise
                    continue

            # Normal line
            out_lines.append(SourceLine(line, rel_path, idx, "IDENTITY"))

        return out_lines, tombstones
    finally:
        visited_files.remove(resolved_root)


def inline_latex_tree(
    root_tex: Path,
    project_dir: Path,
    bbl_path: Optional[Path] = None,
    dir_stack: Optional[List[Path]] = None,
    visited_files: Optional[Set[Path]] = None
) -> str:
    """
    Recursively inlines all child \\input, \\include, and \\subimport files into
    a single contiguous document string. Slices in .bbl at \\bibliography{...}.
    """
    lines, _ = inline_latex_tree_provenance(
        root_tex=root_tex,
        project_dir=project_dir,
        bbl_path=bbl_path,
        dir_stack=dir_stack,
        visited_files=visited_files
    )
    return "".join(l.text for l in lines)
