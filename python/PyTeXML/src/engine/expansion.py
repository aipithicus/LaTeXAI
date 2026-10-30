"""Bounded expansion over lazy source input and frozen replacement tokens.

The cursor owns input continuation, not meanings or execution state. Tokens keep
their original source spans and categories even when one argument crosses frames.
This module never serializes tokens as TeX or dispatches an executable command.
"""
from dataclasses import dataclass, replace
from .primitive import PrimitiveMeaning

from ..reading.contracts import (BoundMeaning, CharacterCodeMeaning, CommandDefinition,
                                 ReadingIssue, StoredDefinition,
                                 UncertainMeaning, TokenListMeaning, UndefinedMeaning)
from ..reading.tex_reader import CatCode, Token, TokenKind


@dataclass(frozen=True, slots=True)
class TokenListInsertion:
    """A the_toks result, copied by scan_toks but expanded in ordinary input.

    This is an ephemeral expansion result, not a flag on stored tokens. The
    consuming scan decides whether to copy it; nested scans do not inherit that
    decision. Tokens retain their original categories and occurrence spans.
    """
    tokens: tuple[Token, ...]


@dataclass(frozen=True, slots=True)
class MacroCall:
    invocation: Token
    definition: StoredDefinition
    arguments: tuple[tuple[Token, ...], ...]


