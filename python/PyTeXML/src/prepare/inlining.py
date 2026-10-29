"""Residual TeX for a characterized LaTeX document-input event.

Hook bodies remain registered in the delivered program. Python's evaluation is
analysis only; the renderer dispatches them exactly once at the inserted body.
No input-wide group, private hook registry, or generated runtime is installed.
"""
from ..reading.contracts import BoundMeaning, ReadingIssue
from ..reading.tex_reader import CatCode
from ..engine.primitive import PrimitiveMeaning
from .emission import SourcePiece


def check_context(context):
    expected = {"\\": CatCode.ESCAPE, "{": CatCode.BEGIN_GROUP, "}": CatCode.END_GROUP,
                " ": CatCode.SPACE, "#": CatCode.PARAMETER, "%": CatCode.COMMENT}
    expected.update((c, CatCode.LETTER) for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if any(context.catcodes[c] != code for c, code in expected.items()):
        raise ReadingIssue("file_hook_serialization", "File-event TeX requires established standard delimiter/letter catcodes")
    if any(context.catcodes[c] not in {CatCode.OTHER, CatCode.LETTER, CatCode.SUBSCRIPT}
           for c in "@_:./-"):
        raise ReadingIssue("file_hook_serialization", "File-event helper names require inert punctuation tokens")
    for name in ("csname", "endcsname", "let"):
        meaning = context.lookup_meaning(name) or context.engine_profile.lookup(name)
        expected_meaning = context.engine_profile.lookup(name)
        if not (isinstance(meaning, PrimitiveMeaning) and meaning.uncertain is None
                and isinstance(expected_meaning, PrimitiveMeaning) and meaning.identity == expected_meaning.identity):
            raise ReadingIssue("file_hook_serialization", f"File-event serialization depends on the original {name} operation")
    for name in ("@expl@@@filehook@file@push@@", "@expl@@@filehook@file@pop@@",
                 "__filehook_set_curr_file_assign:nnnNN", "@addtofilelist"):
        meaning = context.lookup_meaning(name)
        if meaning is not None and not (isinstance(meaning, BoundMeaning) and meaning.uncertain is None
                and meaning.profile is not None and meaning.profile.name == name):
            raise ReadingIssue("file_hook_serialization", f"File-event helper {name!r} was redefined")


def _internal(name):
    return "\\csname " + name + "\\endcsname"


def context_assignment(event):
    if any(c in value for value in (*event.values, event.resolved) for c in "\\{}%#^\r\n"):
        raise ReadingIssue("file_hook_filename", "File-event lowering requires literal TeX-safe paths")
    # CurrentFile values are strings (OTHER characters, SPACE for spaces), not
    # tokens read under the payload's letter/subscript/active-character catcodes.
    return (_internal("__filehook_set_curr_file_assign:nnnNN")
            + "{" + event.path + "}{" + event.name + "}{}"
            + r"\CurrentFileUsed\CurrentFilePathUsed"
            + r"\let\CurrentFile\CurrentFileUsed\let\CurrentFilePath\CurrentFilePathUsed ")


def wrappers(event, line):
    assign = context_assignment(event)
    before = (_internal("@expl@@@filehook@file@push@@") + assign
        + _internal("@addtofilelist") + "{" + event.resolved + "}"
        + r"\UseHook{file/before}\UseHook{file/\CurrentFile/before}")
    after = (assign + r"\UseHook{file/\CurrentFile/after}\UseHook{file/after}"
        + _internal("@expl@@@filehook@file@pop@@") + "{}")
    # The empty trailing group is a lexical delimiter, not a scope around the
    # file: it prevents the last control word from swallowing a following space.
    sources = tuple(dict.fromkeys((event.anchor, *event.origins)))
    return tuple(SourcePiece(text, event.anchor, line, operation=operation,
                             derivations=sources)
                 for text, operation in ((before, "FILE_HOOK_ENTER"), (after, "FILE_HOOK_LEAVE")))
