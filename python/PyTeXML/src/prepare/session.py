"""One cached, ordered traversal owns dependency discovery and master assembly.

The dispatcher owns TeX execution routing. This owner supplies input occurrences,
resolves declared resources and records emissions. It does not expand macros or
fall back to raw-text dependency searches at an unresolved reading boundary.
"""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
import re

from ..source_io import SourceStore
from ..assets import IMAGE_EXTENSIONS, characterize_image
from ..bindings.resolver import BindingResolver
from ..reading.dispatcher import StructuralDispatcher, InputRecovery
from ..reading.argument_scanner import key_values
from ..reading.coverage import ReadingCoverage
from ..reading.contracts import (SourceCommand, SourceEnd, ReadingBoundary, ReadingIssue,
                                StoredDefinition, SkippedRegion, DeferredRegion, LiteralRegion)
from ..reading.tex_reader import TexReader, ReadEvent, TokenKind, CatCode
from .discovery import select_root
from .emission import SourcePiece, event_text
from .survey import survey_sources
from .policy import load_policy
from .resources import prepare_external_literal
from .provenance import Tombstone
from .manifest import PreflightManifest, BibliographyInfo, PackageUsage, StyleFileInfo, ImplicitGraphicInfo


class PreparationUnresolved(ValueError):
    """A concrete resource error prevents preparation (not missing knowledge)."""


class _PreserveRemainder(Exception):
    """Stop justified edits, while allowing publication of preserved source."""


class _DeferredCommand(Exception):
    """One fully scanned command needs resolution; later source remains readable."""


@dataclass
class _Input:
    path: Path
    reader: TexReader
    emit: bool
    import_dir: Path | None = None
    packages: list = field(default_factory=list)
    include: bool = False
    bibliography_start: int | None = None
    recovery: InputRecovery | None = None


