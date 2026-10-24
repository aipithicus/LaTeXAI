"""Stage complete outputs, then publish with rollback on commit errors.

Directory renames prevent readers from seeing a half-written package. Replacing
an existing directory uses a backup rename (Windows cannot replace a nonempty
directory atomically); a reader may briefly see no directory during the swap.
The previous complete directory is restored if any publication operation fails.
"""
from pathlib import Path
import os
import shutil
import tempfile
import time


def _replace(source, destination):
    """Bounded retries for Windows sharing/access errors; never alter ACLs."""
    for attempt in range(5):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 4:
                raise
            time.sleep(0.025 * 2 ** attempt)


class OutputTransaction:
    def __init__(self, destination):
        self.destination = Path(destination).resolve()
        self.temporary = []
        self.targets = []
        self.recovery_needed = False

    def _workspace(self, parent):
        parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=".pytexml-publish-", dir=parent))
        self.temporary.append(directory)
        return directory

    def __enter__(self):
        self.workspace = self._workspace(self.destination.parent)
        self.stage = self.workspace / "payload"
        self.stage.mkdir()
        self.targets.append((self.destination, self.stage, self.workspace / "previous"))
        log = self.destination / "preparation.log"
        self.log_start = 0
        if log.is_file():
            data = log.read_bytes()
            self.log_start = len(data)
            (self.stage / log.name).write_bytes(data)
        return self

    def secondary(self, destination, text):
        destination = Path(destination).resolve()
        if destination.is_relative_to(self.destination):
            target = self.stage / destination.relative_to(self.destination)
        else:
            work = self._workspace(destination.parent)
            target = work / "output"
            self.targets.append((destination, target, work / "previous"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")

    def publish(self):
        committed, displaced = [], []
        try:
            for destination, stage, backup in self.targets:
                if destination.exists():
                    _replace(destination, backup)
                    displaced.append((destination, backup))
                _replace(stage, destination)
                committed.append((destination, stage))
        except BaseException as error:
            # Move newly published products back into owned staging directories
            # before restoring old products. Never recursively delete a target.
            try:
                for destination, stage in reversed(committed):
                    _replace(destination, stage)
                for destination, backup in reversed(displaced):
                    _replace(backup, destination)
            except OSError as recovery:
                self.recovery_needed = True
                raise RuntimeError(f"Publication rollback failed: {recovery}; retained recovery data in "
                                   + ", ".join(str(d) for d in self.temporary)) from error
            raise

    def failure(self, error):
        # A failed first attempt still gets diagnostics. A failed rerun must not
        # replace the last good manifest or any of its resources.
        if self.recovery_needed:
            return
        existed = self.destination.exists()
        if not existed:
            self.destination.mkdir()
            for name in ("manifest.json", "preparation.log"):
                source = self.stage / name
                if source.is_file():
                    os.replace(source, self.destination / name)
        elif (self.stage / "preparation.log").is_file():
            with (self.destination / "preparation.log").open("ab") as log:
                log.write((self.stage / "preparation.log").read_bytes()[self.log_start:])
        with (self.destination / "preparation.log").open("a", encoding="utf-8", newline="\n") as log:
            log.write(f"FAILED ATTEMPT (previous payload preserved)\n{type(error).__name__}: {error}\n")

    def __exit__(self, kind, error, traceback):
        if not self.recovery_needed:
            for directory in reversed(self.temporary):
                shutil.rmtree(directory)
