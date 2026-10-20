"""Explicit YAML bootstrap shared by lexical conformance fixtures."""
from pathlib import Path

from mouth_profiles import MouthProfiles
from tex_reader import TexReader

PROFILES = MouthProfiles(Path(__file__).resolve().parents[2] / "python/latex-extractor/profiles/mouth")
BASELINE = PROFILES.baseline("latex_ascii")


def new_catcodes():
    return BASELINE.new_catcodes()


def new_reader(text, **kwargs):
    kwargs.setdefault("catcodes", new_catcodes())
    kwargs.setdefault("endline_char", BASELINE.endlinechar)
    return TexReader(text, **kwargs)
