"""Plan prepared asset destinations and rewrite manuscript image references."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List
from collections import Counter
from dataclasses import dataclass
from ..assets import convert_asset_to_svg
from ..reading.contracts import ReadingIssue, SourceCommand
from ..reading.spans import SourceSpan
from ..reading.argument_scanner import key_value_items
from ..reading.tex_reader import CatCode, TokenKind
from .records import source_reference


@dataclass(frozen=True)
class AssetUse:
    command: SourceCommand
    path: Path
    page: int = 1
    page_spans: tuple[SourceSpan, ...] = ()

    def edits(self, destination):
        yield self.command.argument("target").span, destination
        # A page derivative contains just one page, including when the optional
        # rendering adapter converts the SVG back to a temporary PDF.
        for span in self.page_spans:
            yield span, "1"


def register_asset(session, command, path):
    page, spans = 1, []
    for key, tokens in key_value_items(command.argument("options")):
        if key != "page":
            continue
        tokens = tuple(tokens or ())
        def trimmed(value):
            start, end = 0, len(value)
            while start < end and value[start].catcode == CatCode.SPACE:
                start += 1
            while end > start and value[end - 1].catcode == CatCode.SPACE:
                end -= 1
            return value[start:end]
        tokens = trimmed(tokens)
        while len(tokens) >= 2 and tokens[0].catcode == CatCode.BEGIN_GROUP and tokens[-1].catcode == CatCode.END_GROUP:
            tokens = trimmed(tokens[1:-1])
        if not tokens or any(t.kind != TokenKind.CHARACTER or t.value not in "0123456789" for t in tokens):
            raise ReadingIssue("asset_page", "PDF page requires a positive literal integer")
        page = int("".join(t.value for t in tokens))
        if page < 1 or (page != 1 and path.suffix.lower() != ".pdf"):
            raise ReadingIssue("asset_page", "Page must be positive; multiple pages require a PDF asset")
        spans.append(command.span.basis.span(tokens[0].span.start, tokens[-1].span.end))
    use = AssetUse(command, path, page, tuple(spans))
    session.asset_uses[command.unit_id] = use
    return use


def observe_asset(session, command, context_span, reason, *, binding=None, search_changed=False):
    unit = session.units.records[command.unit_id]
    record = {**source_reference(unit), "kind": "asset",
              "context_span": [context_span.start, context_span.end],
              "context": reason, "basis": "entry_reading_and_search_state",
              "binding": binding, "status": "unresolved"}
    record.update(activity=unit.activity, activity_evidence=dict(unit.activity_evidence))
    session.manifest.candidate_dependencies.append(record)
    try:
        if search_changed:
            raise ReadingIssue("asset_search_context", "An unexecuted search-path/extension declaration precedes this image")
        path = session.image_path(command, provisional=True)
        use = register_asset(session, command, path)
    except ReadingIssue as error:
        record["reason"] = error.reason
        session.require(command.span, error.reason, error.detail, stage="preparation", unit_id=command.unit_id,
                        dependency="possible", next_step="resource_resolution")
        return None
    target = session.name(path)
    record.update(target=target, page=use.page, status="resolved")
    session.candidate_images.add(path)
    session.require(command.span, "observed_asset",
        "Literal image resolved under entry reading/search state; its owning context remains uninterpreted",
        stage="interpretation", unit_id=command.unit_id, materialization="pending", next_step="asset_conversion")
    return command, target


def observe_environment_assets(session, region):
    """Package literal asset observations without executing an unbound body.

    The dispatcher has already protected literals, definitions and arguments.
    Only its captured command headers are eligible; no raw-text search or second
    tokenizer is involved. The environment and its reading assumptions survive.
    """
    references = []
    if region.command is not None and region.command.action == "asset_reference":
        reference = observe_asset(session, region.command, region.span, region.reason, binding=region.binding_id)
        if reference is not None:
            references.append(reference)
    search_changed = False
    for observation in region.observations:
        command = observation.command
        if command.action in {"asset_search_paths", "asset_extensions"}:
            search_changed = True
        if command.action != "asset_reference":
            continue
        reference = observe_asset(session, command, region.span, region.reason,
                                  binding=observation.binding_id, search_changed=search_changed)
        if reference is not None:
            references.append(reference)
    return tuple(references)


def rewrite_image_references(pieces, mapping, uses):
    """Apply captured filename edits; preserve all surrounding source exactly.

    Multiple observations can share one deferred envelope. Edits are applied from
    right to left in that envelope's original coordinate system. Its provenance
    remains a transformation of the whole span, not a false affine mapping.
    """
    result = []
    for piece in pieces:
        for use in uses:
            span = use.command.span
            if (span.basis is piece.span.basis and piece.span.start <= span.start <= span.end <= piece.span.end
                    and piece.operation != "PRESERVE_UNRESOLVED"):
                for target, replacement in sorted(use.edits(mapping[use.command.unit_id]), key=lambda e: e[0].start, reverse=True):
                    piece = piece.edit_source(target, replacement, "REWRITE_IMAGE")
        result.append(piece)
    return result


def batch_convert_assets_to_svg(
    uses: List[AssetUse],
    output_dir: Path,
    project_dir: Path
) -> Dict[str, str]:
    """
    Convert each distinct (file, page) once. Return unit id to payload path.
    """
    variants = list(dict.fromkeys((u.path, u.page) for u in uses))
    explicit = {(u.path, u.page) for u in uses if u.page_spans}
    def name(path, page, *, qualified=False):
        rel = path.relative_to(project_dir)
        stem = rel.as_posix() if qualified else rel.with_suffix("").as_posix()
        return stem + (f"_p{page}" if (path, page) in explicit else "") + ".svg"
    stems = Counter(name(p, page).casefold() for p, page in variants)
    destinations = {}
    occupied = set()
    for p, page in variants:
        target = name(p, page)
        if stems[target.casefold()] > 1:
            target = name(p, page, qualified=True)
        if target.casefold() in occupied:
            raise ValueError(f"Asset output collision: {target}")
        destinations[p, page] = target
        occupied.add(target.casefold())

    for src_path, page in variants:
        if not src_path.exists():
            raise FileNotFoundError(f"Active image not found: {src_path}")

        # Create output destination preserving relative subdirectory
        rel_svg = destinations[src_path, page]
        dest_svg_path = (output_dir / rel_svg).resolve()

        success = convert_asset_to_svg(src_path, dest_svg_path, page_index=page - 1)
        if not success:
            raise RuntimeError(f"SVG conversion failed for {src_path}; package preparation is incomplete")
    return {use.command.unit_id: destinations[use.path, use.page] for use in uses}


def surviving_asset_uses(session, pieces):
    """Select admitted uses whose owning source survived emission rollback."""
    retained = set(session.styles) | session.code
    return [u for u in session.asset_uses.values() if session.documents[u.command.span.basis].path in retained or any(
        p.operation != "PRESERVE_UNRESOLVED" and p.span.basis is u.command.span.basis
        and p.span.start <= u.command.span.start <= u.command.span.end <= p.span.end for p in pieces)]


def prepare_assets(session, pieces, output_dir):
    """Apply the same per-use edits to inlined source and retained local code."""
    retained = set(session.styles) | session.code
    uses = surviving_asset_uses(session, pieces)
    mapping = batch_convert_assets_to_svg(uses, output_dir, session.store.root)
    for use in uses:
        if session.documents[use.command.span.basis].path in retained:
            for span, replacement in use.edits(mapping[use.command.unit_id]):
                session._payload_edit(span, replacement)
    return rewrite_image_references(pieces, mapping, uses), mapping
