"""Math list construction before noad conversion and font measurement."""
from ..content import Frame
from ..dimensions import dimension
from ..integers import IntegerScanner
from ..operations import ExpansionKind, OperationFamily, PrimitiveOperation
from ..primitive import PrimitiveMeaning
from .content import owner, result
from ...reading.contracts import ReadingIssue
from ...reading.tex_reader import CatCode, TokenKind


def delimiter(scanner, *, radical=False):
    from .code_tables import read
    if radical:
        value = scanner.integer()
    else:
        token = scanner._nonspace()
        if token is None:
            raise ReadingIssue("math_delimiter", "Missing delimiter")
        if token.kind == TokenKind.CHARACTER and token.catcode in {CatCode.LETTER, CatCode.OTHER}:
            value = read(scanner.host.context, "delcode", ord(token.value))
        else:
            meaning = scanner.host.context.resolve_meaning(scanner.host.knowledge, token.value, token.kind)
            if not isinstance(meaning, PrimitiveMeaning) or meaning.uncertain is not None or meaning.operation != "content.math" or meaning.operand != "delimiter":
                raise ReadingIssue("math_delimiter", "Expected a delimiter character or delimiter primitive")
            value = scanner.integer() % (1 << 24)
    if not 0 <= value <= 0xffffff:
        raise ReadingIssue("math_delimiter", "Delimiter code is absent or outside the 24-bit range")
    return value


def execute(host, opening, meaning):
    content, command, span = owner(host), meaning.operand, opening.span
    if content.frame.mode != "m":
        raise ReadingIssue("content_mode", "This operation requires math mode")
    scanner = IntegerScanner(host)
    if command == "mathchar":
        code = scanner.integer()
        scanner.finish()
        content.math_character(host, code, span)
    elif command == "delimiter":
        code = scanner.integer()
        if not 0 <= code < (1 << 27):
            raise ReadingIssue("math_delimiter", "delimiter requires a 27-bit code")
        scanner.finish()
        content.math_character(host, ((code >> 24) << 12) + ((code >> 12) & 0xfff), span)
    elif command in {"mathord", "mathop", "mathbin", "mathrel", "mathopen", "mathclose", "mathpunct", "mathinner", "overline", "underline"}:
        content.scan_field(host, span, ("class", command[4:] if command.startswith("math") else command))
    elif command in {"limits", "nolimits", "displaylimits"}:
        nodes = content.frame.nodes
        if not nodes or nodes[-1].kind != "noad" or nodes[-1].get("class_") != "op":
            raise ReadingIssue("math_limits", "Limits modifier requires an operator atom")
        nodes[-1] = nodes[-1].with_value("limits", command)
    elif command in {"displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle"}:
        content.emit(content.node(host, "style", span, value=command[:-5]))
    elif command in {"over", "atop", "above"}:
        if "numerator" in content.frame.info:
            raise ReadingIssue("ambiguous_fraction", "A math group cannot contain two fraction separators")
        thickness = dimension(scanner)[0] if command == "above" else 0 if command == "atop" else "default"
        scanner.finish()
        content.frame.info.update(numerator=tuple(content.frame.nodes), thickness=thickness)
        content.frame.nodes.clear()
    elif command in {"left", "right"}:
        code = delimiter(scanner)
        scanner.finish()
        if command == "left":
            host.begin_group("content:left", span)
            content.frames.append(Frame("left", "m", span, info={"left": code}))
        else:
            if content.frame.kind != "left":
                raise ReadingIssue("math_delimiter", "right has no matching left")
            content.frame.info["right"] = code
            content.close(host, span)
    elif command in {"radical", "mathaccent"}:
        code = delimiter(scanner, radical=True) if command == "radical" else scanner.integer()
        if command == "mathaccent" and not 0 <= code <= 32767:
            raise ReadingIssue("math_character", "Math accent requires a 15-bit code")
        scanner.finish()
        content.scan_field(host, span, ("class", "radical" if command == "radical" else "accent", code))
    elif command == "mathchoice":
        content.require_field_group(host, span, ("choice", ()))
    return result(host, opening)


MATH = PrimitiveOperation("content.math", ExpansionKind.UNEXPANDABLE, execute, operand_type=str)
FAMILY = OperationFamily((MATH,), tuple(MATH.declare(k, k) for k in
    "mathchar delimiter mathord mathop mathbin mathrel mathopen mathclose mathpunct mathinner limits nolimits displaylimits displaystyle textstyle scriptstyle scriptscriptstyle over atop above left right radical mathaccent mathchoice overline underline".split()))
