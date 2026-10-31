"""Parse bounded TeX observations; macro calls and emitted nodes remain separate.

Command reports show current command/operand meanings, not source aliases.
The records retain log line numbers. This is not a causal trace reconstructor.
"""
import re


NODE = re.compile(r"^([.^_/DTSs|\\]*)(\\.*|\{\})$")
METADATA = re.compile(r"^(?:spacefactor |prevdepth |prevgraf |total height |goal height |"
                      r"current page:|recent contributions:|\\box\d+=void$)")


def list_tree(lines, *, issues=None, metadata=None):
    """Read TeX's printed paths, including mathchoice and fraction branches.

    Unknown/abbreviated lines are evidence of an incomplete observation, never
    continuation text silently attached to a preceding node.
    """
    strict = issues is None
    issues = [] if issues is None else issues
    metadata = [] if metadata is None else metadata
    roots, stack = [], []
    for number, line in lines:
        if not line:
            continue
        if (re.match(r"^[.^_/DTSs|\\]*etc\.$", line) or line.endswith(" []")
                or line.endswith("...") or "display aborted" in line or "Unknown node type!" in line):
            issues.append({"line": number, "kind": "truncated_list", "raw": line})
        if METADATA.match(line):
            metadata.append({"line": number, "raw": line})
            continue
        match = NODE.fullmatch(line)
        if not match:
            issues.append({"line": number, "kind": "unrecognized_list_line", "raw": line})
            continue
        path, text = match.groups()
        node = {"path": path, "text": text, "line": number, "children": []}
        while stack and len(stack[-1]["path"]) >= len(path):
            stack.pop()
        if path and (not stack or path[:-1] != stack[-1]["path"]):
            issues.append({"line": number, "kind": "orphan_list_path", "raw": line})
        (stack[-1]["children"] if stack else roots).append(node)
        stack.append(node)
    if strict and issues:
        raise ValueError(f"Incomplete native list dump: {issues}")
    return roots


def parse(log, *, expected_ok=0, marked=True, strict=True, wrap_column=None):
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
    commands, macros, boxes, lists, outcomes, issues = [], [], [], [], [], []
    for number, line in lines:
        if wrap_column and len(line) >= wrap_column:
            issues.append({"line": number, "kind": "possibly_wrapped_record", "raw": line})
        if match := re.fullmatch(r"\{(?:([^{}]+ mode): )?(.+)\}", line):
            if match[2] in {"true", "false"}:
                outcomes.append({"line": number, "value": match[2] == "true"})
            else:
                commands.append({"line": number, "mode": match[1], "command": match[2]})
        elif match := re.match(r"^(\\[^ ]+.*?)\s*->(.*)$", line):
            macros.append({"line": number, "header": match[1], "replacement_head": match[2], "arguments": []})
        elif match := re.match(r"^#([1-9])<-(.*)$", line):
            argument = {"line": number, "parameter": int(match[1]), "text": match[2]}
            if macros:
                macros[-1]["arguments"].append(argument)
            else:
                issues.append({"line": number, "kind": "orphan_macro_argument", "raw": line})
        elif line.startswith("{") and not line.endswith("}"):
            issues.append({"line": number, "kind": "incomplete_command_report", "raw": line})
    body = "\n".join(s for _, s in lines)
    for match in re.finditer(r"^> \\box(\d+)=\n(.*?)(?=\n! OK\.)", body, re.M | re.S):
        start = body[:match.start(2)].count("\n")
        chunk = lines[start:start + len(match[2].splitlines())]
        metadata = []
        boxes.append({"register": int(match[1]), "line": lines[start - 1][0],
                      "nodes": list_tree(chunk, issues=issues, metadata=metadata),
                      "metadata": metadata})
    for match in re.finditer(r"^> \\box(\d+)=void\n(?:\n)?(?=! OK\.)", body, re.M):
        index = body[:match.start()].count("\n")
        boxes.append({"register": int(match[1]), "line": lines[index][0], "nodes": [], "metadata": [], "void": True})
    boxes.sort(key=lambda box: box["line"])
    if len(re.findall(r"^> \\box\d+=", body, re.M)) != len(boxes):
        issues.append({"kind": "unterminated_box_dump"})
    for match in re.finditer(r"^### ([^\n]+)\n(.*?)(?=^### |^! OK\.|\Z)", body, re.M | re.S):
        if not re.search(r"^! OK\.", body[match.end():], re.M):
            issues.append({"kind": "unterminated_list_dump", "mode": match[1]})
        start = body[:match.start(2)].count("\n")
        metadata = []
        lists.append({"mode": match[1], "nodes": list_tree(lines[start:start + len(match[2].splitlines())],
                                                          issues=issues, metadata=metadata), "metadata": metadata})
    if strict and issues:
        raise ValueError(f"Incomplete native observations: {issues}")
    return {"commands": commands, "macro_calls": macros, "boxes": boxes, "lists": lists,
            "conditional_outcomes": outcomes, "issues": issues,
            "raw_lines": [{"line": n, "raw": s} for n, s in lines]}


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
