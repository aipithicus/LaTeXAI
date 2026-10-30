"""Bounded INITEX source execution through the shared structural dispatcher.

An explicit inventory owns physical input, metrics and provenance. Successful
builds require an executed dump; reaching EOF or a retained command is not a
format build. This does not claim a complete LaTeX/pdfTeX bootstrap.
"""
from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath

from ..bindings.catalog import BindingCatalog
from ..bindings.resolver import BindingResolver
from ..reading.context import ReaderContext
from ..reading.contracts import (MouthBaseline, ReadingBoundary, DeferredRegion, ReadingIssue,
                                 SourceCommand, SourceEnd, StoredDefinition, SkippedRegion, ScannedArgument)
from ..reading.tex_reader import TexReader, CatcodeTable, CatCode, ReadEvent, TokenKind
from ..reading.token_cursor import TokenCursor
from .primitive import PrimitiveMeaning
from .primitives.parameters import INTEGERS, INITIAL, CLOCK_PARAMETERS
from .read_streams import ReadSource
from .programs import PROGRAM_ACTIONS, ProgramSource
from . import format_snapshot


@dataclass
class FormatBuild:
    status: str
    context: ReaderContext
    messages: tuple[str, ...]
    sources: dict
    steps: int
    boundary: dict | None = None
    snapshot: str | None = None
    content: dict | None = None

    def receipt(self):
        return {"schema": "pytexml-content-build/1" if self.content is not None else "pytexml-format-build/1", "status": self.status, "steps": self.steps,
                "messages": self.messages, "sources": self.sources, "boundary": self.boundary,
                "snapshot_sha256": hashlib.sha256(self.snapshot.encode()).hexdigest() if self.snapshot else None,
                "meanings": len(self.context._meanings), "integer_cells": len(self.context.integer_parameters.values),
                "token_cells": len(self.context.token_registers.values), "state_cells": len(self.context.state_cells.values)}


