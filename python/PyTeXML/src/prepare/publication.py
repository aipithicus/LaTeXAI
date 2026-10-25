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
    def __init__(self, destination, *, retained=()):
        self.destination = Path(destination).resolve()
        self.temporary = []
        self.targets = []
        self.recovery_needed = False
        if any(Path(name).name != name or name in {"", ".", ".."} for name in retained):
            raise ValueError("Retained bookkeeping must use plain filenames")
        self.retained_paths = {name: self.destination / name for name in retained}

    def _move(self, source, destination):
        _replace(source, destination)
        for name, path in self.retained_paths.items():
            if path.is_relative_to(source):
                self.retained_paths[name] = destination / path.relative_to(source)

    def _workspace(self, parent):
        parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=".pytexml-publish-", dir=parent))
        self.temporary.append(directory)
        return directory

    def __enter__(self):
        self.existed = self.destination.exists()
        self.workspace = self._workspace(self.destination.parent)
        self.stage = self.workspace / "payload"
        self.stage.mkdir()
        self.targets.append((self.destination, self.stage, self.workspace / "previous"))
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
        committed, displaced, carried = [], [], []
        try:
            for destination, stage, backup in self.targets:
                if destination.exists():
                    self._move(destination, backup)
                    displaced.append((destination, backup))
                    if destination == self.destination:
                        # Journals have their own append-only lifetime. Carry
                        # them by rename, without reading/copying their history.
                        for name in self.retained_paths:
                            old, new = backup / name, stage / name
                            if old.exists():
                                if new.exists():
                                    raise ValueError(f"Prepared payload collides with retained journal: {name}")
                                self._move(old, new)
                                carried.append((old, new))
                self._move(stage, destination)
                committed.append((destination, stage))
        except BaseException as error:
            # Move newly published products back into owned staging directories
            # before restoring old products. Never recursively delete a target.
            try:
                for destination, stage in reversed(committed):
                    self._move(destination, stage)
                for old, new in reversed(carried):
                    self._move(new, old)
                for destination, backup in reversed(displaced):
                    self._move(backup, destination)
            except OSError as recovery:
                self.recovery_needed = True
                raise RuntimeError(f"Publication rollback failed: {recovery}; retained recovery data in "
                                   + ", ".join(str(d) for d in self.temporary)) from error
            raise

    def failure(self):
        # A failed first attempt still gets diagnostics. A failed rerun must not
        # replace the last good manifest or any of its resources.
        if self.recovery_needed:
            return
        if not self.existed:
            self.destination.mkdir(exist_ok=True)
            source = self.stage / "manifest.json"
            if source.is_file():
                os.replace(source, self.destination / source.name)

    def __exit__(self, kind, error, traceback):
        if not self.recovery_needed:
            for directory in reversed(self.temporary):
                shutil.rmtree(directory)
