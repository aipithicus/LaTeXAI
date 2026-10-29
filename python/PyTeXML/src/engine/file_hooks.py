"""Bounded LaTeX hook facilities, declared in Python beside their handlers.

Source contract: LaTeX2e 2026-06-01, latex.ltx SHA256
19d3b75884681539e1ef7a427af472bfe80d9ff214b84b9ca45e790d3e89c5c4.
These are format meanings, not engine primitives or YAML spelling overrides.
"""
from dataclasses import replace
from types import MappingProxyType

from .operations import ExecutableOperation, ExpansionKind, OperationFamily
from .requests import expand_literal_argument
from ..reading.argument_scanner import ArgumentScanner
from ..reading.contracts import EffectiveReadingProfile, ReadingIssue, TokenListMeaning
from ..reading.tex_reader import CatCode, Token, TokenKind


def _argument(name, kind="braced", role="data"):
    return {"name": name, "kind": kind, "role": role}


def _profile(name, action, *arguments):
    return EffectiveReadingProfile(name, "format_hook", action=action,
        grammar={"handler": "source_arguments", "arguments": arguments},
        binding_id="format:latex-file-hooks/2026-06-01")


PROFILES = MappingProxyType({p.name: p for p in (
    _profile("AddToHook", "hook_register", _argument("hook"), _argument("label", "optional"),
             _argument("body", role="stored")),
    _profile("RemoveFromHook", "hook_remove", _argument("hook"), _argument("label", "optional")),
    _profile("AddToHookNext", "hook_unresolved", _argument("hook"), _argument("body", role="stored")),
    _profile("ClearHookNext", "hook_unresolved", _argument("hook")),
    _profile("DeclareHookRule", "hook_unresolved", _argument("hook"), _argument("first"),
             _argument("relation"), _argument("second")),
    _profile("UseHook", "hook_use", _argument("hook")),
    _profile("typeout", "hook_diagnostic", _argument("message", role="diagnostic")),
    _profile("@expl@@@filehook@file@push@@", "file_context_push"),
    _profile("@expl@@@filehook@file@pop@@", "file_context_pop"),
    _profile("@expl@@@filehook@file@pop@assign@@nnnn", "file_context_set",
             *(_argument(name, role="stored") for name in ("path_used", "name_used", "path", "name"))),
    _profile("@addtofilelist", "file_list", _argument("file")),
    _profile("__filehook_set_curr_file_assign:nnnNN", "file_context_strings",
             _argument("path"), _argument("base"), _argument("extension"),
             _argument("file_target", "control_sequence"), _argument("path_target", "control_sequence")),
)})


def execute(host, opening, profile):
    command = ArgumentScanner(host.reader, host.context).read(opening.span, profile)
    if command.action.startswith("file_context_"):
        from .file_events import CONTEXT_NAMES, CONTRACT
        if command.action == "file_context_push":
            host.context.hooks.context_stack.append(tuple(host.context.lookup_meaning(n) for n in CONTEXT_NAMES))
        elif command.action == "file_context_pop":
            if not host.context.hooks.context_stack:
                raise ReadingIssue("file_context_stack", "File context stack is empty")
            for name, value in zip(CONTEXT_NAMES, host.context.hooks.context_stack.pop()):
                host.context.record_meaning(name, value or TokenListMeaning(None, (), format_origin=CONTRACT))
        elif command.action == "file_context_strings":
            values = (command.value("base") + command.value("extension"), command.value("path"))
            for target, value in zip((command.argument("file_target"), command.argument("path_target")), values):
                tokens = tuple(Token(TokenKind.CHARACTER, char, CatCode.SPACE if char == " " else CatCode.OTHER,
                                     command.span) for char in value)
                host.context.record_meaning(target.tokens[0].value,
                    TokenListMeaning(command.span, tokens, format_origin=CONTRACT))
        else:
            for name, argument in zip(CONTEXT_NAMES, command.arguments):
                host.context.record_meaning(name, TokenListMeaning(command.span, argument.tokens, format_origin=CONTRACT))
        return command
    if command.action == "file_list":
        return command
    if command.action == "hook_diagnostic":
        argument = expand_literal_argument(host, command.argument("message"))
        return replace(command, metadata={**command.metadata, "message": argument.literal()})
    name = expand_literal_argument(host, command.argument("hook")).literal()
    if not name:
        raise ReadingIssue("hook_name", "A hook name must be established and nonempty")
    label = command.argument("label")
    label = (expand_literal_argument(host, label).literal() if label is not None
             else host.options.name if host.options is not None else "top-level")
    state = host.context.hooks
    if command.action == "hook_register":
        state.add(name, command.argument("body").tokens, host.uncertainty_origin(command.span), label=label)
    elif command.action == "hook_remove":
        state.remove(name, label=label)
    elif command.action == "hook_unresolved":
        state.invalidate(name, host.uncertainty_origin(command.span))
    elif command.action == "hook_use":
        from .programs import evaluate
        for body in state.bodies(name):
            evaluate(host, body.tokens, command.span)
    return replace(command, metadata={**command.metadata, "hook": name, "label": label,
        "hook_version": host.context.hooks.version})


FAMILY = OperationFamily((ExecutableOperation[EffectiveReadingProfile](
    "kernel.file_hook", ExpansionKind.INTERNAL, execute, continuation=True),))