class PreparationSession:
    def __init__(self, project_dir: Path, *, root_tex=None, excluded_dirs=(), engine="pytexml", catalog=None, policy="prepare"):
        self.store = SourceStore(project_dir, excluded_dirs)
        self.resolver = BindingResolver(catalog)
        self.root = select_root(self.store, root_tex, catalog=self.resolver.catalog)
        self.context = self.resolver.new_context()
        self.policy = load_policy(policy)
        self.literal_payloads = {}
        self.manifest = PreflightManifest(self.name(self.root), self.root.stem, str(self.store.root), engine,
            BibliographyInfo("NONE", None, None, False, False))
        self.pieces: list[SourcePiece] = []
        self.tombstones = []
        self.frames: list[_Input] = []
        self.active: set[Path] = set()
        self.styles: dict[Path, StyleFileInfo] = {}
        self.images: set[Path] = set()
        self._implicit = []
        self.code: set[Path] = set()
        self.payload_edits: dict[Path, dict[tuple[int, int], str]] = {}
        self.commands: list[SourceCommand] = []
        self.documents = {}
        self.line_starts = {}
        self.loaded_packages: set[str] = set()
        self.graphic_paths: dict[int, list[Path]] = {}
        self.graphic_extensions: dict[int, list[str]] = {}
        self.includeonly: set[str] | None = None
        self.bibliography_pieces = None
        self.bibliography_context = None
        self.bibliography_knowledge = None
        self._ran = False
        self._ended_document = False
        self._observations = {}
        self.coverage = {}
        first = self._reader(self.root)
        self._root_reader = first
        self.frames.append(_Input(self.root, first, True))
        self.dispatcher = StructuralDispatcher(first, self.context, self.resolver, source_commands=True, preparation=True)
        self.manifest.reading_assumptions = [
            "Source-visible preparation does not expand macros. Unbound commands and packages are not assumed to generate inputs or change entry catcodes.",
            "Uninterpreted math, environments and adjacent command groups retain their source; their contents are not executed."]

    def name(self, path):
        return path.relative_to(self.store.root).as_posix()

    def _reader(self, path):
        doc = self.store.document(path)
        occurrence = len(self.manifest.input_occurrences)
        reader = TexReader(doc.text, source_id=doc.name, occurrence_id=occurrence,
                           catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.documents[reader.basis] = doc
        self._observations[reader.basis] = []
        if path not in self.line_starts:
            self.line_starts[path] = [0] + [m.end() for m in re.finditer(r"\r\n|\r|\n", doc.text)]
        self.active.add(path)
        self.manifest.input_occurrences.append({"id": occurrence, "source": doc.name,
            "parent": self.frames[-1].reader.basis.occurrence_id if self.frames else None})
        return reader

    def line(self, span):
        return bisect_right(self.line_starts[self.documents[span.basis].path], span.start)

    def raw(self, span):
        return self.documents[span.basis].text[span.start:span.end]

    def diagnose(self, span, reason, detail):
        diagnostic = {"source": span.basis.source_id, "occurrence": span.basis.occurrence_id,
                      "start": span.start, "end": span.end, "line": self.line(span),
                      "reason": reason, "detail": detail}
        self.manifest.unresolved.append(diagnostic)
        return diagnostic

    def fail(self, span, reason, detail):
        diagnostic = self.diagnose(span, reason, detail)
        raise PreparationUnresolved(f"{diagnostic['source']}:{diagnostic['line']} [{reason}] {detail}")

    def require(self, span, reason, detail, *, stage="interpretation"):
        self.manifest.requirements.append({"source": span.basis.source_id,
            "occurrence": span.basis.occurrence_id, "start": span.start, "end": span.end,
            "line": self.line(span), "reason": reason, "detail": detail, "stage": stage})

    def defer(self, span, reason, detail):
        self.diagnose(span, reason, detail)
        raise _DeferredCommand

    def _preserve_remainder(self, checkpoint):
        # Do not concatenate an unread child suffix with its parent's suffix:
        # EOF, comments and possibly unknown catcodes make that an unsafe splice.
        # Roll back the unfinished root operation (including an input/package
        # handoff) and preserve its contiguous original remainder instead.
        start, pieces, tombstones, commands = checkpoint
        root = self._root_reader
        span = root.source_span(start, len(root.text))
        del self.pieces[pieces:]
        del self.tombstones[tombstones:]
        del self.commands[commands:]
        self.pieces.append(SourcePiece(self.raw(span), span, self.line(span),
            "PRESERVE_UNRESOLVED", source_end_line=self.line(
                span.basis.span(max(span.start, span.end - 1), span.end))))
        self.manifest.preserved_source_spans = [{"source": span.basis.source_id,
            "occurrence": span.basis.occurrence_id, "start": span.start, "end": span.end}]
        # Only convert assets whose references survived this emission rollback.
        targets = {p.target for p in self.pieces if p.target is not None}
        self.images = {p for p in self.images if self.name(p) in targets}
        self.manifest.active_images = [i for i in self.manifest.active_images if i.rel_path in targets]
        retained_resources = {(p.command.span.basis.source_id, p.command.span.basis.occurrence_id,
                               p.command.span.start, p.command.span.end)
                              for p in self.pieces if p.command and p.command.action == "external_literal"}
        self.manifest.resources = [r for r in self.manifest.resources
            if (r["source"], r["occurrence"], r["start"], r["end"]) in retained_resources
            or self.store.root / r["source"] in self.styles or self.store.root / r["source"] in self.code]
        payloads = {r.get("payload") for r in self.manifest.resources}
        self.literal_payloads = {path: target for path, target in self.literal_payloads.items() if target in payloads}
        if self.bibliography_pieces is not None:
            retained = {id(p) for p in self.pieces}
            if any(id(p) not in retained for p in self.bibliography_pieces):
                self.bibliography_pieces = None

    def resolve(self, name, suffixes, span, *, directories=None, required=True):
        if not name or Path(name).is_absolute():
            self.fail(span, "dependency_path", f"Expected a project-relative dependency: {name!r}")
        frame = self.frames[-1]
        roots = directories if directories is not None else [frame.import_dir or self.root.parent, self.store.root]
        for directory in dict.fromkeys(roots):
            matches = []
            for suffix in suffixes:
                path = (directory / (name + suffix)).resolve()
                if self.store.contains(path):
                    matches.append(path)
            if len(set(matches)) > 1:
                self.fail(span, "ambiguous_dependency", f"Multiple candidates for {name!r}: {[self.name(p) for p in matches]}")
            if matches:
                return matches[0]
        if required:
            self.fail(span, "missing_dependency", f"Cannot resolve {name!r} in {[self.name(p) for p in roots if p.is_relative_to(self.store.root)]}")
        return None

    def edge(self, command, path, kind):
        self.manifest.dependencies.append({"source": command.span.basis.source_id,
            "occurrence": command.span.basis.occurrence_id, "start": command.span.start,
            "end": command.span.end, "kind": kind, "target": self.name(path)})

    def _enter(self, path, command, *, emit, import_dir=None, package=False, include=False):
        if any(frame.path == path for frame in self.frames):
            chain = " -> ".join(self.name(f.path) for f in self.frames) + " -> " + self.name(path)
            self.fail(command.span, "input_cycle", chain)
        reader = self._reader(path)
        overrides = self.resolver.catalog.engine_bindings["source_traversal"]["reading"]["package_input_catcodes"] if package else None
        recovery = self.dispatcher.input_recovery() if not emit and self.frames[-1].emit else None
        self.frames.append(_Input(path, reader, emit, import_dir, include=include, recovery=recovery))
        self.dispatcher.enter_source(reader, catcode_overrides=overrides)

    def _emit(self, span, text=None, *, command=None, target=None, operation=None, deferred=None):
        if not self.frames[-1].emit:
            return
        raw = self.raw(span)
        text = raw if text is None else text
        if text:
            self.pieces.append(SourcePiece(text, span, self.line(span), operation or
                              ("IDENTITY" if text == raw else "MOUTH_EMISSION"), command, target,
                              self.line(span.basis.span(max(span.start, span.end - 1), span.end)), deferred))

    def _omit(self, span, reason):
        if span.start != span.end:
            self.tombstones.append(Tombstone(span.basis.source_id, self.line(span),
                self.line(span.basis.span(max(span.start, span.end - 1), span.end)), "OMIT", reason))

    def _payload_edit(self, span, replacement):
        path = self.documents[span.basis].path
        edits = self.payload_edits.setdefault(path, {})
        key = (span.start, span.end)
        if key in edits and edits[key] != replacement:
            self.fail(span, "context_dependent_payload", "One local code file resolves differently across occurrences")
        edits[key] = replacement

    def payload_text(self, path):
        text = self.store.document(path).text
        for (start, end), replacement in sorted(self.payload_edits.get(path, {}).items(), reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    def _neutral(self, command):
        # Capturing a bounded header does not require interpreting its contents.
        # Retain the whole header and locate work without dispatching its body.
        for arg in command.arguments:
            for token in arg.tokens:
                if token.kind != TokenKind.CHARACTER or token.catcode in (CatCode.PARAMETER, CatCode.MATH_SHIFT, CatCode.ALIGNMENT_TAB):
                    self.require(token.span, "argument_behavior", "Unexpanded argument token retained inside " + command.name)
        self._deferred_dependencies(t for arg in command.arguments for t in arg.tokens)

    def _deferred_dependencies(self, tokens):
        for token in tokens:
            if token.kind != TokenKind.CONTROL_SEQUENCE:
                continue
            profile = self.resolver.resolve_command(token.value)
            if getattr(profile, "action", None) in {"source_input", "source_include", "source_import",
                    "source_subimport", "asset_reference", "bibliography", "biblatex_resource", "package_load", "external_literal"}:
                self.require(token.span, "deferred_dependency", "Dependency inside an uninterpreted expression requires its owning context",
                             stage="preparation")

    def _package(self):
        frame = self.frames[-1]
        name, options, command, is_class = frame.packages.pop(0)
        key = ("class:" if is_class else "package:") + name
        path = self.resolve(name, [".cls" if is_class else ".sty"], command.span, required=False)
        if key in self.loaded_packages:
            return
        self.loaded_packages.add(key)
        self.manifest.packages_declared.append(PackageUsage(name, options, path is not None, self.name(path) if path else None))
        if path:
            self.edge(command, path, "class" if is_class else "package")
            self.styles[path] = StyleFileInfo(self.name(path), str(path), True, len(self.store.read_bytes(path)))
            self._enter(path, command, emit=False, package=True)
        elif is_class:
            baseline = self.resolver.catalog.engine_bindings["source_traversal"]["reading"]["baseline_classes"]
            if name not in baseline:
                self.require(command.span, "class_binding", f"No reading contract for class {name!r}", stage="binding")
        elif not self.resolver.load_package(name):
            self.require(command.span, "package_binding", f"No reading binding for package {name!r}", stage="binding")

    def _command(self, command):
        frame, action = self.frames[-1], command.action
        self.commands.append(command)
        if action == "external_literal":
            prepare_external_literal(self, command)
            return
        if action in {"transparent_begin", "transparent_end"}:
            role = command.metadata["semantic_role"]
            role_action = self.policy.get_role_action(role)
            if role_action == "unwrap":
                self._omit(command.span, "Policy unwrapped " + role)
                return
            if action == "transparent_begin" and role_action != "preserve":
                self.require(command.span, "policy_action", f"Transparent role does not support {role_action!r}", stage="preparation")
        if action == "environment_begin":
            self._neutral(command)
        if action in {"source_input", "source_include", "source_import", "source_subimport"}:
            self._omit(command.span, "Input directive replaced by its ordered occurrence")
            name = command.value("target")
            imported = frame.import_dir
            if action in {"source_import", "source_subimport"}:
                base = self.root.parent if action == "source_import" else (imported or self.root.parent)
                imported = (base / command.value("directory")).resolve()
                if self.store.is_excluded(imported):
                    self.fail(command.span, "dependency_path", "Import directory is outside source inventory")
            include = action == "source_include"
            if include:
                self._emit(command.span, "\\clearpage ", operation="INCLUDE_BOUNDARY")
                if self.includeonly is not None and name not in self.includeonly:
                    return
            path = self.resolve(name, [""] if Path(name).suffix else [".tex", ""], command.span,
                                directories=[imported] if imported else None)
            self.edge(command, path, "input")
            emit = frame.emit and path.suffix.lower() not in {".sty", ".cls"}
            if not emit:
                self.code.add(path)
                if imported:
                    self.defer(command.span, "package_import", "Import rebasing inside retained local code needs a payload contract")
                replacement = "\\include{" + self.name(path.with_suffix("")) + "}" if include else "\\input{" + self.name(path) + "}"
                if frame.emit:
                    self._emit(command.span, replacement, operation="REBASE_CODE_INPUT")
                else:
                    self._payload_edit(command.span, replacement)
            self._enter(path, command, emit=emit, import_dir=imported, include=include and emit)
            return
        if action == "end_input":
            self._omit(command.span, "Endinput resolved at physical-line boundary")
            return  # Dispatcher already scheduled this file's physical-line EOF.
        if action == "include_selection":
            self.includeonly = {s.strip() for s in command.value("names").split(",")}
            return
        if action == "bibliography":
            if self.bibliography_context is not None:
                self.defer(command.span, "bibliography_sites", "Multiple bibliography sites need separate preparation")
            self._neutral(command)
            self._emit(command.span, command=command)
            self.bibliography_context = self.context.copy()
            self.bibliography_knowledge = BindingResolver(self.resolver.catalog)
            self.bibliography_knowledge.active_packages = list(self.resolver.active_packages)
            bbl = self.root.with_suffix(".bbl")
            if self.store.contains(bbl):
                self.edge(command, bbl, "formatted_bibliography")
                self._enter(bbl, command, emit=frame.emit, import_dir=frame.import_dir)
                self.frames[-1].bibliography_start = len(self.pieces)
            return
        if action in {"package_load", "document_class"}:
            name = command.value("name")
            options = [s.strip() for s in command.value("options").split(",") if s.strip()]
            names = [s.strip() for s in name.split(",")]
            frame.packages.extend((n, options, command, action == "document_class") for n in names)
            # Rebase local names because master.tex moves to the payload root.
            resolved_names = []
            for n in names:
                p = self.resolve(n, [".cls" if action == "document_class" else ".sty"], command.span, required=False)
                resolved_names.append(self.name(p.with_suffix("")) if p else n)
            arg = command.argument("name")
            raw = self.raw(command.span)
            a, b = arg.span.start - command.span.start, arg.span.end - command.span.start
            replacement = raw[:a] + ",".join(resolved_names) + raw[b:]
            if frame.emit:
                self._emit(command.span, replacement, command=command)
            else:
                self._payload_edit(command.span, replacement)
            return
        if action == "asset_reference":
            self._neutral(command)
            # Widths/captions can contain unexpanded TeX without making the
            # filename or PDF page computed. Inspect only options we consume.
            options = key_values(command.argument("options"))
            if options.get("page", "1").strip() != "1":
                self.defer(command.span, "asset_page", "Only first-page PDF conversion is currently qualified")
            if not frame.emit:
                self.defer(command.span, "package_asset", "Asset emission from local package code needs a payload rewrite contract")
            name = command.value("target")
            paths = next((self.graphic_paths[d] for d in sorted(self.graphic_paths, reverse=True) if d <= self.context.scope_depth), [])
            exts = next((self.graphic_extensions[d] for d in sorted(self.graphic_extensions, reverse=True) if d <= self.context.scope_depth), sorted(IMAGE_EXTENSIONS))
            path = self.resolve(name, [""] if Path(name).suffix else exts, command.span,
                                directories=[frame.import_dir or self.root.parent, self.store.root, *paths])
            self.images.add(path)
            for candidate in self._implicit:
                candidate[1] = True
            self.edge(command, path, "asset")
            self._emit(command.span, command=command, target=self.name(path))
            return
        if action == "asset_search_paths":
            paths, current, depth = [], [], 0
            for token in command.argument("directories").tokens:
                if token.catcode == CatCode.BEGIN_GROUP and depth == 0:
                    depth = 1
                elif token.catcode == CatCode.END_GROUP and depth == 1:
                    paths.append((self.root.parent / "".join(current)).resolve())
                    current, depth = [], 0
                elif depth == 1 and token.kind == TokenKind.CHARACTER and token.catcode not in {CatCode.BEGIN_GROUP, CatCode.END_GROUP}:
                    current.append(token.value)
                elif not (depth == 0 and token.catcode == CatCode.SPACE):
                    self.defer(token.span, "graphics_paths", "Expected literal directory groups")
            if depth:
                self.fail(command.span, "graphics_paths", "Unclosed directory group")
            self.graphic_paths[self.context.scope_depth] = paths
        elif action == "asset_extensions":
            self.graphic_extensions[self.context.scope_depth] = [s.strip() for s in command.value("extensions").split(",")]
        elif action == "environment_begin" and command.metadata.get("implicit"):
            self._implicit.append([command, False])
        elif action == "environment_end" and command.metadata.get("implicit"):
            opening, has_image = self._implicit.pop()
            if not has_image:
                self.manifest.implicit_graphics.append(ImplicitGraphicInfo(opening.metadata["implicit"],
                    opening.metadata["category"], opening.span.basis.source_id, self.line(opening.span),
                    opening.metadata.get("floating", False), False, self.raw(opening.span), opening.name))
        elif action in {"opaque", "metadata", "citation", "bibliography", "bibliography_style", "biblatex_resource", "biblatex_print"}:
            self._neutral(command)
        self._emit(command.span, command=command)
        if action == "environment_end" and command.metadata.get("document"):
            self._ended_document = True
        # No-argument commands need a lexical separator after a control word.
        if not command.arguments and action in {"opaque", "biblatex_print"}:
            self._emit(command.span.basis.span(command.span.end, command.span.end), " ")

    def run(self):
        if self._ran:
            raise RuntimeError("Preparation sessions are single-use")
        self._ran = True
        self._checkpoint = (0, 0, 0, 0)
        try:
            self._traverse()
        except _PreserveRemainder:
            self._preserve_remainder(self._checkpoint)
        self.coverage = {basis: ReadingCoverage(basis, items) for basis, items in self._observations.items()}
        for basis, coverage in self.coverage.items():
            # Mouth events may leave trimmed physical-line suffixes unobserved;
            # retain those gaps explicitly instead of fabricating mappings.
            self.manifest.input_occurrences[basis.occurrence_id]["unobserved"] = [
                [s.start, s.end] for s in coverage.unknown]
        self._inventory()
        self.manifest.source_survey = survey_sources(self.store, self.resolver.catalog)
        self.manifest.source_reads = list(self.store.read_paths)
        return self

    def _traverse(self):
        while self.frames and not self._ended_document:
            if self.frames[-1].packages:
                self._package()
                continue
            if len(self.frames) == 1 and self.dispatcher.reader is self._root_reader:
                self._checkpoint = (self.frames[0].reader.position, len(self.pieces),
                                    len(self.tombstones), len(self.commands))
            item = self.dispatcher.next_item()
            if item is None:
                break
            if isinstance(item, ReadingBoundary):
                # An EOF diagnostic can point to an opener in another input.
                # Keep that anchor in diagnostics; do not misattribute coverage.
                if len(self.frames) == 1:
                    start, pieces, tombstones, commands = self._checkpoint
                    self._checkpoint = (min(start, item.remainder.start), pieces, tombstones, commands)
                self.diagnose(item.span, item.reason, item.detail)
                recoverable = next((i for i, frame in enumerate(self.frames) if frame.recovery is not None), None)
                if recoverable is not None:
                    frame = self.frames[recoverable]
                    self.require(item.span, "retained_code_reading",
                        f"Retained {self.name(frame.path)!r}; caller resumes with its entry reading state. "
                        "This file's reading effects and dependencies still require resolution.", stage="preparation")
                    self.dispatcher.resume_input(frame.recovery)
                    del self.frames[recoverable:]
                    continue
                raise _PreserveRemainder
            self._observations[item.span.basis].append(item)
            if isinstance(item, SourceEnd):
                self._omit(item.span, "Unread remainder after endinput")
                finished = self.frames.pop()
                if finished.bibliography_start is not None:
                    self.bibliography_pieces = self.pieces[finished.bibliography_start:]
                if finished.include and self.frames:
                    self._emit(item.span, "\\clearpage ", operation="INCLUDE_BOUNDARY")
                continue
            try:
                if isinstance(item, SourceCommand):
                    checkpoint = (len(self.pieces), len(self.tombstones))
                    self._command(item)
                elif isinstance(item, DeferredRegion):
                    self.require(item.span, item.reason, item.detail,
                                 stage="preparation" if item.reason == "package_not_loaded" else "interpretation")
                    self._deferred_dependencies(item.tokens)
                    raw = self.raw(item.span)
                    # A bare control word needs a separator after mouth-discarded
                    # whitespace. Protected groups and math remain exact slices.
                    if (len(item.tokens) == 1 and item.tokens[0].kind == TokenKind.CONTROL_SEQUENCE
                            and item.span.end == item.tokens[0].span.end):
                        raw += " "
                    self._emit(item.span, raw, operation="DEFER_INTERPRETATION", deferred=item)
                elif isinstance(item, ReadEvent):
                    text = event_text(item, self.raw(item.span))
                    self._emit(item.span, text)
                    if not text:
                        self._omit(item.span, "Mouth discarded comment, spacing or ignored character")
                elif isinstance(item, SkippedRegion):
                    self._omit(item.span, "Inactive conditional branch")
                elif isinstance(item, LiteralRegion) and item.classification:
                    for detail in item.warnings:
                        self.manifest.warnings.append({"source": item.span.basis.source_id,
                            "start": item.closing.start, "end": item.closing.end,
                            "line": self.line(item.closing), "detail": detail})
                    action = self.policy.get_role_action(item.classification.semantic_role)
                    if action == "eliminate":
                        self._omit(item.span, "Policy eliminated " + item.classification.semantic_role)
                    else:
                        self._emit(item.span)
                        if action != "preserve":
                            self.require(item.span, "policy_action", f"Literal role does not support {action!r}", stage="preparation")
                else:
                    self._emit(item.span)
                    if isinstance(item, StoredDefinition) and self.frames[-1].path in self.styles:
                        self.styles[self.frames[-1].path].declared_commands.append(item.target.value)
            except (ReadingIssue, _DeferredCommand) as error:
                if isinstance(error, ReadingIssue):
                    self.diagnose(item.span, error.reason, error.detail)
                # Only undo the current command's attempted emission. Previous
                # children and subsequent source remain part of the new master.
                del self.pieces[checkpoint[0]:]
                del self.tombstones[checkpoint[1]:]
                self._emit(item.span, command=item, operation="DEFER_RESOLUTION")
            depth = self.context.scope_depth
            self.graphic_paths = {k: v for k, v in self.graphic_paths.items() if k <= depth}
            self.graphic_extensions = {k: v for k, v in self.graphic_extensions.items() if k <= depth}
        if self._ended_document:
            for frame in self.frames:
                remainder = frame.reader.source_span(frame.reader.position, len(frame.reader.text))
                self._observations[remainder.basis].append(SourceEnd(remainder, "end_document"))
                self._omit(remainder, "Unread remainder after end of document")

    def _inventory(self):
        m = self.manifest
        m.active_tex_files = sorted(self.name(p) for p in self.active if p.suffix.lower() == ".tex")
        m.local_styles = list(self.styles.values())
        m.code_inputs = sorted(self.name(p) for p in self.code)
        m.active_images = [characterize_image(self.name(p), str(p)) for p in sorted(self.images)]
        for path in self.store.files:
            if path not in self.active and path not in self.images:
                if m.unresolved or m.requirements:
                    m.unclassified_files.append(self.name(path))
                    continue
                if path.suffix.lower() == ".tex":
                    m.dormant_tex_files.append(self.name(path))
                elif path.suffix.lower() in {".sty", ".cls"}:
                    m.dormant_styles.append(self.name(path))
                elif path.suffix.lower() in IMAGE_EXTENSIONS:
                    m.dormant_images.append(self.name(path))
        bib = m.bibliography
        actions = {c.action for c in self.commands}
        bib.kind = "BIBLATEX" if actions & {"biblatex_resource", "biblatex_print"} else "CLASSIC_BIBTEX" if "bibliography" in actions else "NONE"
        bib.backend = "bibtex" if bib.kind == "CLASSIC_BIBTEX" else "biber" if bib.kind == "BIBLATEX" else None
        bbl = self.root.with_suffix(".bbl")
        bib.bbl_exists = self.store.contains(bbl)
        bib.bbl_path = str(bbl) if bib.bbl_exists else None
        bib.bbl_needed = "bibliography" in actions and not bib.bbl_exists
        m.implicit_graphics_count = len(m.implicit_graphics)
        m.has_implicit_graphics = bool(m.implicit_graphics)
        m.source_reads = list(self.store.read_paths)
        m.source_dependency_closure = "unresolved" if m.unresolved or any(
            r["stage"] == "preparation" for r in m.requirements) else "complete"
        m.dependency_closure = "unresolved" if m.unresolved or m.requirements else "complete"
