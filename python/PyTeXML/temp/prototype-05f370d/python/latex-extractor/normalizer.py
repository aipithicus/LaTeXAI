r"""
Knuth Reader State Machine & Non-Mutating Whitespace Normalizer for LaTeX.

Architecture:
  - Non-Mutating Protected Zones: Identifies verbatim and code blocks as immutable lines.
  - Zero Mutation: Protected lines are passed through completely untouched (no sentinel placeholders).
  - Complementary Set Processing: Normalization and Knuth FSM operations are strictly confined
    to the complementary set of non-verbatim lines.
  - Inline Protection: Within complementary lines, inline \verb|...| and \url{...} spans are
    protected from comment stripping and inner space compaction.
  - Escaped \%: Recognized directly via backslash parity without sentinel injection.
  - Text normalization: Universal LF, preservation of decoded Unicode,
    trailing space trimming, and canonical paragraph break capping (\n{3,} -> \n\n).
  - Provenance Tracking: Supports line-level tracking via SourceLine and Tombstone.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

try:
    from .provenance import SourceLine, Tombstone
except ImportError:
    from provenance import SourceLine, Tombstone  # type: ignore

BLOCK_VERBATIM_START_RE = re.compile(
    r"\\begin\{(?:verbatim|Verbatim|lstlisting|minted|alltt|filecontents\*?)\*?\}",
    re.IGNORECASE
)
BLOCK_VERBATIM_END_RE = re.compile(
    r"\\end\{(?:verbatim|Verbatim|lstlisting|minted|alltt|filecontents\*?)\*?\}",
    re.IGNORECASE
)

INLINE_VERB_RE = re.compile(r"\\verb\*?(?P<delim>[^\w\s])(?:(?!\1).)*\1")
URL_RE = re.compile(r"\\url\{[^}]*\}")


def knuth_normalize_provenance(
    lines: List[SourceLine]
) -> Tuple[List[SourceLine], List[Tombstone]]:
    """
    Executes Knuth reader state machine and whitespace normalization on a list
    of SourceLine objects, tracking provenance and recording dropped lines in tombstones.
    """
    is_protected_line = [False] * len(lines)
    in_block = False

    for idx, l in enumerate(lines):
        t = l.text
        if not in_block:
            if BLOCK_VERBATIM_START_RE.search(t):
                in_block = True
                is_protected_line[idx] = True
        else:
            is_protected_line[idx] = True
            if BLOCK_VERBATIM_END_RE.search(t):
                in_block = False

    output_lines: List[SourceLine] = []
    tombstones: List[Tombstone] = []
    comment_pending_state_n = False

    for idx, l in enumerate(lines):
        # 1. Protected block lines: zero touch
        if is_protected_line[idx]:
            l.op = "PROTECTED"
            output_lines.append(l)
            comment_pending_state_n = False
            continue

        # Encoding and character repair require separate diagnostics and policy.
        # Valid Unicode, including invisible characters and literal spelling,
        # must not disappear as a side effect of whitespace normalization.
        line = l.text

        # Knuth State N: eat leading whitespace if following a swallowed comment
        if comment_pending_state_n:
            stripped = line.lstrip(" \t")
            if stripped in ("\n", ""):
                # The preceding comment swallowed its newline. Terminate that
                # physical line before emitting the empty line that means \par.
                if output_lines and not output_lines[-1].text.endswith("\n"):
                    output_lines[-1].text += "\n"
                l.text = "\n"
                output_lines.append(l)
                comment_pending_state_n = False
                continue
            line = stripped
            l.op = "KNUTH_STATE_N"

        # Identify inline protected spans (\verb|...| and \url{...})
        inline_spans: List[Tuple[int, int]] = []
        for m in INLINE_VERB_RE.finditer(line):
            inline_spans.append((m.start(), m.end()))
        for m in URL_RE.finditer(line):
            inline_spans.append((m.start(), m.end()))

        # Locate true comment '%'
        comm_idx = -1
        for i, ch in enumerate(line):
            if ch == "%":
                if any(s <= i < e for s, e in inline_spans):
                    continue
                bs_count = 0
                k = i - 1
                while k >= 0 and line[k] == "\\":
                    bs_count += 1
                    k -= 1
                if bs_count % 2 == 0:
                    comm_idx = i
                    break

        if comm_idx != -1:
            code_part = line[:comm_idx]
            if re.search(r"\\[a-zA-Z@]+$", code_part):
                code_part += " "


            if code_part.strip():
                if inline_spans:
                    code_part = _compact_inner_spaces_preserving_spans(code_part, inline_spans)
                else:
                    code_part = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", code_part)

                l.text = code_part
                l.op = "STRIP_COMMENT"
                output_lines.append(l)
                comment_pending_state_n = True
            else:
                tombstones.append(Tombstone(l.src_file, l.src_line, l.src_line, "STRIP_COMMENT", "Comment line stripped"))
                comment_pending_state_n = True
        else:
            if inline_spans:
                line_proc = _compact_inner_spaces_preserving_spans(line, inline_spans)
            else:
                line_proc = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", line)

            l.text = line_proc.rstrip(" \t\r\n") + "\n"
            output_lines.append(l)
            comment_pending_state_n = False

    # Phase 3: Paragraph Break Capping (max-blank-1: consecutive blanks capped at 1, '\n\n')
    final_lines: List[SourceLine] = []
    consecutive_blanks = 0
    for l in output_lines:
        if l.op == "PROTECTED":
            consecutive_blanks = 0
            final_lines.append(l)
            continue

        if l.text == "\n":
            consecutive_blanks += 1
            if consecutive_blanks <= 1:
                final_lines.append(l)
            else:
                tombstones.append(Tombstone(l.src_file, l.src_line, l.src_line, "COMPACT_WS", "Excess blank line collapsed"))
        else:
            consecutive_blanks = 0
            final_lines.append(l)

    return final_lines, tombstones


def knuth_normalize(text: str) -> str:
    """
    Executes Knuth's TeX Reader State Machine and whitespace normalization
    by partitioning the document into protected blocks (verbatim/code) and
    applying operations strictly to the complementary set of lines.
    """
    clean_text = re.sub(r"\r\n|[\r\x0b\x0c\x85\u2028\u2029]", "\n", text)
    raw_lines = clean_text.splitlines(keepends=True)
    source_lines = [SourceLine(text=line, src_file="document.tex", src_line=i) for i, line in enumerate(raw_lines, start=1)]

    normalized_lines, _ = knuth_normalize_provenance(source_lines)
    assembled = "".join(l.text for l in normalized_lines)
    return assembled.strip() + "\n"


def _compact_inner_spaces_preserving_spans(
    line: str,
    protected_spans: List[Tuple[int, int]]
) -> str:
    r"""
    Compacts multiple spaces between tokens on a complementary line,
    while leaving protected inline spans (\verb, \url) completely untouched.
    """
    parts: List[str] = []
    last = 0
    line_len = len(line)

    for start, end in sorted(protected_spans):
        s = min(start, line_len)
        e = min(end, line_len)
        if s > last:
            parts.append(re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", line[last:s]))
        if s < e:
            parts.append(line[s:e])
        last = e

    if last < line_len:
        parts.append(re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", line[last:]))

    return "".join(parts)
