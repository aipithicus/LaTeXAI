r"""
Semantic pruning for LaTeX documents.

Capabilities:
  - Stack-based evaluation of \iftrue and \iffalse conditional trees.
  - Linear balanced-brace macro stripping (\todo{...}, \note{...}).
  - Environment stripping (\begin{comment}...\end{comment}, draft blocks).
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple


def simplify_conditionals(text: str) -> str:
    """
    Evaluates nested \\iftrue / \\iffalse conditional blocks.
    Prunes dead branches while preserving unknown conditionals (\\ifx, \\ifdim, etc.).
    """
    pattern = re.compile(r"(\\(?:iftrue|iffalse|if0|if1|else|fi))\b")
    tokens = list(pattern.finditer(text))
    if not tokens:
        return text

    stack: List[Tuple[str, int, int, Optional[Tuple[int, int]]]] = []
    deletions: List[Tuple[int, int]] = []

    for m in tokens:
        tag = m.group(1)
        if tag in (r"\iftrue", r"\if1"):
            stack.append(("iftrue", m.start(), m.end(), None))
        elif tag in (r"\iffalse", r"\if0"):
            stack.append(("iffalse", m.start(), m.end(), None))
        elif tag == r"\else":
            if stack:
                kind, s_start, s_end, _ = stack.pop()
                stack.append((kind, s_start, s_end, (m.start(), m.end())))
        elif tag == r"\fi":
            if stack:
                kind, s_start, s_end, else_pos = stack.pop()
                fi_start, fi_end = m.start(), m.end()
                if kind == "iftrue":
                    # Keep 'then' block; delete \iftrue, and delete \else...\fi if present
                    deletions.append((s_start, s_end))
                    if else_pos:
                        deletions.append((else_pos[0], fi_end))
                    else:
                        deletions.append((fi_start, fi_end))
                elif kind == "iffalse":
                    # Delete 'then' block; keep 'else' block if present
                    if else_pos:
                        deletions.append((s_start, else_pos[1]))
                        deletions.append((fi_start, fi_end))
                    else:
                        deletions.append((s_start, fi_end))

    # Nested dead branches produce overlapping original-source intervals.
    # Merge them before slicing so inner edits cannot shift an outer endpoint.
    merged: List[Tuple[int, int]] = []
    for start, end in sorted(deletions):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        text = text[:start] + text[end:]

    return text


def strip_environment(text: str, env_name: str) -> str:
    """Removes \\begin{env_name}...\\end{env_name} environments."""
    escaped = re.escape(env_name)
    pat = re.compile(r"\\begin\{" + escaped + r"\}[\s\S]*?\\end\{" + escaped + r"\}")
    return pat.sub("", text)


def strip_macro_with_args(text: str, macro_name: str, keep_content: bool = False) -> str:
    """
    Strips \\macro{...} or \\macro[...]{...} with arbitrary nested curly braces.
    If keep_content=True, replaces the macro with its inner mandatory argument.
    """
    target = f"\\{macro_name}"
    idx = 0
    out = []
    text_len = len(text)

    while idx < text_len:
        m_pos = text.find(target, idx)
        if m_pos == -1:
            out.append(text[idx:])
            break

        # Check token boundary: character after target must not be alphabetic
        boundary_idx = m_pos + len(target)
        if boundary_idx < text_len and text[boundary_idx].isalpha():
            out.append(text[idx:boundary_idx])
            idx = boundary_idx
            continue

        out.append(text[idx:m_pos])
        cur = boundary_idx

        # Skip optional argument [...]
        while cur < text_len and text[cur].isspace():
            cur += 1
        if cur < text_len and text[cur] == "[":
            depth = 1
            cur += 1
            while cur < text_len and depth > 0:
                if text[cur] == "[":
                    depth += 1
                elif text[cur] == "]":
                    depth -= 1
                cur += 1

        # Match mandatory argument {...}
        while cur < text_len and text[cur].isspace():
            cur += 1

        if cur < text_len and text[cur] == "{":
            depth = 1
            arg_start = cur + 1
            cur += 1
            while cur < text_len and depth > 0:
                if text[cur] == "{":
                    depth += 1
                elif text[cur] == "}":
                    depth -= 1
                cur += 1

            if keep_content:
                out.append(text[arg_start:cur - 1])
            idx = cur
        else:
            idx = cur

    return "".join(out)


def prune_latex(
    text: str,
    drop_commands: Optional[List[str]] = None,
    keep_content_commands: Optional[List[str]] = None,
    drop_environments: Optional[List[str]] = None
) -> str:
    """
    Executes full semantic pruning:
      1. Conditionals (\\iftrue / \\iffalse dead branches)
      2. Environments (comment, draft, etc.)
      3. Macros to delete (\\todo{}, \\note{}, etc.)
      4. Markup macros to unwrap while preserving text (\\blue{text} -> text)
    """
    if drop_commands is None:
        drop_commands = ["todo", "todonotes", "note", "comment"]
    if keep_content_commands is None:
        keep_content_commands = []
    if drop_environments is None:
        drop_environments = ["comment", "draft"]

    # 1. Conditionals
    text = simplify_conditionals(text)

    # 2. Environments
    for env in drop_environments:
        text = strip_environment(text, env)

    # 3. Drop commands completely
    for cmd in drop_commands:
        text = strip_macro_with_args(text, cmd, keep_content=False)

    # 4. Unwrap formatting/markup commands
    for cmd in keep_content_commands:
        text = strip_macro_with_args(text, cmd, keep_content=True)

    return text



def prune_latex_provenance(
    lines: List[Any],
    drop_commands: Optional[List[str]] = None,
    keep_content_commands: Optional[List[str]] = None,
    drop_environments: Optional[List[str]] = None
) -> Tuple[List[Any], List[Any]]:
    """
    Executes semantic pruning on a list of SourceLine objects,
    using line-sequence alignment to track deleted lines in tombstones.
    """
    import difflib
    from .provenance import SourceLine, Tombstone

    orig_text = "".join(l.text for l in lines)
    pruned_text = prune_latex(
        orig_text,
        drop_commands=drop_commands,
        keep_content_commands=keep_content_commands,
        drop_environments=drop_environments
    )

    if pruned_text == orig_text:
        return lines, []

    orig_line_texts = [l.text for l in lines]
    pruned_line_texts = pruned_text.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, orig_line_texts, pruned_line_texts)
    out_lines: List[Any] = []
    tombstones: List[Any] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for idx in range(i1, i2):
                out_lines.append(lines[idx])
        elif tag == "delete":
            for idx in range(i1, i2):
                l = lines[idx]
                tombstones.append(Tombstone(l.src_file, l.src_line, l.src_line, "PRUNED_SEMANTIC", "Pruned conditional or draft macro"))
        elif tag == "replace":
            for idx in range(i1, i2):
                l = lines[idx]
                tombstones.append(Tombstone(l.src_file, l.src_line, l.src_line, "PRUNED_SEMANTIC", "Replaced during pruning"))
            for jdx in range(j1, j2):
                ref_line = lines[i1]
                out_lines.append(SourceLine(pruned_line_texts[jdx], ref_line.src_file, ref_line.src_line, "PRUNED_SEMANTIC"))
        elif tag == "insert":
            ref_line = lines[i1] if i1 < len(lines) else lines[-1]
            for jdx in range(j1, j2):
                out_lines.append(SourceLine(pruned_line_texts[jdx], ref_line.src_file, ref_line.src_line, "PRUNED_SEMANTIC"))

    return out_lines, tombstones
