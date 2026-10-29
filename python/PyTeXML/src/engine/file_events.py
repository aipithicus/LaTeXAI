"""LaTeX document-input events over the reader's existing execution context."""
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .programs import evaluate
from .requests import origin
from ..reading.contracts import BoundMeaning, ReadingIssue, TokenListMeaning
from ..reading.tex_reader import CatCode, Token, TokenKind


CONTEXT_NAMES = ("CurrentFilePathUsed", "CurrentFileUsed", "CurrentFilePath", "CurrentFile")
CONTRACT = "latex-file-hooks/2026-06-01"


@dataclass
class FileInput:
    requested: str
    resolved: str
    anchor: object
    basis: object
    saved: tuple = ()
    installed: tuple = ()
    required: bool = False
    events: list = field(default_factory=list)
    origins: list = field(default_factory=list)

    @property
    def name(self):
        return PurePosixPath(self.resolved).name

    @property
    def path(self):
        parent = PurePosixPath(self.resolved).parent.as_posix()
        return "" if parent == "." else parent

    @property
    def values(self):
        # This slice admits resolved author inputs without file substitution.
        return self.path, self.name, self.path, self.name

    @property
    def hooks(self):
        return "file/before", f"file/{self.name}/before", f"file/{self.name}/after", "file/after"

    def _install(self, context):
        span = self.basis.span(0, 0)
        installed = []
        for name, value in zip(CONTEXT_NAMES, self.values):
            tokens = tuple(Token(TokenKind.CHARACTER, char,
                CatCode.SPACE if char == " " else CatCode.OTHER, span) for char in value)
            meaning = TokenListMeaning(span, tokens, format_origin=CONTRACT)
            context.record_meaning(name, meaning)
            installed.append(meaning)
        self.installed = tuple(installed)

    def enter(self, host):
        self.saved = tuple(host.context.lookup_meaning(name) for name in CONTEXT_NAMES)
        self.required = host.context.hooks.relevant(self.hooks)
        self._install(host.context)
        self.fire(host, self.hooks[:2])

    def fire(self, host, names):
        meaning = host.context.resolve_meaning(host.knowledge, "UseHook")
        if not (isinstance(meaning, BoundMeaning) and meaning.uncertain is None
                and meaning.profile is not None and meaning.profile.action == "hook_use"):
            raise ReadingIssue("file_hook_dispatch", "The format's hook dispatcher was redefined or is uncertain")
        for name in names:
            # Read each table at its event, not one snapshot before all events.
            bodies = host.context.hooks.bodies(name)
            self.required |= bool(bodies)
            record = {"hook": name, "registrations": [origin(b.registration) for b in bodies],
                      "diagnostics": [], "status": "completed"}
            for body in bodies:
                self.origins.append(body.registration)
                results = evaluate(host, body.tokens, self.anchor)
                record["diagnostics"].extend(r.metadata["message"] for r in results
                    if getattr(r, "action", None) == "hook_diagnostic")
            self.events.append(record)

    def leave(self, host):
        # The kernel restores the input's file identity before firing after hooks,
        # even if the body assigned CurrentFile or performed a nested input.
        # A retained invocation may read these values; a source assignment may
        # replace them. Both require a residual context lifetime even without a
        # registered hook. Unknown writes already mark meanings uncertain.
        self.required |= any(host.context.lookup_meaning(name) != meaning
                             for name, meaning in zip(CONTEXT_NAMES, self.installed))
        self._install(host.context)
        self.fire(host, self.hooks[2:])
        self.required |= self.basis.occurrence_id in host.context.hooks.context_reads
        for name, value in zip(CONTEXT_NAMES, self.saved):
            host.context.record_meaning(name, value or TokenListMeaning(None, (), format_origin=CONTRACT))

    def record(self, status="inlined"):
        return {"contract": CONTRACT, "requested": self.requested, "resolved": self.resolved,
                "occurrence": self.basis.occurrence_id, "invocation": origin(self.anchor),
                "status": status, "lowered": status == "inlined" and self.required, "events": self.events}

    def invalidate_retained_effects(self, host):
        # Runtime will still execute the retained file and hooks. Restoring the
        # probe entry must not license later branch selection from stale macros.
        if self.required:
            host.context.invalidate_meanings(host.context.meaning_names(), self.anchor)
        host.context.hooks.invalidate_effects(None, self.anchor)
