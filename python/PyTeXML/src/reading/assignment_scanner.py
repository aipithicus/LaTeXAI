"""Bounded, non-expanding scanners for source-visible reading assignments."""
from .argument_scanner import ArgumentScanner
from .contracts import ReadingIssue, SourceCommand
from .tex_reader import CatCode, TokenKind


class AssignmentScanner(ArgumentScanner):
    """Decimal/backtick catcodes; computed values remain explicit boundaries.

    The final decimal must end at space, relax or EOF. Other terminators need
    TeX's frozen token pushback/expansion rules and are not guessed here.
    """

    @staticmethod
    def _digit(token):
        return (token is not None and token.kind == TokenKind.CHARACTER
                and token.catcode == CatCode.OTHER and token.value in "0123456789")

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