class FormatBuilder:
    def __init__(self, sources, *, metrics=None, initialization=None, profile="pdftex", budget=10000):
        if type(budget) is not int or budget <= 0:
            raise ValueError("Format execution needs a positive step budget")
        self.sources = {name: value if isinstance(value, ReadSource) else ReadSource.from_text(name, value)
                        for name, value in sources.items()}
        if sum(len(value.text) for value in self.sources.values()) > 4000000:
            raise ValueError("Format inventory exceeds the bounded source budget")
        self.metrics, self.profile, self.budget = dict(metrics or {}), profile, budget
        self.initialization = dict(initialization or {})
        if (self.initialization.keys() - CLOCK_PARAMETERS or
                any(type(v) is not int or abs(v) > 2147483647 for v in self.initialization.values())):
            raise ValueError("Initialization accepts explicit integer time/day/month/year values")
        self.manifest = {"text": {name: hashlib.sha256(value.text.encode("utf-8")).hexdigest()
                                  for name, value in sorted(self.sources.items())},
                         "metrics": {name: hashlib.sha256(value).hexdigest() for name, value in sorted(self.metrics.items())},
                         "initialization": self.initialization}
        self.resolver = BindingResolver(BindingCatalog(), engine_profile=profile)

    def initial_context(self, jobname):
        codes = {chr(n): 11 for n in (*range(65, 91), *range(97, 123))}
        codes.update({"\\": 0, "\r": 5, " ": 10, "%": 14, "\x7f": 15, "\0": 9})
        context = ReaderContext(baseline=MouthBaseline("tex82_initex", 12, 13, ()),
                                catcodes=CatcodeTable(codes, default=12),
                                engine_profile=self.profile, primitive_initial_state=True,
                                initial_meanings={(TokenKind.CONTROL_SEQUENCE, name): PrimitiveMeaning("format." + name, None)
                                                  for name in ("input", "end")})
        for name in INTEGERS:
            if name not in CLOCK_PARAMETERS:
                context.integer_parameters.assign(name, INITIAL.get(name, 0), None, global_=True)
        for name, value in {"escapechar": 92, "endlinechar": 13, "defaulthyphenchar": 45, "defaultskewchar": -1}.items():
            context.integer_parameters.assign(name, value, None, global_=True)
        context.state_cells.assign("jobname", jobname, None, global_=True)
        context.state_cells.assign("current_font", "nullfont", None, global_=True)
        return context

    def restore(self, snapshot):
        return format_snapshot.restore(snapshot, sources=self.manifest)

    def build(self, root, *, restored=None, require_dump=True, construct_content=False):
        from ..reading.dispatcher import StructuralDispatcher
        if root not in self.sources:
            raise ValueError("Root is absent from the source inventory")
        context, origins, occurrence = restored if restored is not None else (self.initial_context(PurePosixPath(root).stem), (), 0)
        context = context.copy()
        context.read_streams.configure(self.sources)
        context.fonts.configure(self.metrics)
        context.state_cells.values.pop("format_messages", None)
        context.state_cells.assign("jobname", PurePosixPath(root).stem, None, global_=True)
        for name in CLOCK_PARAMETERS:
            context.integer_parameters.values.pop(name, None)
            if name in self.initialization:
                context.integer_parameters.assign(name, self.initialization[name], None, global_=True)
        def reader(name):
            nonlocal occurrence
            source = self.sources[name]
            result = TexReader(source.text, source_id=name, occurrence_id=occurrence,
                               catcodes=context.catcodes, endline_char=context.endlinechar)
            occurrence += 1
            return result
        host = StructuralDispatcher(reader(root), context, self.resolver, preparation=True, source_commands=True)
        if construct_content:
            from .content import ContentState
            host.content = ContentState(host.reader.basis.span(0, 0))
        for basis, text, tokens, anchor, relation in origins:
            frozen = TokenCursor(ScannedArgument("program", basis.whole, tokens), text, context)
            host.program_sources.append(ProgramSource(frozen, anchor, relation))
        host.program_serial = max((-s.reader.basis.occurrence_id for s in host.program_sources), default=0)
        steps, status, boundary, snapshot = 0, "missing_dump", None, None
        item = SourceCommand(host.reader.basis.span(0, 0), "", "format_start")
        try:
            if restored is not None:
                from .programs import evaluate, SETUP, CONTENT
                everyjob = context.token_registers.read("everyjob")
                if everyjob:
                    evaluate(host, everyjob, item.span, policy=CONTENT if construct_content else SETUP)
            while (item := host.next_item()) is not None:
                steps += 1
                if steps > self.budget:
                    raise ReadingIssue("format_budget", "Format execution exhausted its step budget")
                if isinstance(item, (ReadingBoundary, DeferredRegion)):
                    raise ReadingIssue(item.reason, item.detail, causes=getattr(item, "causes", ()))
                if isinstance(item, SourceCommand):
                    if item.action == "format_input":
                        name = item.metadata["filename"]
                        relative = str(PurePosixPath(host.reader.basis.source_id).parent / name)
                        candidates = (relative, relative + ".tex", name, name + ".tex")
                        found = next((path for path in candidates if path in self.sources), None)
                        if found is None:
                            raise ReadingIssue("input_inventory", f"Input {name!r} is absent from the inventory")
                        if len(host._parents) >= 64:
                            raise ReadingIssue("input_budget", "Input nesting exceeds 64 sources")
                        host.enter_source(reader(found))
                    elif item.action == "format_dump":
                        if construct_content:
                            raise ReadingIssue("content_dump", "Content execution does not dump a format")
                        saved_origins = tuple((s.reader.basis, s.reader.text, tuple(s.reader.tokens), s.anchor, s.origins)
                                              for s in host.program_sources)
                        snapshot = format_snapshot.save(context, sources=self.manifest, origins=saved_origins,
                                                        next_occurrence=occurrence)
                        status = "dumped"
                        break
                    elif item.action == "format_end":
                        status = "missing_dump" if require_dump else "completed"
                        break
                    elif item.action == "content" and construct_content:
                        pass
                    elif item.action not in PROGRAM_ACTIONS | {"setup_program", "end_input"}:
                        raise ReadingIssue("format_effect", f"Format owner cannot execute {item.action!r}")
                elif isinstance(item, ReadEvent):
                    token = item.token
                    if not construct_content and token is not None and token.kind == TokenKind.CHARACTER and token.catcode not in {
                            CatCode.SPACE, CatCode.BEGIN_GROUP, CatCode.END_GROUP}:
                        raise ReadingIssue("format_content", "Format build reached typeset content")
                elif not isinstance(item, (StoredDefinition, SourceEnd, SkippedRegion)):
                    raise ReadingIssue("format_effect", f"Unsupported format result {type(item).__name__}")
            else:
                if not require_dump:
                    status = "completed"
            if construct_content:
                host.content.finish(host, item.span if item is not None else host.reader.basis.whole)
        except ReadingIssue as error:
            span = item.span if item is not None else host.reader.basis.whole
            boundary = {"reason": error.reason, "detail": error.detail, "source": span.basis.source_id,
                        "occurrence": span.basis.occurrence_id, "start": span.start, "end": span.end}
            if construct_content:
                from .content import location
                remainder = (item.remainder if isinstance(item, ReadingBoundary) else
                    host.reader.source_span(span.start if span.basis == host.reader.basis else host.reader.position,
                                            len(host.reader.text)))
                boundary["remainder"] = location(remainder)
            status = "boundary"
        except ValueError as error:
            # A rejected snapshot is a build failure, never a successful dump.
            if not isinstance(item, SourceCommand) or item.action != "format_dump":
                raise
            status, boundary = "boundary", {"reason": "format_snapshot", "detail": str(error),
                                            "source": item.span.basis.source_id, "start": item.span.start, "end": item.span.end}
        messages = context.state_cells.read("format_messages") if "format_messages" in context.state_cells.values else ()
        return FormatBuild(status, context, messages, self.manifest, steps, boundary, snapshot,
                           host.content.as_dict() if construct_content else None)