class ExpansionCursor:
    def __init__(self, source, context, knowledge, operations, *, budget=10000, relaxed_target=None, host=None, protect_macros=False):
        if type(budget) is not int or budget <= 0:
            raise ValueError("Expansion requires a positive work budget")
        self.source, self.context, self.knowledge, self.operations = source, context, knowledge, operations
        self.host = host
        self.protect_macros = protect_macros
        self.remaining = budget
        self.frames = []
        self.source_tokens = []
        self.calls = []
        self._last = None
        self._last_from_source = False
        self.suppressed = False
        self.relaxed_target = relaxed_target
        self._depth = 0
        self.optional_return_used = False

    def optional_at_eof(self):
        boundary = getattr(self.source, "return_continuation", None)
        if boundary is None or not boundary.next_token_is_control_sequence:
            return False
        # Flattening must preserve the raw lookahead barrier. A current relax
        # meaning gives preparation a source-backed, side-effect-free spelling.
        from .input_boundaries import require_inert_barrier
        require_inert_barrier(self.context, self.knowledge)
        self.optional_return_used = True
        return True

    def push(self, tokens):
        tokens = tuple(tokens)
        if tokens:
            self.frames.append((tokens, 0))

    def _charge(self, amount=1):
        if amount > self.remaining:
            self.remaining = 0
            raise ReadingIssue("expansion_budget", "Expansion exhausted its work budget")
        self.remaining -= amount

    def next_token(self):
        self._charge()
        while self.frames:
            tokens, index = self.frames[-1]
            if index == len(tokens):
                self.frames.pop()
                continue
            self.frames[-1] = tokens, index + 1
            self._last = tokens[index]
            self._last_from_source = False
            return self._last
        token = self.source.next_token()
        if token is not None:
            self.source_tokens.append(token)
        self._last = token
        self._last_from_source = True
        return token

    def unread_token(self, token):
        if token is None or token is not self._last:
            raise ValueError("Only the last expansion token can be put back")
        if self._last_from_source:
            self.source.unread_token(token)
            self.source_tokens.pop()
        else:
            self.push((token,))
        self._last = None
        self._last_from_source = False

    def checkpoint(self):
        return (self.source.checkpoint(), tuple(self.frames), tuple(self.source_tokens), len(self.calls),
                self._last, self._last_from_source, self.suppressed)

    def restore(self, saved):
        source, frames, consumed, calls, self._last, self._last_from_source, self.suppressed = saved
        self.source.restore(source)
        self.frames = list(frames)
        self.source_tokens = list(consumed)
        del self.calls[calls:]
        # Work already attempted still counts against the evaluation budget.

    @property
    def pending(self):
        return any(index < len(tokens) for tokens, index in self.frames)

    def expand_macro(self, token, definition, *, execution=False):
        if isinstance(definition, CommandDefinition):
            raise ReadingIssue('declaration_observation', 'A declaration capture is not an executable meaning')
        from .macro_arguments import arguments as scan_arguments
        arguments = scan_arguments(self, token, definition)
        replacement, index = [], 0
        body = definition.replacement_tokens
        self._charge(len(body))
        while index < len(body):
            part = body[index]
            index += 1
            if part.catcode != CatCode.PARAMETER:
                replacement.append(part)
                continue
            if index == len(body):
                raise ReadingIssue("invalid_definition_parameter", "Missing replacement parameter")
            following = body[index]
            index += 1
            if following.catcode == CatCode.PARAMETER:
                replacement.append(following)
            elif (following.catcode == CatCode.OTHER and following.value in "123456789"
                  and int(following.value) <= len(arguments)):
                argument = arguments[int(following.value) - 1]
                # Charge duplication before allocating the replacement. Reading
                # input alone would not bound a large, repeatedly substituted arg.
                self._charge(len(argument))
                replacement.extend(argument)
            else:
                raise ReadingIssue("invalid_definition_parameter", "Invalid replacement parameter")
        if definition.hash_brace is not None:
            replacement.append(definition.hash_brace)
        self.calls.append(MacroCall(token, definition, arguments))
        self.push(replacement)

    def expand_once(self, token, *, stop=None, stop_operation=None):
        """Expand one token once, or return an unexpanded token to the consumer."""
        if token.kind == TokenKind.CHARACTER:
            return token
        if self.relaxed_target == (token.kind, token.value):
            return token
        meaning = self.context.resolve_meaning(self.knowledge, token.value, token.kind)
        uncertain = meaning.span if isinstance(meaning, UncertainMeaning) else getattr(meaning, "uncertain", None)
        if uncertain is not None:
            raise ReadingIssue("uncertain_meaning", f"Expansion depends on {token.value!r}", causes=(uncertain,))
        if isinstance(meaning, UndefinedMeaning):
            raise ReadingIssue("undefined_control_sequence", f"{token.value!r} is established undefined")
        if isinstance(meaning, StoredDefinition):
            if meaning.protected and self.protect_macros:
                return token
            self.expand_macro(token, meaning)
            return None
        if isinstance(meaning, TokenListMeaning):
            self._charge(len(meaning.replacement_tokens))
            self.push(meaning.replacement_tokens)
            return None
        if isinstance(meaning, CharacterCodeMeaning) or (isinstance(meaning, BoundMeaning) and meaning.token is not None):
            return token
        if isinstance(meaning, PrimitiveMeaning):
            operation = self.operations.get(meaning.operation)
            if operation is not None:
                if stop_operation is not None and stop_operation(operation):
                    return token
                if operation.expansion is not None:
                    if self._depth >= 100:
                        raise ReadingIssue("expansion_budget", "Expansion nesting exhausted its work budget")
                    self._depth += 1
                    try:
                        result = operation.expansion(self, token, meaning)
                        if isinstance(result, TokenListInsertion):
                            self._charge(len(result.tokens))
                        return result
                    finally:
                        self._depth -= 1
                if operation.unexpandable:
                    return token
        elif isinstance(meaning, BoundMeaning) and meaning.profile is not None:
            if stop is not None and stop(meaning.profile):
                return token
        raise ReadingIssue("expansion_required", f"No established expansion behavior for {token.value!r}")

    def next_expanded(self, *, stop=None, stop_operation=None, copy_token_lists=False):
        """Return a token, or a whole insertion to an expanded-list consumer.

        A parameter-number scan uses the default get_x_token behavior even
        inside an edef; it must not copy an insertion past parameter validation.
        """
        self.suppressed = False
        while (token := self.next_token()) is not None:
            if token.expansion_suppressed:
                self.suppressed = True
                return replace(token, expansion_suppressed=False)
            result = self.expand_once(token, stop=stop, stop_operation=stop_operation)
            if isinstance(result, TokenListInsertion):
                if copy_token_lists:
                    return result
                self.push(result.tokens)
                continue
            if result is not None:
                return result
        return None
