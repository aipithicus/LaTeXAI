"""Root selection over cached sources, using the structural reader."""
from __future__ import annotations
from pathlib import Path
from ..source_io import SourceStore
from ..bindings.resolver import BindingResolver
from ..reading.dispatcher import StructuralDispatcher
from ..reading.contracts import SourceCommand, ReadingBoundary
from ..reading.tex_reader import TexReader, ReadEvent, EventKind
from .emission import comment_directive


def select_root(store: SourceStore, explicit: str | None = None, *, catalog=None) -> Path:
    if explicit is not None:
        path = (store.root / explicit).resolve()
        if store.is_excluded(path):
            raise ValueError(f"Root must be a source file within the project: {explicit}")
        if not store.contains(path):
            raise FileNotFoundError(f"Root TeX file not found: {path}")
        return path
    files = [p for p in store.files if p.suffix.lower() == ".tex"]
    if not files:
        raise FileNotFoundError(f"No .tex files found in {store.root}")
    candidates, hints, blocked = [], set(), []
    for path in files:
        doc = store.document(path)
        resolver = BindingResolver(catalog)
        if catalog is None:
            catalog = resolver.catalog
        context = resolver.new_context()
        reader = TexReader(doc.text, source_id=doc.name, catcodes=context.catcodes,
                           endline_char=context.endlinechar)
        for item in StructuralDispatcher(reader, context, resolver, source_commands=True, preparation=True):
            if isinstance(item, ReadingBoundary):
                blocked.append(f"{doc.name}:{item.span.start} ({item.reason})")
                break
            if isinstance(item, SourceCommand) and item.action == "document_class":
                if item.value("name") != "subfiles":
                    candidates.append(path)
                break
            if isinstance(item, ReadEvent) and item.kind == EventKind.COMMENT:
                # Use the mouth's introducer span, including ^^ spelling.
                directive = comment_directive(item, doc.text)
                if directive and directive["key"] == "root":
                    value = directive["value"]
                    target = (path.parent / value).resolve()
                    if not store.contains(target):
                        raise ValueError(f"Invalid root hint in {doc.name}: {value}")
                    hints.add(target)
    choices = sorted(hints) if hints else candidates
    if len(choices) == 1:
        return choices[0]
    if not choices and len(files) == 1:
        return files[0]
    detail = ", ".join(p.relative_to(store.root).as_posix() for p in choices) or "; ".join(blocked)
    raise ValueError(f"Root selection is unresolved; supply root_tex. Candidates/boundaries: {detail}")


def find_root_tex(project_dir: str, excluded_dirs=None) -> str:
    store = SourceStore(Path(project_dir), excluded_dirs or ())
    return select_root(store).relative_to(store.root).as_posix()
