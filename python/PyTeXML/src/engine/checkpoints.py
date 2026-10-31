"""One rollback protocol for language, preparation and materialization requests.

Participants own their state representation. The checkpoint owns ordering and
exactly-once completion. Failure evidence and consumed work budgets are outside
the speculative state; callers publish recovery only after rollback succeeds.
"""
from collections import deque
from dataclasses import replace


class Checkpoint:
    def __init__(self, *participants, boundary="request"):
        self.participants = participants
        self.boundary = boundary
        self.status = "open"

    def commit(self):
        if self.status != "open":
            raise ValueError("A completed checkpoint cannot be committed again")
        self.status = "committed"

    def rollback(self):
        if self.status == "rolled_back":
            return
        if self.status != "open":
            raise ValueError("A committed checkpoint cannot be rolled back")
        for participant in reversed(self.participants):
            participant.restore()
        for participant in self.participants:
            reconcile = getattr(participant, "after_restore", None)
            if reconcile is not None:
                reconcile()
        self.status = "rolled_back"

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if self.status == "open":
            self.rollback() if kind else self.commit()
        return False


class LanguageState:
    """The active continuation, including suspended mouths and token inputs.

An enclosing *retention* boundary keeps already observed units/decisions and
generated origins. A failed command rolls those speculative observations back.
Neither route restores fuel: an attempted operation has spent its budget.
"""
    _scalars = ("_base_scope_depth", "_skip_start", "_pending_skip", "_lexical_failure",
                "halted", "_finished", "_root_ended", "assignment_prefixes")

    def __init__(self, host, *, observations=True):
        self.host, self.observations = host, observations
        self.recording = host.context.recorder.checkpoint() if getattr(host.context, "recorder", None) is not None else None
        self.reader = host.reader
        self.context = host.context.copy()
        self.content = host.content.checkpoint() if getattr(host, "content", None) is not None else None
        self.parents, self.options = host._copy_option_stack(host._parents, host.options)
        readers = {host.reader, *(entry[0] for entry in host._parents)}
        for mapping in (host._replays, host._branch_replays):
            readers.update(mapping)
            readers.update(value[0] for value in mapping.values())
        self.readers = [(reader, reader.checkpoint(), reader.endline_char) for reader in readers]
        self.scalars = {name: getattr(host, name) for name in self._scalars if hasattr(host, name)}
        self.groups = list(host._groups)
        self.conditionals = [replace(c) for c in host._conditionals]
        self.environments = list(host._environment_stack)
        self.replays = dict(host._replays)
        self.branch_replays = dict(host._branch_replays)
        self.active_branches = list(host._active_branches)
        self.pending = deque(host._pending)
        self.loads = (dict(host.loads.loaded), list(host.loads.uncertainties))
        self.packages = list(host.knowledge.active_packages) if hasattr(host.knowledge, "active_packages") else None
        if observations:
            self.units = host.units.checkpoint()
            self.decisions = list(host.decisions)
            self.conditional_units = dict(host._conditional_units)
            self.sources = list(host.program_sources)
            self.serial = host.program_serial

    def restore(self):
        host = self.host
        host.context.restore_from(self.context)
        if self.content is not None:
            host.content.restore(self.content)
        for reader, saved, endline in self.readers:
            reader.restore(saved)
            reader.endline_char = endline
        for name in self._scalars:
            if name in self.scalars:
                setattr(host, name, self.scalars[name])
            elif hasattr(host, name):
                delattr(host, name)
        parents, host.options = host._copy_option_stack(self.parents, self.options)
        host._parents = list(parents)
        host._groups = list(self.groups)
        host._conditionals = [replace(c) for c in self.conditionals]
        host._environment_stack = list(self.environments)
        host._replays, host._branch_replays = dict(self.replays), dict(self.branch_replays)
        host._active_branches, host._pending = list(self.active_branches), deque(self.pending)
        host.loads.loaded, host.loads.uncertainties = dict(self.loads[0]), list(self.loads[1])
        if self.packages is not None:
            host.knowledge.active_packages[:] = self.packages
        if self.observations:
            host.units.restore(self.units)
            host.decisions, host._conditional_units = list(self.decisions), dict(self.conditional_units)
            host.program_sources[:] = self.sources
            host.program_serial = max(host.program_serial, self.serial)
        host._set_reader(self.reader)
        if self.recording is not None:
            host.context.recorder.rollback(self.recording)


def language_checkpoint(host, *, observations=True, boundary="command"):
    return Checkpoint(LanguageState(host, observations=observations), boundary=boundary)


class ContinuationPoint:
    """A scanned request's input position, without its speculative state writes.

    Resuming is allowed only for a complete request returned by the dispatcher.
    Frozen tokens and mouth positions survive; current reading parameters belong
    to the restored caller, not to the failed attempt.
    """
    def __init__(self, host):
        self.host, self.reader = host, host.reader
        readers = {host.reader, *(entry[0] for entry in host._parents)}
        self.readers = [(reader, reader.checkpoint()) for reader in readers]

    def restore(self):
        host = self.host
        catcodes = host.context.catcodes.copy()
        for reader, saved in self.readers:
            reader.restore(saved)
        host.context.catcodes.restore_from(catcodes)
        host._set_reader(self.reader)
        host.reader.endline_char = host.context.endlinechar


class Attempt:
    """An operation and its optional, already-scanned recovery continuation."""
    def __init__(self, checkpoint):
        self.checkpoint, self.continuation = checkpoint, None
        self.recoveries = {}
        self.retention_required = False

    def commit(self):
        if self.checkpoint.status == "open":
            self.checkpoint.commit()

    def rollback(self):
        self.checkpoint.rollback()

    def resume(self):
        if self.continuation is not None:
            self.continuation.restore()


class ArtifactState:
    """Exact owned output paths inside an unpublished materialization stage."""
    def __init__(self, *paths):
        self.files = {path: path.read_bytes() if path.exists() else None for path in paths}

    def restore(self):
        for path, contents in self.files.items():
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(contents)