def main():
    """Build/restore from a JSON inventory of explicitly named local files."""
    import argparse
    import json
    from pathlib import Path
    import time
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="JSON with entry, sources and optional metrics mappings")
    parser.add_argument("--entry", help="Override the entry name from the inventory")
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--output", type=Path, help="Destination for a successful JSON format dump")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--no-dump", action="store_true", help="Allow a completed execution without dump")
    parser.add_argument("--budget", type=int, default=10000)
    args = parser.parse_args()
    start, cpu = time.perf_counter(), time.process_time()
    config = json.loads(args.inventory.read_text(encoding="utf-8"))
    base = args.inventory.resolve().parent
    sources = {name: (base / path).read_bytes().decode("utf-8") for name, path in config["sources"].items()}
    metrics = {name: (base / path).read_bytes() for name, path in config.get("metrics", {}).items()}
    builder = FormatBuilder(sources, metrics=metrics, initialization=config.get("initialization"),
                            profile=config.get("profile", "pdftex"), budget=args.budget)
    restored = builder.restore(args.restore.read_text(encoding="utf-8")) if args.restore else None
    result = builder.build(args.entry or config["entry"], restored=restored, require_dump=not args.no_dump)
    receipt = result.receipt()
    receipt["timing"] = {"wall_seconds": time.perf_counter() - start, "cpu_seconds": time.process_time() - cpu,
                         "instrumentation": "counters; includes inventory and resolver construction"}
    from ..validation.measured_prepare import peak_memory
    receipt["memory"] = {**peak_memory(), "memory_scope": "format_worker_process"}
    if args.output and result.snapshot:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result.snapshot, encoding="utf-8", newline="\n")
    rendered = json.dumps(receipt, indent=2, ensure_ascii=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0 if result.status in {"dumped", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
