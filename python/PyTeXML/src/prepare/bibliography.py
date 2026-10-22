"""Prepare a standalone classic bibliography before publishing the master.

Existing thebibliography BBLs are reused. Missing BBLs are prepared from native
BibTeX data parsing; preparation never invokes a TeX engine.
Biblatex data BBLs are not interchangeable with formatted thebibliography.
"""

from __future__ import annotations

from pathlib import Path
import re

from .manifest import BibliographyInfo, PreflightManifest
from .provenance import SourceLine, Tombstone
from ..source_io import open_source
from ..bibtex import Database, BibTeXError
from typing import List, Set


class BibliographyPreparationError(ValueError):
    pass


_BIB = re.compile(r"\\bibliography\s*\{([^{}]+)\}")
_STYLE = re.compile(r"\\bibliographystyle\s*\{([^{}]+)\}")
_CITE = re.compile(
    r"\\(?:[Cc]ite(?:t|p|alp|alt|author|year|yearpar|num|fullauthor)?|"
    r"autocite|parencite|textcite|footcite|nocite)\*?"
    r"\s*(?:\[[^\]]*\]\s*){0,2}\{([^{}]+)\}"
)
_ITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}")


def _visible_source(text: str) -> str:
    """Mask comments and conventional literal regions, retaining offsets.

    This is bounded lexical discovery, not macro expansion or an AST.
    """
    pattern = re.compile(
        r"\\begin\{(verbatim\*?|Verbatim\*?|lstlisting|minted|filecontents\*?)\}"
        r"[\s\S]*?\\end\{\1\}|\\verb\*?(?P<delimiter>[^\s])[^\n]*?(?P=delimiter)"
    )
    masked = list(text)
    for match in pattern.finditer(text):
        for i in range(match.start(), match.end()):
            if masked[i] != "\n":
                masked[i] = " "
    for match in re.finditer(r"%", "".join(masked)):
        if masked[match.start()] != "%":
            continue
        slash_count = 0
        i = match.start() - 1
        while i >= 0 and masked[i] == "\\":
            slash_count += 1
            i -= 1
        if slash_count % 2 == 0:
            end = text.find("\n", match.start())
            if end < 0:
                end = len(text)
            masked[match.start():end] = " " * (end - match.start())
    return "".join(masked)


def _resource(name: str, suffix: str, project_dir: Path, origin: Path) -> Path:
    name = name.strip()
    if not name.endswith(suffix):
        name += suffix
    for directory in dict.fromkeys([project_dir, origin.parent]):
        path = (directory / name).resolve()
        if path.is_file():
            return path
    raise BibliographyPreparationError(f"Bibliography resource not found: {name} (from {origin})")


