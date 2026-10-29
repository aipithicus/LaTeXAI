"""An explicit, finite TeX resource search environment.

Project lookup is owned by preparation. These ordered recursive roots supply its
external vocabulary; no ambient PATH, compiler process or network is consulted.
The inventory is built once per session and its identity enters the manifest.
"""
from collections import defaultdict
from pathlib import Path
import hashlib
import os


class ResourceSearch:
    def __init__(self, roots=None):
        self.closed = roots is not None
        self.roots = tuple(dict.fromkeys(Path(p).resolve() for p in roots or ()))
        self.indices = []
        digest = hashlib.sha256()
        for root in self.roots:
            if not root.is_dir():
                raise FileNotFoundError(f'TeX resource root does not exist: {root}')
            index = defaultdict(list)
            digest.update(str(root).encode('utf-8') + b'\0')
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    relative = path.relative_to(root).as_posix()
                    digest.update(relative.encode('utf-8') + b'\0')
                    index[os.path.normcase(path.name)].append((os.path.normcase(relative), path))
            self.indices.append(index)
        self.fingerprint = digest.hexdigest()

    def find(self, name, suffixes):
        from ..reading.contracts import ReadingIssue
        name = name.replace('\\', '/')
        if Path(name).anchor or '..' in Path(name).parts:
            raise ReadingIssue('dependency_path', 'External resource names must be relative and confined')
        for index in self.indices:
            for suffix in suffixes:
                target = os.path.normcase(Path(name + suffix).as_posix())
                separator = os.path.normcase('/')
                found = [path for relative, path in index.get(os.path.normcase(Path(target).name), ())
                         if relative == target or relative.endswith(separator + target)]
                if len(found) > 1:
                    raise ReadingIssue('ambiguous_dependency', f'Multiple external resources match {target!r}')
                if found:
                    return found[0]
        return None

    def record(self):
        return {'roots': [str(p) for p in self.roots], 'inventory_sha256': self.fingerprint,
                'search': 'project_then_ordered_recursive_roots', 'closed': self.closed}
