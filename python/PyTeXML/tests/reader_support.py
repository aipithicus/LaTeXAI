"""Explicit YAML bootstrap shared by lexical conformance fixtures."""
from pathlib import Path

from src.reading.mouth_profiles import MouthProfiles
from src.reading.tex_reader import TexReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILES = MouthProfiles(PROJECT_ROOT / "resources" / "profiles" / "mouth")
BASELINE = PROFILES.baseline("latex_ascii")


def new_catcodes():
    return BASELINE.new_catcodes()


def new_reader(text, **kwargs):
    kwargs.setdefault("catcodes", new_catcodes())
    kwargs.setdefault("endline_char", BASELINE.endlinechar)
    return TexReader(text, **kwargs)
