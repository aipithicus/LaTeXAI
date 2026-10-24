"""Render original and prepared sources in disposable, independent workspaces.

This optional module owns its explicit compiler configuration. Preparation has
no import or execution dependency on it. Only PDFs, logs and a report survive;
staged inputs, SVG derivatives, aux files and generated font caches are removed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from ..source_io import SourceStore
from .assets import SVG_DRIVER, stage_svg


DRIVER_NAME = "__pytexml_svg_driver__.tex"
BOOTSTRAP = ("\\AddToHook{package/graphics/after}{\\input{" + DRIVER_NAME + "}}\n").encode("ascii")
BOOKKEEPING = {"manifest.json", "master.provenance.json", "preparation.log"}
BYPRODUCTS = {".aux", ".log", ".out", ".toc", ".lof", ".lot", ".blg", ".fls", ".synctex"}


@dataclass(frozen=True)
class RenderConfig:
    tectonic: Path
    timeout_seconds: float = 120
    bundle: str | None = None
    only_cached: bool = True
    fontconfig_file: Path | None = None
    font_dirs: tuple[Path, ...] = ()

    def validate(self):
        if not self.tectonic.is_file():
            raise ValueError(f"Explicit Tectonic executable not found: {self.tectonic}")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Compiler timeout must be finite and positive")
        if self.fontconfig_file and self.font_dirs:
            raise ValueError("Supply a Fontconfig file or font directories, not both")
        if self.fontconfig_file and not self.fontconfig_file.is_file():
            raise ValueError(f"Fontconfig file not found: {self.fontconfig_file}")
        if any(not p.is_dir() for p in self.font_dirs):
            raise ValueError("Every configured font directory must exist")


def compiler_environment(config: RenderConfig, work: Path) -> tuple[dict, dict]:
    """One child-process environment for both sides; never mutate os.environ."""
    env = dict(os.environ)
    info = {"mode": "inherited"}
    if config.font_dirs:
        root = ET.Element("fontconfig")
        for directory in config.font_dirs:
            ET.SubElement(root, "dir").text = directory.resolve().as_posix()
        cache = work / "font-cache"
        cache.mkdir()
        ET.SubElement(root, "cachedir").text = cache.as_posix()
        path = work / "fonts.conf"
        path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
        info = {"mode": "temporary_config", "directories": [p.resolve().as_posix() for p in config.font_dirs]}
    elif config.fontconfig_file:
        path = config.fontconfig_file.resolve()
        info = {"mode": "explicit_config", "path": path.as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    else:
        return env, info
    env["FONTCONFIG_FILE"] = str(path)
    env["FONTCONFIG_PATH"] = str(path.parent)
    return env, info


def stage_project(source: Path, main: str, destination: Path, *, excluded_dirs=()) -> dict:
    """Stage each side from its own files, with no access to the other side."""
    store = SourceStore(source, excluded_dirs)
    entry = (store.root / main).resolve()
    if not store.contains(entry) or entry.suffix.lower() != ".tex":
        raise ValueError(f"Main document must be an inventoried .tex file: {main}")
    selected = [p for p in store.files if p.name not in BOOKKEEPING and p.suffix.lower() not in BYPRODUCTS]
    relative = {p.relative_to(store.root) for p in selected}
    main_relative = entry.relative_to(store.root)
    driver = main_relative.parent / DRIVER_NAME
    if driver in relative:
        raise ValueError(f"Reserved validation filename already exists: {driver}")
    for rel in relative:
        if rel.suffix.lower() == ".svg" and any(rel.with_name(rel.name + suffix) in relative for suffix in (".pdf", ".bb")):
            raise ValueError(f"SVG rendering derivative collides with a source file: {rel}")
    destination.mkdir(parents=True)
    receipt = {"main": main_relative.as_posix(), "files": [], "svg_derivatives": []}
    for path in selected:
        rel = path.relative_to(store.root)
        target = destination / rel
        data = store.read_bytes(path)
        receipt["files"].append({"path": rel.as_posix(), "sha256": hashlib.sha256(data).hexdigest()})
        if path.suffix.lower() == ".svg":
            receipt["svg_derivatives"].append({"path": rel.as_posix(), **stage_svg(data, target)})
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if path == entry:
                # Keep the original basename/jobname (and any existing BBL),
                # inserting only a renderer hook in this temporary copy.
                bom = b"\xef\xbb\xbf"
                data = bom + BOOTSTRAP + data[len(bom):] if data.startswith(bom) else BOOTSTRAP + data
            target.write_bytes(data)
    (destination / driver).write_text(SVG_DRIVER, encoding="ascii", newline="\n")
    return receipt


def render_one(source: Path, main: str, label: str, output: Path, work: Path,
               config: RenderConfig, env: dict) -> dict:
    stage = work / label
    result = {"status": "failed", "source": str(source), "main": main, "pdf": None,
              "log": label + ".log"}
    log_path = output / result["log"]
    try:
        result["inputs"] = stage_project(source, main, stage / "source", excluded_dirs=[output])
        main_path = stage / "source" / result["inputs"]["main"]
        build = stage / "build"
        build.mkdir()
        command = [str(config.tectonic.resolve()), "-X", "compile", "--untrusted", "--keep-logs",
                   "--print", "--outdir", str(build)]
        if config.only_cached:
            command.append("--only-cached")
        if config.bundle:
            command.extend(["--bundle", config.bundle])
        command.append(str(main_path))
        with log_path.open("wb") as log:
            process = subprocess.run(command, cwd=main_path.parent, env=env, stdout=log,
                                     stderr=subprocess.STDOUT, timeout=config.timeout_seconds, check=False)
        result["returncode"] = process.returncode
        pdf = build / (main_path.stem + ".pdf")
        if process.returncode != 0:
            result["error"] = "Compiler returned an error; inspect the retained log"
        elif not pdf.is_file():
            result["error"] = "Compiler did not produce a PDF"
        else:
            import pymupdf

            with pymupdf.open(pdf) as document:
                if not document.is_pdf or document.needs_pass or len(document) == 0:
                    raise ValueError("Compiler output is not a readable, nonempty PDF")
                result["pages"] = len(document)
            result["status"] = "rendered"
            result["pdf"] = label + ".pdf"
            shutil.move(str(pdf), str(output / result["pdf"]))
    except subprocess.TimeoutExpired:
        result.update(status="timeout", error=f"Compiler exceeded {config.timeout_seconds:g} seconds")
    except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    if "error" in result:
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write("\nADAPTER: " + result["error"] + "\n")
    return result


def compare_pdfs(original: Path, prepared: Path) -> dict:
    """Content observations, not a pass/fail judgement of manuscript fidelity."""
    import pymupdf

    def inspect(path):
        with pymupdf.open(path) as doc:
            text = "\n".join(page.get_text() for page in doc)
            images = Counter((i["width"], i["height"], i["digest"].hex())
                             for page in doc for i in page.get_image_info(hashes=True))
            return {"pages": len(doc), "text_characters": len(text),
                    "image_occurrences": images.total()}, Counter(text.split()), images

    left, left_words, left_images = inspect(original)
    right, right_words, right_images = inspect(prepared)
    common_words = (left_words & right_words).total()
    return {"original": left, "prepared": right,
            "common_word_occurrences": common_words,
            "original_word_occurrences": left_words.total(), "prepared_word_occurrences": right_words.total(),
            "matching_raster_image_occurrences": (left_images & right_images).total(),
            "original_only_words": (left_words - right_words).most_common(30),
            "prepared_only_words": (right_words - left_words).most_common(30),
            "assessment": "observations_only",
            "limitations": ["Text extraction and word overlap do not prove mathematical or structural equivalence.",
                            "Image digests compare decoded raster content, not placement or vector drawings.",
                            "Canonical bibliography formatting can intentionally change text, layout and page count."]}


def render_comparison(original_dir: Path, original_main: str, prepared_dir: Path,
                      output_dir: Path, config: RenderConfig) -> dict:
    """Publish a new comparison directory; dispose of inputs on every exit path."""
    config.validate()
    original, prepared, output = original_dir.resolve(), prepared_dir.resolve(), output_dir.resolve()
    for source in (original, prepared):
        if not source.is_dir():
            raise ValueError(f"Source directory not found: {source}")
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("Comparison output must be separate from both source trees")
    output.mkdir(parents=True, exist_ok=False)  # never mistake an older PDF for success
    report = {"schema": "pytexml-render-comparison/1", "compiler": str(config.tectonic.resolve()),
              "bundle": config.bundle, "only_cached": config.only_cached, "status": "failed"}
    with tempfile.TemporaryDirectory(prefix=".render-", dir=output) as directory:
        work = Path(directory)
        env, report["fonts"] = compiler_environment(config, work)
        try:
            version = subprocess.run([str(config.tectonic.resolve()), "--version"], env=env,
                capture_output=True, timeout=config.timeout_seconds, check=True)
            report["compiler_version"] = version.stdout.decode("utf-8", errors="replace").strip()
            for label, source, main in (("original", original, original_main), ("prepared", prepared, "master.tex")):
                report[label] = render_one(source, main, label, output, work, config, env)
            if all(report[label]["status"] == "rendered" for label in ("original", "prepared")):
                report["comparison"] = compare_pdfs(output / "original.pdf", output / "prepared.pdf")
                report["status"] = "rendered"
            else:
                report["status"] = "incomplete"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            report["error"] = f"{type(error).__name__}: {error}"
    report["temporary_inputs_removed"] = True
    (output / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original_dir", type=Path)
    parser.add_argument("original_main", help="TeX path relative to the original source directory")
    parser.add_argument("prepared_dir", type=Path)
    parser.add_argument("output_dir", type=Path, help="New directory outside both source trees")
    parser.add_argument("--tectonic", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--bundle")
    parser.add_argument("--allow-downloads", action="store_true")
    fonts = parser.add_mutually_exclusive_group()
    fonts.add_argument("--fontconfig", type=Path)
    fonts.add_argument("--font-dir", type=Path, action="append", default=[])
    args = parser.parse_args()
    report = render_comparison(args.original_dir, args.original_main, args.prepared_dir, args.output_dir,
        RenderConfig(args.tectonic, args.timeout, args.bundle, not args.allow_downloads,
                     args.fontconfig, tuple(args.font_dir)))
    print(json.dumps({"status": report["status"], "report": str(args.output_dir / "comparison.json")}, indent=2))
    return 0 if report["status"] == "rendered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
