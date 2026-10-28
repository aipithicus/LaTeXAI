"""Explicit YAML bootstrap shared by lexical conformance fixtures."""
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from src.bindings.catalog import BindingCatalog
from src.reading.mouth_profiles import MouthProfiles
from src.reading.tex_reader import TexReader
from src.reading.argument_scanner import ArgumentScanner
from src.reading.options import option_items

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILES = MouthProfiles(PROJECT_ROOT / "resources" / "profiles" / "mouth")
BASELINE = PROFILES.baseline("latex_ascii")


def new_catcodes():
    return BASELINE.new_catcodes()


def new_reader(text, **kwargs):
    kwargs.setdefault("catcodes", new_catcodes())
    kwargs.setdefault("endline_char", BASELINE.endlinechar)
    return TexReader(text, **kwargs)


def requested_options(context, names, source="request.tex"):
    reader = TexReader("{" + ",".join(names) + "}", source_id=source,
                       catcodes=context.catcodes, endline_char=context.endlinechar)
    return option_items(ArgumentScanner(reader, context).group("options"))


def reload_catalog(testcase, catalog):
    """Author a modified fixture as YAML, then validate/index it as production does.

    A loaded catalog is a snapshot, not a mutable declaration builder. Synthetic
    test packages receive a filename identity when they do not supply one.
    """
    directory = PROJECT_ROOT / "temp" / "tests"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = TemporaryDirectory(dir=directory, prefix="catalog-")
    testcase.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    for tier, bindings, key in (("engine", catalog.engine_bindings, "name"),
                                ("packages", catalog.package_bindings, "package")):
        (root / tier).mkdir()
        for name, data in bindings.items():
            authored = {"identity": {key: name}, **data}
            (root / tier / f"{name}.yaml").write_text(
                yaml.safe_dump(authored, sort_keys=False), encoding="utf-8", newline="\n")
    return BindingCatalog(root, catalog.profiles_dir, catalog.handlers_path)