def prepare_bibliography(
    lines: list[SourceLine], manifest: PreflightManifest, project_dir: Path,
    output_dir: Path,
) -> tuple[list[SourceLine], list[Tombstone]]:
    text = "".join(line.text for line in lines)
    visible = _visible_source(text)
    declarations = list(_BIB.finditer(visible))
    if manifest.bibliography.kind == "BIBLATEX" or re.search(r"\\(?:addbibresource|printbibliography)\b", visible):
        raise BibliographyPreparationError(
            "Biblatex bibliography preparation requires a formatter for its metadata BBL; "
            "it cannot be pasted as thebibliography. No master was published."
        )
    if not declarations:
        return lines, []
    if len(declarations) != 1:
        raise BibliographyPreparationError("Multiple bibliography sites require separate preparation; no master was published")

    root_path = project_dir / manifest.root_file
    existing = Path(manifest.bibliography.bbl_path) if manifest.bibliography.bbl_path else None
    # Locate the declaring source for relative resources in an included file.
    offset = 0
    origin = root_path
    for line in lines:
        if offset <= declarations[0].start() < offset + len(line.text):
            origin = project_dir / line.src_file
            break
        offset += len(line.text)
    resources = []
    for name in declarations[0].group(1).split(","):
        try:
            path = _resource(name, ".bib", project_dir, origin)
        except BibliographyPreparationError:
            if existing and existing.is_file():
                continue  # An existing formatted BBL needs no source databases.
            raise
        if path not in resources:
            resources.append(path)
    # One package-local database retains fields that formatted entries omit.
    canonical = "\n".join(open_source(path).read().rstrip() + "\n" for path in resources)

    keys = list(dict.fromkeys(key.strip() for match in _CITE.finditer(visible)
                             for key in match.group(1).split(",")))
    if any(not key or re.search(r"[\\{}%#\s]", key) for key in keys):
        raise BibliographyPreparationError("Nonliteral citation key requires expansion before bibliography preparation")
    if existing and existing.is_file():
        bbl = open_source(existing).read()
        backend = "existing-bbl"
    else:
        if not keys:
            raise BibliographyPreparationError("No supported literal citation commands found; cannot choose bibliography entries")
        database = Database()
        try:
            for resource in resources:
                database.read(open_source(resource).read(), str(resource))
            bbl = extraction_bbl(database, keys)
        except BibTeXError as exc:
            raise BibliographyPreparationError(str(exc)) from exc
        backend = "native-bibtex"
        manifest.bibliography.preparation_warnings = database.diagnostics
    if not re.search(r"\\begin\{thebibliography\}", bbl) or not re.search(r"\\end\{thebibliography\}", bbl):
        raise BibliographyPreparationError("Prepared .bbl does not contain a complete thebibliography environment")
    entry_keys = set(_ITEM.findall(bbl))
    missing = [key for key in keys if key != "*" and key not in entry_keys]
    if missing:
        raise BibliographyPreparationError("Bibliography entries missing for citation keys: " + ", ".join(missing))

    if canonical:
        (output_dir / "bibliography.bib").write_text(canonical, encoding="utf-8", newline="\n")
    (output_dir / "bibliography.bbl").write_text(bbl, encoding="utf-8", newline="\n")
    manifest.bibliography.prepared_bbl = "bibliography.bbl"
    manifest.bibliography.canonical_bib = "bibliography.bib" if canonical else None
    manifest.bibliography.preparation_backend = backend
    manifest.bibliography.bbl_needed = False
    manifest.bibliography.citations_count = len(entry_keys)

    # Replace only command spans; adjacent manuscript text survives.
    edits = [(m.start(), m.end(), False) for m in _STYLE.finditer(visible)]
    edits.append((declarations[0].start(), declarations[0].end(), True))
    result = []
    tombstones = []
    cursor = 0
    offset = 0
    edits.sort()
    edit_index = 0
    for line in lines:
        end = offset + len(line.text)
        cursor = max(cursor, offset)
        while edit_index < len(edits) and edits[edit_index][0] < end:
            start, stop, insert = edits[edit_index]
            if start > cursor:
                result.append(SourceLine(text[cursor:start], line.src_file, line.src_line, line.op))
            if insert:
                result.extend(SourceLine(part, "bibliography.bbl", i, "SPLICE_BIB")
                              for i, part in enumerate(bbl.splitlines(keepends=True), 1))
            tombstones.append(Tombstone(line.src_file, line.src_line, line.src_line,
                                        "PREPARE_BIB", "Replaced by prepared inline bibliography"))
            cursor = stop
            edit_index += 1
        if cursor < end:
            result.append(SourceLine(text[cursor:end], line.src_file, line.src_line, line.op))
        offset = end
    return result, tombstones


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


def extraction_bbl(database: Database, keys: list[str]) -> str:
    """Serialize keyed, field-labelled content; no publisher-style emulation."""
    entries = database.selected(keys)
    lines = [value.resolve() for value in database.preambles]
    lines.append(r"\begin{thebibliography}{" + str(max(1, len(entries))) + "}")
    for entry in entries:
        if re.search(r"[\\{}%#\s]", entry.key):
            raise BibTeXError(f"Cannot emit nonliteral bibliography key {entry.key!r}")
        lines.append(r"\bibitem{" + entry.key + "}")
        lines.append(r"\textbf{entrytype}: " + _label(entry.kind) + r"\par")
        for name, field_value in entry.fields:
            value = field_value.resolve()
            # Bibliographic data preserves raw URL/identifier characters.
            # Other values remain TeX source, including grouping and math.
            if name in ("url", "doi", "eprint") and "\\" not in value:
                value = r"\url{" + value + "}"
            lines.append(r"\textbf{" + _label(name) + "}: {" + value + r"}\par")
    lines.append(r"\end{thebibliography}")
    return "\n".join(lines) + "\n"


def _label(text: str) -> str:
    # Labels are data, never field-supplied TeX commands.
    return "".join("\\" + ch if ch in "_&#%${}" else
                   r"\textasciitilde{}" if ch == "~" else
                   r"\textasciicircum{}" if ch == "^" else ch for ch in text)
