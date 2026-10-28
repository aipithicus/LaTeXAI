"""One cached, ordered traversal owns dependency discovery and master assembly.

The dispatcher owns TeX execution routing. This owner supplies input occurrences,
resolves declared resources and records emissions. It does not expand macros or
fall back to raw-text dependency searches at an unresolved reading boundary.
"""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from pathlib import Path
import re

from ..source_io import SourceStore
from ..assets import IMAGE_EXTENSIONS, characterize_image
from ..bindings.resolver import BindingResolver
from ..reading.dispatcher import StructuralDispatcher, InputRecovery
from ..reading.argument_scanner import key_values
from ..reading.coverage import ReadingCoverage
from ..reading.contracts import (SourceCommand, SourceEnd, ReadingBoundary, ReadingIssue, TokenArgument,
                                StoredDefinition, CommandDefinition, EnvironmentDefinition, CollectedEnvironment,
                                SkippedRegion, DeferredRegion, LiteralRegion, ConditionalRegion, ScannedArgument)
from ..reading.dependencies import observe_dependencies, DEPENDENCY_ACTIONS
from ..reading.tex_reader import TexReader, ReadEvent, TokenKind, CatCode
from ..reading.edit_map import EditMap
from ..reading.units import UnitRegistry
from ..reading.options import OptionScope, option_names
from ..reading.spans import SourceSpan
from .discovery import select_root
from .emission import SourcePiece, MouthEmitter
from .survey import survey_sources
from .policy import load_policy
from .lint import PreparationLint
from .resources import prepare_external_literal
from .assets import observe_environment_assets, observe_asset, parse_asset_use, surviving_asset_uses
from .deferred import emit_observed_region
from .preservation import retain_candidate_input, retain_source, retain_survey_inputs
from .provenance import Tombstone
from .manifest import PreflightManifest, BibliographyInfo, PackageUsage, StyleFileInfo, ImplicitGraphicInfo
from .records import source_reference, pending_location
from ..reading.effect_summary import EffectSummary


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
    replacement: SourceSpan | None = None
    emission_start: int = 0
    command: SourceCommand | None = None
    tombstone_start: int = 0
    command_start: int = 0


@dataclass(slots=True)
class _ImplicitGraphic:
    opening: SourceCommand
    has_image: bool = False


