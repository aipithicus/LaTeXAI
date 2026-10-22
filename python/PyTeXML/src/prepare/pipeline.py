"""
Unified preprocessing pipeline for LaTeX extraction.

Coordinates:
  1. Preflight Inventory: Discovers root, classifies bibliography, probes assets,
     and ascertains upfront inventory of implicit rendered graphics.
  2. Recursive Inliner: Flattens supported document inclusions.
  3. Semantic Pruner: Prunes dead conditionals, draft macros, and comments, recording tombstones.
  4. Bibliography preparation and bounded whitespace/comment normalization.
  5. Asset Conversion & Packaging: Converts active images to standardized SVGs,
     rewrites supported image references and bundles discovered local styles.
  6. Provenance Ledger: Emits compact RLE interval source map (`master.provenance.json`)
     for diagnostics. Emitted-line accuracy is not yet qualified (see DESIGN.md).
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Dict, List, Optional, Tuple

from .preflight import preflight_inventory, PreflightManifest
from .pruner import prune_latex, prune_latex_provenance
from .inliner import inline_latex_tree, inline_latex_tree_provenance
from .normalizer import knuth_normalize, knuth_normalize_provenance
from ..converter import batch_convert_assets_to_svg, rewrite_tex_image_references, rewrite_lines_image_references
from .provenance import ProvenanceLedger, SourceLine, Tombstone
from ..source_io import open_source
from .bibliography import prepare_bibliography


def preprocess_paper(
    project_dir: str,
    output_dir: Optional[str] = None,
    output_file: Optional[str] = None,
    root_tex: Optional[str] = None,
    execute_probe: bool = False,
    engine: str = "pytexml",
    drop_commands: Optional[List[str]] = None,
    keep_content_commands: Optional[List[str]] = None,
    drop_environments: Optional[List[str]] = None,
    convert_images_to_svg: bool = True,
    copy_local_dependencies: bool = True,
    clean_styles: bool = True,
    emit_manifest_json: bool = True,
    emit_provenance: bool = True,
) -> Tuple[str, PreflightManifest, Path, Optional[ProvenanceLedger]]:
    """
    Executes end-to-end preprocessing, flattening, SVG conversion, and replication packaging.

    Writes the following into output_dir (default: `<project_dir>/extracted`):
      - master.tex: Flattened, pruned, Knuth-normalized LaTeX referencing SVGs.
      - master.provenance.json: Compact RLE source provenance ledger.
      - *.svg: All active raster and vector assets converted to SVG.
      - *.sty / *.cls / local code inputs: Minimal active dependencies needed to compile.
      - manifest.json: Full preflight characterization including implicit graphics inventory.

    Returns:
      (master_tex_content, preflight_manifest, output_directory_path, provenance_ledger)
    """
    p_dir = Path(project_dir).resolve()
    if not p_dir.exists():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    # Determine destination directory
    if output_dir:
        out_dir = Path(output_dir).resolve()
    else:
        out_dir = (p_dir / "extracted").resolve()
    if p_dir.is_relative_to(out_dir):
        raise ValueError("Output directory must not contain or equal the source project")
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = out_dir / "preparation.log"
    log_path.write_text("STARTED\n", encoding="utf-8", newline="\n")
    try:
        # Phase 0: Preflight discovery and implicit graphics characterization
        manifest = preflight_inventory(
            str(p_dir),
            root_tex=root_tex,
            engine=engine,
            execute_probe=execute_probe,
            excluded_dirs=[out_dir],
        )

        root_path = p_dir / manifest.root_file

        # Phase 1 & 2: Recursive inlining, retaining bibliography declarations
        inlined_lines, inliner_tombs = inline_latex_tree_provenance(
            root_tex=root_path,
            project_dir=p_dir,
            bbl_path=None  # Bibliography declarations survive until preparation succeeds.
        )
        all_tombstones: List[Tombstone] = list(inliner_tombs)

        # Phase 3: Semantic pruning (conditionals, draft macros, comments)
        pruned_lines, pruner_tombs = prune_latex_provenance(
            inlined_lines,
            drop_commands=drop_commands,
            keep_content_commands=keep_content_commands,
            drop_environments=drop_environments
        )
        all_tombstones.extend(pruner_tombs)

        pruned_lines, bib_tombs = prepare_bibliography(
            pruned_lines, manifest, p_dir, out_dir,
        )
        all_tombstones.extend(bib_tombs)

        # Phase 4: Bounded whitespace/comment normalization
        normalized_lines, norm_tombs = knuth_normalize_provenance(pruned_lines)
        all_tombstones.extend(norm_tombs)

        # Phase 5: Asset conversion to SVG & reference rewriting
        path_mapping: Dict[str, str] = {}
        if manifest.active_images and not convert_images_to_svg:
            raise ValueError("Active images require SVG conversion for a standalone extraction package")
        if convert_images_to_svg and manifest.active_images:
            active_paths = [Path(img.abs_path) for img in manifest.active_images]
            path_mapping = batch_convert_assets_to_svg(
                active_image_paths=active_paths,
                output_dir=out_dir,
                project_dir=p_dir
            )
            # Rewrite \includegraphics references across SourceLine objects
            final_lines = rewrite_lines_image_references(normalized_lines, path_mapping)
        else:
            final_lines = normalized_lines

        # Assemble master.tex text
        master_tex_content = "".join(l.text for l in final_lines).strip() + "\n"

        # Phase 6: Build Compact Provenance Ledger
        ledger: Optional[ProvenanceLedger] = None
        if emit_provenance:
            ledger = ProvenanceLedger.build_from_lines(final_lines, tombstones=all_tombstones)
            provenance_path = out_dir / "master.provenance.json"
            ledger.save(provenance_path)

        # Phase 7: Copy active local style and code dependencies for self-sufficiency
        if copy_local_dependencies:
            for style in manifest.local_styles:
                if style.is_active and not style.rel_path.startswith("extracted/"):
                    src_style = Path(style.abs_path)
                    if src_style.exists():
                        dst_style = out_dir / style.rel_path
                        dst_style.parent.mkdir(parents=True, exist_ok=True)
                        if src_style.resolve() != dst_style.resolve():
                            ext = src_style.suffix.lower()
                            if clean_styles and ext in (".sty", ".cls", ".clo", ".def", ".bbx", ".cbx"):
                                raw_code = open_source(src_style).read()
                                cleaned_code = knuth_normalize(raw_code)
                                dst_style.write_text(cleaned_code, encoding="utf-8", newline="\n")
                            else:
                                shutil.copy2(src_style, dst_style)


            for code_rel in manifest.code_inputs:
                if not code_rel.startswith("extracted/"):
                    src_code = p_dir / code_rel
                    if src_code.exists():
                        dst_code = out_dir / code_rel
                        dst_code.parent.mkdir(parents=True, exist_ok=True)
                        if src_code.resolve() != dst_code.resolve():
                            shutil.copy2(src_code, dst_code)


        # Phase 8: Emit standard master.tex
        master_tex_path = out_dir / "master.tex"
        with open(master_tex_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(master_tex_content)

        if output_file:
            out_f = Path(output_file).resolve()
            out_f.parent.mkdir(parents=True, exist_ok=True)
            with open(out_f, "w", encoding="utf-8", newline="\n") as f:
                f.write(master_tex_content)

        # Phase 9: Emit manifest JSON sidecar
        manifest.entrypoint = "master.tex"
        if emit_manifest_json:
            manifest_path = out_dir / "manifest.json"
            with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(manifest.to_json(indent=2))

        warnings = [img.dimension_error for img in manifest.active_images if img.dimension_error]
        warnings.extend(manifest.bibliography.preparation_warnings)
        log_path.write_text("SUCCESS\n" + "".join(f"WARNING: {message}\n" for message in warnings), encoding="utf-8", newline="\n")
        return master_tex_content, manifest, out_dir, ledger
    except Exception as exc:
        log_path.write_text(f"FAILED\n{type(exc).__name__}: {exc}\n", encoding="utf-8", newline="\n")
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare a standalone LaTeX extraction package")
    parser.add_argument("project_dir")
    parser.add_argument("output_dir", nargs="?")
    parser.add_argument("root_tex", nargs="?")
    args = parser.parse_args()
    cleaned_text, manifest, out_path, ledger = preprocess_paper(
        args.project_dir, output_dir=args.output_dir, root_tex=args.root_tex,
    )
    print(f"\n[pipeline] Preprocessing complete for: {manifest.root_file}")
    print(f"[pipeline] Replication package emitted to: {out_path}")
    print(f"[pipeline] Master TeX file: {out_path / 'master.tex'} ({len(cleaned_text):,} chars)")
    print(f"[pipeline] Active image assets converted to SVG: {len(manifest.active_images)}")
    print(f"[pipeline] Implicit rendered graphics detected: {manifest.implicit_graphics_count}")
    for g in manifest.implicit_graphics:
        print(f"    - [{g.category}] {g.kind} in {g.file}:{g.line_number} (floating={g.is_floating}, math={g.is_math_mode})")
    print(f"[pipeline] Bibliography kind: {manifest.bibliography.kind} (bbl_exists={manifest.bibliography.bbl_exists})")

    if ledger:
        summary = ledger.summary()
        print(f"[pipeline] Provenance ledger: {out_path / 'master.provenance.json'}")
        print(f"    - Master lines mapped: {summary['total_master_lines']}")
        print(f"    - Compact RLE runs: {summary['total_runs']} ({summary['compression_ratio']}x compression)")
        print(f"    - Pruned tombstones tracked: {summary['total_tombstones']}")
        print(f"    - Source files: {summary['sources_count']}")
