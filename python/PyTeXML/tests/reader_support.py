"""Explicit YAML bootstrap shared by lexical conformance fixtures."""
from pathlib import Path

from mouth_profiles import MouthProfiles
from tex_reader import TexReader

def _find_mouth_profiles() -> Path:
    test_dir = Path(__file__).resolve().parent
    for candidate in (
        test_dir.parent / "profiles" / "mouth",
        test_dir.parents[2] / "python" / "latex-extractor" / "profiles" / "mouth",
    ):
        if candidate.is_dir():
            return candidate
    return test_dir.parent / "profiles" / "mouth"


PROFILES = MouthProfiles(_find_mouth_profiles())
BASELINE = PROFILES.baseline("latex_ascii")


def new_catcodes():
    return BASELINE.new_catcodes()


def new_reader(text, **kwargs):
    kwargs.setdefault("catcodes", new_catcodes())
    kwargs.setdefault("endline_char", BASELINE.endlinechar)
    return TexReader(text, **kwargs)