class PreparationSession:
    def __init__(self, project_dir: Path, *, root_tex=None, excluded_dirs=(), engine="pytexml", catalog=None, policy="prepare"):
        self.policy = load_policy(policy)
        self.emitter = MouthEmitter(self.policy)
        self.store = SourceStore(project_dir, excluded_dirs)
        self.resolver = BindingResolver(catalog)
        self.root = select_root(self.store, root_tex, catalog=self.resolver.catalog)
        self.context = self.resolver.new_context()
        self.literal_payloads = {}
        self.manifest = PreflightManifest(self.name(self.root), self.root.stem, str(self.store.root), engine,
            BibliographyInfo("NONE", None, None, False, False))
        self.lint = PreparationLint(self.policy.linting)
        self.manifest.lint = self.lint.report
        self.pieces: list[SourcePiece] = []
        self.tombstones = []
        self.frames: list[_Input] = []
        self.active: set[Path] = set()
        self.styles: dict[Path, StyleFileInfo] = {}
        self.images: set[Path] = set()
        self.candidate_images: set[Path] = set()
        self.asset_uses = {}
        self.candidate_sources: set[Path] = set()
        self._implicit: list[_ImplicitGraphic] = []
        self.code: set[Path] = set()
        self.retained_search_dirs: dict[Path, set[Path]] = {}
        self.payload_edits: dict[Path, dict[tuple[int, int], str]] = {}
        self.commands: list[SourceCommand] = []
        self.documents = {}
        self.readers = {}
        self.generated_sources = {}
        self.units = UnitRegistry()
        self.line_starts = {}
        self.loaded_packages: set[str] = set()
        self.package_options: dict[str, tuple[str, ...]] = {}
        self.forwarded_options: dict[str, tuple[str, ...]] = {}
        self.class_options: tuple[str, ...] = ()
        self.graphic_paths: dict[int, list[Path]] = {}
        self.graphic_extensions: dict[int, list[str]] = {}
        self.includeonly: set[str] | None = None
        self.bibliography_pieces = None
        self.bibliography_context = None
        self.bibliography_knowledge = None
        self.bibliography_observed = False
        self.bibliography_may_skip = False
        self._ran = False
        self._ended_document = False
        self._observations = {}
        self.coverage = {}
        first = self.open_source(self.root)
        self._root_reader = first
        self.frames.append(_Input(self.root, first, True))
        self.dispatcher = StructuralDispatcher(first, self.context, self.resolver,
            source_commands=True, preparation=True, units=self.units)
        self.manifest.reading_assumptions = [
            "Source-visible preparation does not generally expand manuscript macros; bounded reading predicates may resolve captured single-token constants. Unbound commands and packages are not assumed to generate inputs or change entry catcodes.",
            "Uninterpreted math, environments and adjacent command groups retain their source; their contents are not executed.",
            "Bounded predicate substitution uses current captured single-token constants; hidden redefinitions by unbound expressions are not inferred. Definitions observed in unresolved conditionals invalidate prior meanings."]

    def name(self, path):
        return path.relative_to(self.store.root).as_posix()

    def pending_units(self):
        """Inventory/failure output has identities, but no finalized artifact yet."""
        self.manifest.uncertainty_causes = [
            {"id": cause.id, **source_reference(self.units.records[cause.unit_id]),
             "reason": cause.reason, "detail": cause.detail, **pending_location()}
            for cause in self.units.uncertainty.values()]
        self.manifest.reset_locations(self.units.records.values())
        self.manifest.conditional_decisions = list(self.dispatcher.decisions)

    def open_source(self, path):
        """Open a new occurrence from cached text and register its provenance."""
        doc = self.store.document(path)
        occurrence = len(self.manifest.input_occurrences)
        reader = TexReader(doc.text, source_id=doc.name, occurrence_id=occurrence,
                           catcodes=self.context.catcodes, endline_char=self.context.endlinechar)
        self.register_reader(path, reader)
        return reader

    def register_reader(self, path, reader, *, candidate=False, parent=None):
        doc = self.store.document(path)
        self.documents[reader.basis] = doc
        self.readers[reader.basis] = reader
        self._observations[reader.basis] = []
        if path not in self.line_starts:
            self.line_starts[path] = [0] + [m.end() for m in re.finditer(r"\r\n|\r|\n", doc.text)]
        (self.candidate_sources if candidate else self.active).add(path)
        occurrence = {"id": reader.basis.occurrence_id, "source": doc.name,
            "activity": "unresolved" if candidate else "reached",
            "parent": parent if candidate else self.frames[-1].reader.basis.occurrence_id if self.frames else None}
        if candidate:
            occurrence["activation"] = "unresolved"
        self.manifest.input_occurrences.append(occurrence)

    def observe(self, item):
        """Record coverage only against an already registered occurrence."""
        self._observations[item.span.basis].append(item)

    def previous_observation(self, basis):
        items = self._observations[basis]
        return items[-1] if items else None

    def register_generated_source(self, reader):
        self.generated_sources[reader.basis] = reader.text
        self.manifest.input_occurrences.append({"id": reader.basis.occurrence_id,
            "source": reader.basis.source_id, "parent": None, "generated": True})

    def line(self, span):
        if span.basis in self.generated_sources:
            return 1 + len(re.findall(r"\r\n|\r|\n", self.generated_sources[span.basis][:span.start]))
        return bisect_right(self.line_starts[self.documents[span.basis].path], span.start)

    def raw(self, span):
        return self.documents[span.basis].text[span.start:span.end]

    def diagnose(self, span, reason, detail, *, unit_id=None, dependency="none", materialization=None, evidence=None, causes=()):
        unit_id = unit_id or self.units.add(span, "diagnostic")
        self.units.require(unit_id, span)
        diagnostic = self.manifest.add_diagnostic(self.units.records[unit_id], self.line(span), reason, detail,
                                                  dependency=dependency, materialization=materialization)
        self.link_causes(diagnostic, causes)
        self.lint.record(self.units.records[unit_id], self.line(span), reason, detail, evidence=evidence)
        return diagnostic

    def fail(self, span, reason, detail):
        diagnostic = self.diagnose(span, reason, detail, dependency="required")
        raise PreparationUnresolved(f"{diagnostic['source']}:{diagnostic['line']} [{reason}] {detail}")

    def require(self, span, reason, detail, *, stage="interpretation", unit_id=None, parent_id=None,
                materialization=None, activity=None, dependency=None, next_step=None, causes=()):
        unit_id = unit_id or self.units.add(span, "requirement_target", parent_id, activity=activity)
        self.units.require(unit_id, span)
        record = self.manifest.add_requirement(self.units.records[unit_id], self.line(span), reason, detail,
            stage=stage, dependency=dependency, materialization=materialization, next_step=next_step)
        self.link_causes(record, causes)
        return record

    def link_causes(self, record, spans):
        if spans:
            record["cause_ids"] = list(dict.fromkeys(self.units.uncertainty_cause(span).id for span in spans))

    def defer(self, span, reason, detail, *, evidence=None):
        self.diagnose(span, reason, detail, evidence=evidence)
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
                span.basis.span(max(span.start, span.end - 1), span.end)), mapping=EditMap.copied(span)))
        self.manifest.preserved_source_spans = [{"source": span.basis.source_id,
            "occurrence": span.basis.occurrence_id, "start": span.start, "end": span.end}]
        # Only convert assets whose references survived this emission rollback.
        surviving = self.surviving_assets(self.pieces)
        identifiers = {u.command.unit_id for u in surviving}
        targets = {self.name(u.path) for u in surviving}
        self.images = {p for p in self.images if self.name(p) in targets}
        self.candidate_images = {p for p in self.candidate_images if self.name(p) in targets}
        retained_contexts = {(p.deferred.span.basis.source_id, p.deferred.span.basis.occurrence_id,
                              p.deferred.span.start, p.deferred.span.end)
                             for p in self.pieces if p.deferred is not None}
        self.manifest.candidate_dependencies = [d for d in self.manifest.candidate_dependencies
            if (d["unit_id"] in identifiers if d["kind"] == "asset" else
                (d["source"], d["occurrence"], *d["context_span"]) in retained_contexts)]
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
            retained = {p.key for p in self.pieces}
            if any(p.key not in retained for p in self.bibliography_pieces):
                self.bibliography_pieces = None

    def resolve(self, name, suffixes, span, *, directories=None, required=True, provisional=False):
        def problem(reason, detail):
            if provisional:
                raise ReadingIssue(reason, detail)
            self.fail(span, reason, detail)

        if not name or Path(name).is_absolute():
            problem("dependency_path", f"Expected a project-relative dependency: {name!r}")
        frame = self.frames[-1]
        roots = directories if directories is not None else [frame.import_dir or self.root.parent, self.store.root]
        for directory in dict.fromkeys(roots):
            matches = []
            for suffix in suffixes:
                path = (directory / (name + suffix)).resolve()
                if self.store.contains(path):
                    matches.append(path)
            if len(set(matches)) > 1:
                problem("ambiguous_dependency", f"Multiple candidates for {name!r}: {[self.name(p) for p in matches]}")
            if matches:
                return matches[0]
        if required:
            problem("missing_dependency", f"Cannot resolve {name!r} in {[self.name(p) for p in roots if p.is_relative_to(self.store.root)]}")
        return None

    def edge(self, command, path, kind):
        self.manifest.dependencies.append({**source_reference(self.units.records[command.unit_id]),
                                           "kind": kind, "target": self.name(path)})

    def _enter(self, path, command, *, emit, import_dir=None, package=False, include=False, options=None):
        if any(frame.path == path for frame in self.frames):
            chain = " -> ".join(self.name(f.path) for f in self.frames) + " -> " + self.name(path)
            self.fail(command.span, "input_cycle", chain)
        reader = self.open_source(path)
        overrides = self.resolver.catalog.engine_bindings["source_traversal"]["reading"]["package_input_catcodes"] if package else None
        recovery = self.dispatcher.input_recovery()
        self.frames.append(_Input(path, reader, emit, import_dir, include=include, recovery=recovery,
            replacement=command.span if emit and command.action != "bibliography" else None,
            emission_start=len(self.pieces), command=command,
            tombstone_start=len(self.tombstones), command_start=len(self.commands)))
        self.dispatcher.enter_source(reader, catcode_overrides=overrides, options=options)

    def emit(self, span, text=None, *, command=None, target=None, operation=None, deferred=None,
              image_references=(), source_edits=()):
        """Append an edit-aware piece only while the current input is inlined."""
        if not self.frames[-1].emit:
            return
        raw = self.raw(span)
        text = raw if text is None else text
        if raw and text == raw + " " and not source_edits:
            self.emit(span, command=command, target=target, operation=operation, deferred=deferred,
                       image_references=image_references)
            self.emit(span.basis.span(span.end, span.end), " ", operation="SYNTHETIC_SEPARATOR")
            return
        if text or operation in {"SOURCE_END", "LINT_REPAIR"}:
            piece = SourcePiece(raw if source_edits else text, span, self.line(span), operation or
                              ("IDENTITY" if text == raw else "MOUTH_EMISSION"), command,
                              ((command, target),) if target is not None else image_references,
                              self.line(span.basis.span(max(span.start, span.end - 1), span.end)), deferred,
                              EditMap.copied(span) if text == raw or source_edits else EditMap.replaced(span, len(text)))
            for target_span, replacement in source_edits:
                piece = piece.edit_source(target_span, replacement, operation or "REWRITE_REFERENCE")
            if piece.text != text:
                raise ValueError("Declared emission edits do not produce the emitted text")
            self.pieces.append(piece)
            return piece

    def link_replacement(self, start, original):
        """Link every piece emitted for an insertion to its original command."""
        for i in range(start, len(self.pieces)):
            piece = self.pieces[i]
            self.pieces[i] = replace(piece, replaces=piece.replaces + (original,))

    def omit(self, span, reason):
        if span.start != span.end:
            self.tombstones.append(Tombstone(span.basis.source_id, span.start, span.end, "OMIT", reason,
                occurrence=span.basis.occurrence_id,
                source_lines=(self.line(span), self.line(span.basis.span(span.end - 1, span.end)))))

    def _emit_event(self, event):
        if not self.frames[-1].emit:
            return  # Separately retained local code has no normalization contract.
        result = self.emitter.emit(event, self.documents[event.span.basis].text)
        self.emit(result.kept_span or event.span, result.text)
        if result.suffix:
            self.emit(event.span.basis.span(event.span.end, event.span.end), result.suffix,
                       operation="SYNTHETIC_COMMENT_END")
        if not result.text or result.kept_span is not None:
            self.omit(event.span, "Mouth/policy discarded comment, spacing or ignored character")
        if result.metadata:
            identifier = self.units.add(event.span, "source_metadata", activity="data",
                                        evidence={"reason": "reader_comment"})
            self.manifest.source_metadata.append({"unit_id": identifier, **result.metadata})

    def edit_payload(self, span, replacement):
        """Keep one edit per retained-file range, rejecting occurrence conflicts."""
        path = self.documents[span.basis].path
        edits = self.payload_edits.setdefault(path, {})
        key = (span.start, span.end)
        if key in edits and edits[key] != replacement:
            self.fail(span, "context_dependent_payload", "One local code file resolves differently across occurrences")
        edits[key] = replacement

    def register_asset(self, command, path):
        use = parse_asset_use(command, path)
        self.asset_uses[command.unit_id] = use
        return use

    def surviving_assets(self, pieces):
        retained = set(self.styles) | self.code
        bases = {basis for basis, doc in self.documents.items() if doc.path in retained}
        return surviving_asset_uses(self.asset_uses.values(), pieces, retained_bases=bases)

    def rebase_asset_payloads(self, uses, mapping):
        """Apply converted asset references to retained code, checking occurrences."""
        retained = set(self.styles) | self.code
        for use in uses:
            if self.documents[use.command.span.basis].path in retained:
                for span, replacement in use.edits(mapping[use.command.unit_id]):
                    self.edit_payload(span, replacement)

    def payload_text(self, path):
        text = self.store.document(path).text
        for (start, end), replacement in sorted(self.payload_edits.get(path, {}).items(), reverse=True):
            text = text[:start] + replacement + text[end:]
        return text

    def payload_piece(self, path, basis):
        piece = SourcePiece(self.store.document(path).text, basis.whole, 1)
        for (start, end), replacement in sorted(self.payload_edits.get(path, {}).items(), reverse=True):
            piece = piece.edit_source(basis.span(start, end), replacement, "REBASE_PAYLOAD")
        return piece

    def capture_bibliography(self, *, observed=False, knowledge=None, may_skip=False):
        """Freeze reading knowledge at the accepted bibliography site."""
        self.bibliography_context = self.context.copy()
        if knowledge is None:
            knowledge = BindingResolver(self.resolver.catalog)
            knowledge.active_packages = list(self.resolver.active_packages)
        self.bibliography_knowledge = knowledge
        self.bibliography_observed = observed
        self.bibliography_may_skip = may_skip

    def finish_bibliography(self, start):
        self.bibliography_pieces = self.pieces[start:]

    def discard_bibliography(self, pieces):
        """Retract an inserted BBL while retaining its original declaration."""
        inserted = {p.key for p in self.bibliography_pieces or ()}
        self.bibliography_pieces = None
        return [p for p in pieces if p.key not in inserted]

    def _neutral(self, command):
        # Capturing a bounded header does not require interpreting its contents.
        # Retain the whole header and locate work without dispatching its body.
        for arg in command.arguments:
            identifier = command.metadata.get("argument_units", {}).get(arg.name, command.unit_id)
            if arg.role in {"data", "diagnostic"}:
                if arg.role == "diagnostic" and any(t.kind in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER} for t in arg.tokens):
                    self.require(arg.span, "diagnostic_expansion", "Diagnostic expansion is deferred; these tokens are not dispatched as manuscript commands",
                        unit_id=identifier if self.units.records[identifier].span == arg.span else None,
                        parent_id=command.unit_id, activity="data", next_step="diagnostic_expansion")
                continue
            if any(t.kind != TokenKind.CHARACTER or t.catcode in (CatCode.PARAMETER, CatCode.MATH_SHIFT, CatCode.ALIGNMENT_TAB)
                   for t in arg.tokens):
                self.require(arg.span, "argument_behavior", "Captured argument retained inside " + command.name,
                    unit_id=identifier if self.units.records[identifier].span == arg.span else None,
                    parent_id=command.unit_id, activity="stored" if arg.role == "stored" else "unresolved",
                    next_step="macro_invocation" if arg.role == "stored" else "argument_behavior")
            self._observe_argument(arg, identifier)

    def _observe_argument(self, argument, parent_id, *, excluded=()):
        observations = observe_dependencies(argument,
                self.documents[argument.span.basis].text, self.context, self.resolver,
                self.units, parent_id, excluded=excluded)
        search_changed = False
        for token, identifier, action, role, command in sorted(observations, key=lambda item: item[0].span.start):
            if action in {"asset_search_paths", "asset_extensions"}:
                search_changed = True
                continue
            if command is not None and action == "asset_reference":
                observe_asset(self, command, argument.span, "argument_" + role,
                              binding=command.metadata.get("binding_id"), search_changed=search_changed)
                continue
            requirement = self.require(token.span, "deferred_dependency", "Possible dependency; its owning context has not dispatched this request",
                stage="interpretation" if role == "stored" else "preparation", unit_id=identifier,
                dependency="possible", next_step="macro_invocation" if role == "stored" else
                    "branch_selection" if role == "branch" else "argument_behavior")
            retain_candidate_input(self, command, argument.span, requirement)
            if action in {"package_load", "document_class"} and role != "stored":
                self.dispatcher.loads.invalidate(identifier)

    def require_deferred_dependencies(self, tokens, *, observed=(), observations=(), parent_id=None, command=None, role="unknown"):
        starts = {command.span.start for command in observed}
        envelopes = sorted((o.command for o in observations if o.command is not None), key=lambda c: c.span.start)
        if envelopes:
            for header in envelopes:
                if header.action in DEPENDENCY_ACTIONS and header.span.start not in starts:
                    self.require(header.span, "deferred_dependency", "Possible dependency in a retained source region",
                        stage="preparation", unit_id=header.unit_id, dependency="possible",
                        next_step="branch_selection" if role == "branch" else "argument_behavior")
                    if header.action in {"package_load", "document_class"}:
                        self.dispatcher.loads.invalidate(header.unit_id)
                for arg in header.arguments:
                    self._observe_argument(arg, header.unit_id)
            # Known headers were captured with their argument roles. Do not
            # rediscover their flattened argument tokens as free-standing code.
        if observations:
            spans = sorted((o.span for o in observations), key=lambda s: s.start)
            positions = [s.start for s in spans]
            tokens = tuple(t for t in tokens if (i := bisect_right(positions, t.span.start) - 1) < 0
                           or t.span.start >= spans[i].end)
        if command is not None:
            for arg in command.arguments:
                self._observe_argument(arg, command.metadata.get("argument_units", {}).get(arg.name, parent_id), excluded=starts)
        else:
            tokens = tuple(tokens)
            if tokens:
                span = tokens[0].span.basis.span(tokens[0].span.start, tokens[-1].span.end)
                self._observe_argument(ScannedArgument("captured", span, tokens, role), parent_id, excluded=starts)

    def image_path(self, command, *, provisional=False):
        """Resolve the literal image header against the current search context."""
        name = command.value("target")
        paths = next((self.graphic_paths[d] for d in sorted(self.graphic_paths, reverse=True)
                      if d <= self.context.scope_depth), [])
        exts = next((self.graphic_extensions[d] for d in sorted(self.graphic_extensions, reverse=True)
                     if d <= self.context.scope_depth), sorted(IMAGE_EXTENSIONS))
        frame = self.frames[-1]
        return self.resolve(name, [""] if Path(name).suffix else exts, command.span,
            directories=[frame.import_dir or self.root.parent, self.store.root, *paths], provisional=provisional)

    def _package(self):
        frame = self.frames[-1]
        name, options, command, is_class = frame.packages.pop(0)
        key = ("class:" if is_class else "package:") + name
        options = list(self.forwarded_options.get(key, ())) + options
        path = self.resolve(name, [".cls" if is_class else ".sty"], command.span, required=False)
        if key in self.loaded_packages:
            if not set(options) <= set(self.package_options[key]):
                first_id = self.dispatcher.loads.loaded[("class" if is_class else "package", name)]
                self.diagnose(command.span, "option_clash", f"{name!r} was already requested with different options",
                    unit_id=command.unit_id, evidence={"target": name, "kind": "class" if is_class else "package",
                        "initial_options": list(self.package_options[key]), "requested_options": options,
                        "added_options": sorted(set(options) - set(self.package_options[key])),
                        "comparison": "source_visible_requests", "automatic_repair": False,
                        "related": [self.lint.related(self.units.records[first_id])]})
                self.dispatcher.defer_effects(command.span, reason="option_clash", detail="Package/class options conflict with an earlier load")
            return
        self.loaded_packages.add(key)
        self.dispatcher.loads.record("class" if is_class else "package", name, command.unit_id)
        self.package_options[key] = tuple(options)
        usage = PackageUsage(name, options, path is not None, self.name(path) if path else None,
                             unit_id=command.unit_id, binding_available=name in self.resolver.catalog.package_bindings)
        self.manifest.packages_declared.append(usage)
        if path:
            # Source location and binding availability are independent. A local
            # copy still requests the named package's reading knowledge. Continue
            # scanning its source for author definitions and visible dependencies.
            if not is_class:
                usage.binding_activated = self.resolver.load_package(name)
            self.edge(command, path, "class" if is_class else "package")
            self.styles[path] = StyleFileInfo(self.name(path), str(path), True, len(self.store.read_bytes(path)))
            self._enter(path, command, emit=False, package=True,
                        options=OptionScope(key, tuple(options), self.class_options, is_class, self.context.scope_depth))
        elif is_class:
            baseline = self.resolver.catalog.engine_bindings["source_traversal"]["reading"]["baseline_classes"]
            if name not in baseline:
                self.require(command.span, "class_binding", f"No reading contract for class {name!r}", stage="binding", unit_id=command.unit_id)
                self.dispatcher.defer_effects(command.span, reason="class_binding", detail=f"No reading contract for class {name!r}")
        elif not self.resolver.load_package(name):
            self.require(command.span, "package_binding", f"No reading binding for package {name!r}", stage="binding", unit_id=command.unit_id)
            self.dispatcher.defer_effects(command.span, reason="package_binding", detail=f"No reading binding for package {name!r}")
        else:
            usage.binding_activated = True
            effects = self.resolver.catalog.package_bindings[name].get("reading", {}).get("load_effects")
            if effects is not None:
                summary = EffectSummary.parse(effects["summary"]) if "summary" in effects else None
                if summary is not None and effects["optional_inputs"]:
                    summary = summary.union(EffectSummary.unknown("Optional input contents/search are unresolved"))
                record = self.require(command.span, "package_load_effects", effects["detail"],
                    stage="binding", unit_id=command.unit_id, dependency="possible" if effects["optional_inputs"] else "none")
                record["evidence"] = {"binding": name, "source_reference": effects["source_reference"],
                    "optional_inputs": [{"name": n, "in_source_inventory": self.store.contains(self.root.parent / n),
                        "external_search": "unresolved"} for n in effects["optional_inputs"]]}
                if summary is not None:
                    record["effect_summary"] = summary.record()
                self.dispatcher.defer_effects(command.span, reason="package_load_effects", detail=effects["detail"], summary=summary)

    def _definition_check(self, unit_id, declaration, target, requirement):
        self.require(self.units.records[unit_id].span, "definition_precondition",
                     f"Captured {declaration} for {target!r}; target must be {requirement}, "
                     "but available reading knowledge cannot verify that", unit_id=unit_id)

    def _command(self, command):
        frame, action = self.frames[-1], command.action
        self.commands.append(command)
        if action == "meaning_assignment" and not command.metadata.get("donor_resolved", False):
            self.require(command.span, "assignment_donor", "Donor meaning needs interpretation; assignment retained without expansion",
                         stage="interpretation", unit_id=command.unit_id)
        for check in command.metadata.get("definition_checks", ()):
            self._definition_check(**check)
        if action == "pass_options":
            name = command.value("name")
            if not name or "," in name:
                self.defer(command.span, "option_target", "Option forwarding requires one literal package/class name")
            key = command.metadata["target_kind"] + ":" + name
            if key in self.loaded_packages:
                first_id = self.dispatcher.loads.loaded[(command.metadata["target_kind"], name)]
                self.defer(command.span, "option_lifecycle",
                    "Option forwarding after the target was loaded requires further resolution",
                    evidence={"target": name, "kind": command.metadata["target_kind"],
                        "requested_options": list(option_names(command.argument("options"))),
                        "automatic_repair": False, "related": [self.lint.related(self.units.records[first_id])]})
            self.forwarded_options[key] = self.forwarded_options.get(key, ()) + option_names(command.argument("options"))
            self.emit(command.span, command=command)
            return
        if action == "external_literal":
            prepare_external_literal(self, command)
            return
        if action == "optional_source_input":
            # Do not equate absence from author files with absence from TeX's
            # search path. Nonempty branches also require ordered execution.
            target = command.value("target")
            path = self.resolve(target, [""] if Path(target).suffix else [".tex", ""], command.span, required=False)
            if path is not None and not any(command.argument(n).tokens for n in ("then", "else")):
                self.commands.pop()
                return self._command(replace(command, action="source_input"))
            self.dispatcher.defer_effects(command.span)
            self.require(command.span, "optional_input_context",
                "Optional input retained: branch execution or external search-path knowledge remains unresolved",
                stage="preparation", unit_id=command.unit_id, dependency="possible")
            self.require_deferred_dependencies((), command=command, parent_id=command.unit_id)
            self.emit(command.span, command=command)
            return
        if action in {"transparent_begin", "transparent_end"}:
            role = command.metadata["semantic_role"]
            role_action = self.policy.get_role_action(role)
            if role_action == "unwrap":
                self.omit(command.span, "Policy unwrapped " + role)
                return
            if action == "transparent_begin" and role_action != "preserve":
                self.require(command.span, "policy_action", f"Transparent role does not support {role_action!r}", stage="preparation", unit_id=command.unit_id)
        if action == "environment_begin":
            self._neutral(command)
        if action in {"source_input", "source_include", "source_import", "source_subimport"}:
            self.omit(command.span, "Input directive replaced by its ordered occurrence")
            name = command.value("target")
            imported = frame.import_dir
            if action in {"source_import", "source_subimport"}:
                base = self.root.parent if action == "source_import" else (imported or self.root.parent)
                imported = (base / command.value("directory")).resolve()
                if self.store.is_excluded(imported):
                    self.fail(command.span, "dependency_path", "Import directory is outside source inventory")
            include = action == "source_include"
            if include:
                self.emit(command.span, "\\clearpage ", operation="INCLUDE_BOUNDARY")
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
                    self.emit(command.span, replacement, operation="REBASE_CODE_INPUT")
                else:
                    self.edit_payload(command.span, replacement)
            self._enter(path, command, emit=emit, import_dir=imported, include=include and emit)
            return
        if action == "end_input":
            self.omit(command.span, "Endinput resolved at physical-line boundary")
            return  # Dispatcher already scheduled this file's physical-line EOF.
        if action == "include_selection":
            self.includeonly = {s.strip() for s in command.value("names").split(",")}
            return
        if action == "bibliography":
            if self.bibliography_context is not None:
                self.defer(command.span, "bibliography_sites", "Multiple bibliography sites need separate preparation")
            self._neutral(command)
            self.emit(command.span, command=command)
            self.capture_bibliography()
            bbl = self.root.with_suffix(".bbl")
            if self.store.contains(bbl):
                self.edge(command, bbl, "formatted_bibliography")
                self._enter(bbl, command, emit=frame.emit, import_dir=frame.import_dir)
                self.frames[-1].bibliography_start = len(self.pieces)
            return
        if action in {"package_load", "document_class"}:
            name = command.value("name")
            options = list(option_names(command.argument("options")))
            if action == "document_class":
                self.class_options = tuple(options)
            names = [s.strip() for s in name.split(",")]
            # Rebase local names because master.tex moves to the payload root.
            resolved_names = []
            for n in names:
                p = self.resolve(n, [".cls" if action == "document_class" else ".sty"], command.span, required=False)
                resolved_names.append(self.name(p.with_suffix("")) if p else n)
            arg = command.argument("name")
            if isinstance(arg, TokenArgument):
                if resolved_names != names:
                    self.defer(command.span, "expanded_package_relocation",
                        "Computed package name needs relocation; its invocation is preserved without a source-argument edit")
                frame.packages.extend((n, options, command, action == "document_class") for n in names)
                self.emit(command.span, command=command)
                if command.metadata["trailing_control_word"]:
                    self.emit(command.span.basis.span(command.span.end, command.span.end), " ", operation="SYNTHETIC_SEPARATOR")
                return
            frame.packages.extend((n, options, command, action == "document_class") for n in names)
            raw = self.raw(command.span)
            a, b = arg.span.start - command.span.start, arg.span.end - command.span.start
            replacement = raw[:a] + ",".join(resolved_names) + raw[b:]
            if frame.emit:
                self.emit(command.span, replacement, command=command,
                           source_edits=((arg.span, ",".join(resolved_names)),))
            else:
                self.edit_payload(arg.span, ",".join(resolved_names))
            return
        if action == "asset_reference":
            self._neutral(command)
            # Widths/captions can contain unexpanded TeX without making the
            # filename or PDF page computed. Inspect only options we consume.
            path = self.image_path(command)
            self.register_asset(command, path)
            self.images.add(path)
            for candidate in self._implicit:
                candidate.has_image = True
            self.edge(command, path, "asset")
            self.emit(command.span, command=command, target=self.name(path))
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
            self._implicit.append(_ImplicitGraphic(command))
        elif action == "environment_end" and command.metadata.get("implicit"):
            candidate = self._implicit.pop()
            if not candidate.has_image:
                opening = candidate.opening
                self.manifest.implicit_graphics.append(ImplicitGraphicInfo(opening.metadata["implicit"],
                    opening.metadata["category"], opening.span.basis.source_id, self.line(opening.span),
                    opening.metadata.get("floating", False), False, self.raw(opening.span), opening.name))
        elif action in {"opaque", "metadata", "citation", "bibliography", "bibliography_style", "biblatex_resource", "biblatex_print"}:
            self._neutral(command)
        self.emit(command.span, command=command)
        if action == "environment_end" and command.metadata.get("document"):
            self._ended_document = True
        # No-argument commands need a lexical separator after a control word.
        if (not command.arguments and action in {"opaque", "biblatex_print", "reading_noop", "process_options", "declared_effects"}
                or action == "boolean_declaration" and command.metadata["unbraced"]
                or action in {"character_code_assignment", "reading_assignment", "integer_parameter_assignment"} and command.metadata.get("trailing_control_word")
                or action in {"conditional_test", "meaning_assignment"} and command.metadata["trailing_control_word"]):
            self.emit(command.span.basis.span(command.span.end, command.span.end), " ", operation="SYNTHETIC_SEPARATOR")

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
        self.manifest.source_survey = survey_sources(self.store, self.resolver.catalog)
        retain_survey_inputs(self)
        self._inventory()
        self.manifest.source_reads = list(self.store.read_paths)
        self.pending_units()
        return self

    def _traverse(self):
        while self.frames and not self._ended_document:
            if self.frames[-1].packages:
                self._package()
                continue
            if len(self.frames) == 1 and self.dispatcher.reader is self._root_reader and not self.dispatcher.branch_in_progress:
                self._checkpoint = (self.frames[0].reader.position, len(self.pieces),
                                    len(self.tombstones), len(self.commands))
            item = self.dispatcher.next_item()
            if item is None:
                break
            if (self.frames[-1].emit and
                    (isinstance(item, CommandDefinition) and item.trailing_control_word
                     or isinstance(item, SourceCommand)
                     and (item.metadata.get("expanded_invocation")
                          or item.action in {"reading_assignment", "character_code_assignment", "integer_parameter_assignment"})
                     and item.metadata.get("trailing_control_word"))
                    and self.context.catcodes[" "] != CatCode.SPACE):
                # Publication cannot use its usual control-word separator.
                # Reuse whole-input retention rather
                # than deferring just this item and continuing an unsafe splice.
                item = self.dispatcher.halt(item.span,
                    ("definition_separator" if isinstance(item, CommandDefinition)
                     else "invocation_separator" if item.metadata.get("expanded_invocation")
                     else "assignment_separator"),
                    "A trailing control word requires a proven output separator under the current catcodes",
                    unit_id=item.unit_id)
            if isinstance(item, ReadingBoundary):
                recovery = self.lint.repair_boundary(self, item)
                if recovery is not None:
                    self.observe(recovery)
                    continue
                # An EOF diagnostic can point to an opener in another input.
                # Keep that anchor in diagnostics; do not misattribute coverage.
                if len(self.frames) == 1:
                    start, pieces, tombstones, commands = self._checkpoint
                    self._checkpoint = (min(start, item.remainder.start), pieces, tombstones, commands)
                recoverable = next((i for i in reversed(range(len(self.frames)))
                                    if self.frames[i].recovery is not None), None)
                self.diagnose(item.span, item.reason, item.detail, unit_id=item.unit_id,
                              materialization="prepared" if recoverable is not None else None, causes=item.causes)
                self.dispatcher.loads.invalidate(item.unit_id)
                if recoverable is not None:
                    frame = self.frames[recoverable]
                    if frame.emit:
                        retain_source(self, frame.path, import_dir=frame.import_dir)
                        del self.pieces[frame.emission_start:]
                        del self.tombstones[frame.tombstone_start:]
                        del self.commands[frame.command_start:]
                        # Already visited descendants still occur in the retained
                        # file. Keep their source, rather than stranding their units.
                        for basis, doc in self.documents.items():
                            if basis.occurrence_id >= frame.reader.basis.occurrence_id:
                                retain_source(self, doc.path, import_dir=frame.import_dir)
                        if self.bibliography_pieces is not None:
                            retained = {piece.key for piece in self.pieces}
                            if any(piece.key not in retained for piece in self.bibliography_pieces):
                                self.bibliography_pieces = None
                    self.require(item.span, "retained_code_reading",
                        f"Retained {self.name(frame.path)!r}; immediate caller resumes with its entry reading state. "
                        "This file's reading effects and dependencies still require resolution.", stage="preparation", unit_id=item.unit_id,
                        materialization="prepared", causes=item.causes)
                    self.dispatcher.resume_input(frame.recovery)
                    self.dispatcher.defer_effects(item.span, reason=item.reason, detail=item.detail)
                    del self.frames[recoverable:]
                    if frame.emit:
                        reference = "\\input{" + self.name(frame.path) + "}"
                        if frame.import_dir is not None:
                            relative = frame.path.relative_to(frame.import_dir, walk_up=True).as_posix()
                            reference = "\\import{" + self.name(frame.import_dir) + "/}{" + relative + "}"
                        self.emit(frame.command.span, reference,
                                  operation="PRESERVE_CODE_INPUT", command=frame.command)
                        if frame.include:
                            self.emit(frame.command.span, "\\clearpage ", operation="INCLUDE_BOUNDARY")
                    continue
                raise _PreserveRemainder
            self.observe(item)
            if isinstance(item, SourceEnd):
                self.omit(item.span, "Unread remainder after endinput")
                # Carry a zero-width cursor through the same ordered emission
                # list as text. Later rewrites/splices move it automatically.
                self.emit(item.span.basis.span(item.span.end, item.span.end), "", operation="SOURCE_END")
                finished = self.frames.pop()
                if finished.replacement is not None:
                    self.link_replacement(finished.emission_start, finished.replacement)
                if finished.bibliography_start is not None:
                    self.finish_bibliography(finished.bibliography_start)
                if finished.include and self.frames:
                    self.emit(item.span, "\\clearpage ", operation="INCLUDE_BOUNDARY")
                continue
            try:
                if isinstance(item, SourceCommand):
                    checkpoint = (len(self.pieces), len(self.tombstones))
                    self._command(item)
                elif isinstance(item, DeferredRegion):
                    dependency = item.command is not None and item.command.action in DEPENDENCY_ACTIONS
                    requirement = self.require(item.span, item.reason, item.detail,
                        stage="binding" if item.reason in {"package_not_loaded", "literal_configuration"} else "interpretation", unit_id=item.unit_id,
                        dependency="possible" if dependency else "none",
                        next_step="binding_knowledge" if item.reason in {"package_not_loaded", "literal_configuration"} else
                            "branch_selection" if item.reason == "branch_selection" else None, causes=item.causes)
                    if item.binding_id:
                        requirement["binding_id"] = item.binding_id
                    if isinstance(item, CollectedEnvironment):
                        requirement["definition_unit_id"] = item.definition_id
                    if item.effect_summary is not None:
                        requirement["effect_summary"] = item.effect_summary.record()
                    if self.frames[-1].emit and (isinstance(item, ConditionalRegion) or item.observations or item.events):
                        emit_observed_region(self, item)
                        continue
                    image_references = observe_environment_assets(self, item)
                    self.require_deferred_dependencies(item.tokens, observed=(o.command for o in item.observations
                        if o.command is not None and o.command.action == "asset_reference"), parent_id=item.unit_id, command=item.command,
                        observations=item.observations, role="branch" if isinstance(item, ConditionalRegion) else "unknown")
                    raw = self.raw(item.span)
                    # A bare control word needs a separator after mouth-discarded
                    # whitespace. Protected groups and math remain exact slices.
                    if item.trailing_control_word:
                        raw += " "
                    self.emit(item.span, raw, operation="DEFER_INTERPRETATION", deferred=item,
                               image_references=image_references)
                elif isinstance(item, ReadEvent):
                    self._emit_event(item)
                elif isinstance(item, SkippedRegion):
                    self.omit(item.span, "Inactive conditional branch")
                elif isinstance(item, LiteralRegion) and item.classification:
                    for detail in item.warnings:
                        self.manifest.warnings.append({"source": item.span.basis.source_id,
                            "start": item.closing.start, "end": item.closing.end,
                            "line": self.line(item.closing), "detail": detail})
                    action = self.policy.get_role_action(item.classification.semantic_role)
                    if action == "eliminate":
                        self.omit(item.span, "Policy eliminated " + item.classification.semantic_role)
                    else:
                        self.emit(item.span)
                        for interpolation in item.interpolations:
                            self.require(interpolation.span, interpolation.reason, interpolation.detail,
                                         stage="interpretation", unit_id=interpolation.unit_id)
                            self.require_deferred_dependencies(interpolation.tokens, parent_id=interpolation.unit_id)
                        if action != "preserve":
                            self.require(item.span, "policy_action", f"Literal role does not support {action!r}", stage="preparation", unit_id=item.unit_id)
                else:
                    self.emit(item.span)
                    if isinstance(item, CommandDefinition) and item.trailing_control_word:
                        self.emit(item.span.basis.span(item.span.end, item.span.end), " ", operation="SYNTHETIC_SEPARATOR")
                    if isinstance(item, (StoredDefinition, EnvironmentDefinition)):
                        body_id = next(i for i in self.units.children.get(item.unit_id, ())
                                       if self.units.records[i].kind == "stored_body")
                        self._observe_argument(ScannedArgument("body", item.body, item.body_tokens, "stored"), body_id)
                    if isinstance(item, CommandDefinition) and item.target_check == "unverified":
                        self._definition_check(item.unit_id, item.declaration, item.target.value, item.target_requirement)
                    if isinstance(item, EnvironmentDefinition):
                        if item.target_check == "unverified":
                            self._definition_check(item.unit_id, item.declaration, item.name, item.target_requirement)
                        if self.frames[-1].path in self.styles:
                            self.styles[self.frames[-1].path].declared_commands.extend((item.name, "end" + item.name))
                    if isinstance(item, StoredDefinition) and self.frames[-1].path in self.styles:
                        self.styles[self.frames[-1].path].declared_commands.append(item.target.value)
            except (ReadingIssue, _DeferredCommand) as error:
                if isinstance(error, ReadingIssue):
                    self.diagnose(item.span, error.reason, error.detail)
                # Only undo the current command's attempted emission. Previous
                # children and subsequent source remain part of the new master.
                del self.pieces[checkpoint[0]:]
                del self.tombstones[checkpoint[1]:]
                self.emit(item.span, command=item, operation="DEFER_RESOLUTION")
            depth = self.context.scope_depth
            self.graphic_paths = {k: v for k, v in self.graphic_paths.items() if k <= depth}
            self.graphic_extensions = {k: v for k, v in self.graphic_extensions.items() if k <= depth}
        if self._ended_document:
            for frame in self.frames:
                remainder = frame.reader.source_span(frame.reader.position, len(frame.reader.text))
                self.observe(SourceEnd(remainder, "end_document"))
                self.omit(remainder, "Unread remainder after end of document")

    def _inventory(self):
        m = self.manifest
        m.active_tex_files = sorted(self.name(p) for p in self.active if p.suffix.lower() == ".tex")
        m.candidate_tex_files = sorted(self.name(p) for p in self.candidate_sources - self.active if p.suffix.lower() == ".tex")
        m.local_styles = list(self.styles.values())
        m.code_inputs = sorted(self.name(p) for p in self.code)
        m.active_images = [characterize_image(self.name(p), str(p)) for p in sorted(self.images)]
        m.candidate_images = [characterize_image(self.name(p), str(p))
                              for p in sorted(self.candidate_images - self.images)]
        m.refresh_status()
        for path in self.store.files:
            if path not in self.active and path not in self.candidate_sources and path not in self.images and path not in self.candidate_images:
                if m.source_dependency_closure != "complete":
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
        m.refresh_status()
