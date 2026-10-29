"""An explicit, finite TeX resource search environment.

Project lookup is owned by preparation. These ordered recursive roots supply its
external vocabulary; no ambient PATH, compiler process or network is consulted.
The inventory is built once per session and its identity enters the manifest.
"""
from collections import defaultdict
from pathlib import Path
import hashlib
import os
import stat


class ResourceSearch:
    def __init__(self, roots=None):
        self.closed = roots is not None
        self.roots = tuple(dict.fromkeys(Path(p).resolve() for p in roots or ()))
        self.indices = []
        self.errors = []
        digest = hashlib.sha256()
        for root in self.roots:
            index = defaultdict(list)
            errors = []
            self.errors.append(errors)
            digest.update(str(root).encode('utf-8') + b'\0')
            try:
                if not stat.S_ISDIR(root.stat().st_mode):
                    raise NotADirectoryError(str(root))
            except OSError as error:
                errors.append(error)
            else:
                files = []
                for directory, dirs, names in os.walk(root, onerror=errors.append):
                    dirs.sort()
                    files.extend(Path(directory) / name for name in names)
                for path in sorted(files):
                    try:
                        if not stat.S_ISREG(path.stat().st_mode):
                            continue
                    except OSError as error:
                        errors.append(error)
                        continue
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
        for index, errors in zip(self.indices, self.errors):
            if errors:
                reason = ('file_search_environment' if all(isinstance(e, (FileNotFoundError, NotADirectoryError))
                                                          for e in errors) else 'resource_access')
                raise ReadingIssue(reason, '; '.join(str(e) for e in errors))
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
                'search': 'project_then_ordered_recursive_roots', 'closed': self.closed,
                'inventory_complete': not any(self.errors),
                'inventory_errors': [str(error) for errors in self.errors for error in errors]}
