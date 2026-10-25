"""Bounded, non-expanding scanners for source-visible reading assignments."""
from .argument_scanner import ArgumentScanner
from .contracts import ReadingIssue, ScannedArgument, SourceCommand
from .tex_reader import CatCode, TokenKind


class AssignmentScanner(ArgumentScanner):
    """Decimal/backtick catcodes; computed values remain explicit boundaries.

    The final decimal must end at space, relax or EOF. Other terminators need
    TeX's frozen token pushback/expansion rules and are not guessed here.
    """

    def let(self, opening, profile):
        """TeX82 prefixed_command/let: get_r_token, optional equals, one donor.

        Neither operand is expanded. After an equals TeX consumes at most one
        space token (the mouth has already coalesced ordinary source spaces).
        """
        with self.context.argument_scanning():
            target = self.next_nonspace()
            if target is None or target.kind not in {TokenKind.CONTROL_SEQUENCE, TokenKind.ACTIVE_CHARACTER}:
                raise ReadingIssue("assignment_target", "let needs a control sequence or active-character target")
            donor = self.next_nonspace()
            if donor is not None and donor.kind == TokenKind.CHARACTER and donor.value == "=" and donor.catcode == CatCode.OTHER:
                donor = self.reader.next_token()
                if donor is not None and donor.catcode == CatCode.SPACE:
                    donor = self.reader.next_token()
            if donor is None:
                raise ReadingIssue("assignment_donor", "EOF before the let donor token")
        return SourceCommand(self.reader.source_span(opening.start, self.reader.position), profile.name,
            "meaning_assignment", tuple(ScannedArgument(name, t.span, (t,), "data")
                                        for name, t in (("target", target), ("donor", donor))))

    @staticmethod
    def _digit(token):
        return (token is not None and token.kind == TokenKind.CHARACTER
                and token.catcode == CatCode.OTHER and token.value in "0123456789")

    def integer_parameter(self, opening, profile):
        """Literal integer parameter assignment, with no expansion or pushback."""
        with self.context.argument_scanning():
            checkpoint = self.reader.checkpoint()
            token = self.next_nonspace()
            if not (token is not None and token.kind == TokenKind.CHARACTER
                    and token.catcode == CatCode.OTHER and token.value == "="):
                self.reader.restore(checkpoint)
            sign = 1
            while True:
                checkpoint = self.reader.checkpoint()
                token = self.next_nonspace()
                if token is not None and token.kind == TokenKind.CHARACTER and token.catcode == CatCode.OTHER and token.value in "+-":
                    sign *= -1 if token.value == "-" else 1
                else:
                    self.reader.restore(checkpoint)
                    break
            value = sign * self._integer()
            if abs(value) > 2147483647:
                raise ReadingIssue("invalid_assignment", "Integer parameter value exceeds TeX's range")
            token = self._peek()
            if token is not None:
                if token.catcode == CatCode.SPACE:
                    self.reader.next_token()
                else:
                    raise ReadingIssue("assignment_terminator", "Literal integer assignment needs space or EOF")
        return SourceCommand(self.reader.source_span(opening.start, self.reader.position), profile.name,
                             "layout_assignment", metadata={"value": value, "source_reference": profile.tex_mechanics["source_reference"]})

    def _integer(self, *, character=False):
        token = self.next_nonspace()
        if (character and token is not None and token.kind == TokenKind.CHARACTER
                and token.catcode == CatCode.OTHER and token.value == "`"):
            token = self.reader.next_token()
            if token is None or len(token.value) != 1:
                raise ReadingIssue("computed_assignment", "Backtick requires one character or control symbol")
            return ord(token.value)
        digits = []
        while self._digit(token):
            digits.append(token.value)
            if not self._digit(self._peek()):
                break
            token = self.reader.next_token()
        if not digits:
            raise ReadingIssue("computed_assignment", "Expected a non-expanding decimal number")
        return int("".join(digits))

    def catcode(self, opening, profile):
        with self.context.argument_scanning():
            character = self._integer(character=True)
            checkpoint = self.reader.checkpoint()
            token = self.next_nonspace()
            if not (token is not None and token.kind == TokenKind.CHARACTER
                    and token.catcode == CatCode.OTHER and token.value == "="):
                self.reader.restore(checkpoint)
            category = self._integer()
            token = self._peek()
            if token is not None:
                if token.catcode == CatCode.SPACE:
                    self.reader.next_token()
                elif token.kind == TokenKind.CONTROL_SEQUENCE and token.value == "relax" and self.context.lookup_definition("relax") is None:
                    self.reader.next_token()
                else:
                    raise ReadingIssue("assignment_terminator", "Assignment needs space, relax or EOF; token pushback requires further resolution")
            if not 0 <= character <= 0x10FFFF or not 0 <= category <= 15:
                raise ReadingIssue("invalid_assignment", "Character or category number is out of range")
        return SourceCommand(self.reader.source_span(opening.start, self.reader.position),
                             profile.name, "reading_assignment", (),
                             {"character": chr(character), "category": category})
