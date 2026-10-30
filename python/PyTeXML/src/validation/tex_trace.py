"""Parse bounded TeX observations; macro calls and emitted nodes remain separate.

Command reports show current command/operand meanings, not source aliases.
The records retain log line numbers. This is not a causal trace reconstructor.
"""
import re


def list_tree(lines):
    roots, stack = [], []
    for number, line in lines:
        if "etc." in line or line.endswith("..."):
            raise ValueError("Truncated native list dump")
        match = re.match(r"^([.^_]*)(\\.*)$", line)
        if not match:
            if line and stack:
                stack[-1]["text"] += line
            continue
        path, text = match.groups()
        node = {"path": path, "text": text, "line": number, "children": []}
        while stack and len(stack[-1]["path"]) >= len(path):
            stack.pop()
        (stack[-1]["children"] if stack else roots).append(node)
        stack.append(node)
    return roots


def parse(log, *, expected_ok=0, marked=True):
    log = log.replace("\r\n", "\n")
    errors = re.findall(r"^! (.*)$", log, re.M)
    if errors != ["OK."] * expected_ok:
        raise ValueError(f"Unexpected native diagnostics: {errors}")
    lines = list(enumerate(log.splitlines(), 1))
    if marked:
        begins = [i for i, (_, s) in enumerate(lines) if s.strip() == "PYTEXML:BEGIN"]
        ends = [i for i, (_, s) in enumerate(lines) if s.strip() == "PYTEXML:END"]
        if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
            raise ValueError("Missing or ambiguous trace markers")
        lines = lines[begins[0] + 1:ends[0]]
    commands, macros, boxes, lists, outcomes = [], [], [], [], []
    for number, line in lines:
        if match := re.fullmatch(r"\{(?:([^{}]+ mode): )?(\\[^{}]+|[^{}]+)\}", line):
            if match[2] in {"true", "false"}:
                outcomes.append({"line": number, "value": match[2] == "true"})
            else:
                commands.append({"line": number, "mode": match[1], "command": match[2]})
        elif match := re.match(r"^(\\[^ ]+.*?)\s*->(.*)$", line):
            macros.append({"line": number, "header": match[1], "replacement_head": match[2]})
    body = "\n".join(s for _, s in lines)
    for match in re.finditer(r"^> \\box(\d+)=\n(.*?)(?=\n! OK\.)", body, re.M | re.S):
        start = body[:match.start(2)].count("\n")
        chunk = lines[start:start + len(match[2].splitlines())]
        boxes.append({"register": int(match[1]), "nodes": list_tree(chunk)})
    for match in re.finditer(r"^### ([^\n]+)\n(.*?)(?=^### |^! OK\.|\Z)", body, re.M | re.S):
        start = body[:match.start(2)].count("\n")
        lists.append({"mode": match[1], "nodes": list_tree(lines[start:start + len(match[2].splitlines())])})
    return {"commands": commands, "macro_calls": macros, "boxes": boxes, "lists": lists, "conditional_outcomes": outcomes}


def differences(expected, actual, path=""):
    """Small structural diff suitable for pinned, normalized observations."""
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict):
        return [diff for key in sorted(expected.keys() | actual.keys())
                for diff in differences(expected.get(key), actual.get(key), path + "/" + str(key))]
    if isinstance(expected, list) and len(expected) == len(actual):
        return [diff for i, (left, right) in enumerate(zip(expected, actual))
                for diff in differences(left, right, path + "/" + str(i))]
    return [] if expected == actual else [{"path": path, "expected": expected, "actual": actual}]
