"""Inventory is a view of the same traversal used to assemble master.tex."""
from pathlib import Path
from .session import PreparationSession


def preflight_inventory(project_dir: str, root_tex=None, engine="pytexml",
                        execute_probe=False, excluded_dirs=None):
    if execute_probe:
        raise ValueError("External execution probes are not part of preparation")
    return PreparationSession(Path(project_dir), root_tex=root_tex, engine=engine,
                              excluded_dirs=excluded_dirs or ()).run().manifest


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Inspect reading-aware source dependencies")
    parser.add_argument("project_dir")
    parser.add_argument("root_tex", nargs="?")
    args = parser.parse_args()
    print(preflight_inventory(args.project_dir, args.root_tex).to_json())
