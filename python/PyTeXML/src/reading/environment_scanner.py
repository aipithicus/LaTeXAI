"""Non-expanding collecting-environment declarations and body token capture.

These scanners never install definitions, dispatch body tokens, trim source or
substitute arguments. The dispatcher owns registration and execution routing.
"""
from .argument_scanner import ArgumentScanner
from .context import ExecutionMode
from .contracts import (CollectedEnvironment, EnvironmentDefinition, ReadingIssue,
                        ScannedArgument, StateManagementRule)
from .definition_scanner import DefinitionScanner
from .tex_reader import CatCode, TokenKind


class EnvironmentScanner:
    def __init__(self, reader, context):
        self.reader, self.context = reader, context

    @staticmethod
    def _require(condition, reason, detail):
        if not condition:
            raise ReadingIssue(reason, detail)

    def definition(self, start, profile):
        reader, context = self.reader, self.context
        self._require(context.mode == ExecutionMode.ACTIVE_EXECUTION
                      and reader.catcodes is context.catcodes and reader.endline_char == context.endlinechar,
                      "inactive_context", "Declaration requires a shared active reading context")
        self._require(profile.family == "collected_environment_definition"
                      and profile.grammar.get("handler") == "collected_environment_definition"
                      and profile.grammar.get("expansion") == "none"
                      and profile.state_management == StateManagementRule(),
                      "unsupported_definition", "Collecting declarations require a local non-expanding recipe")
        args, definitions = ArgumentScanner(reader, context), DefinitionScanner(reader, context)
        recipe = profile.tex_mechanics
        with context.stored_definition():
            name_argument = args.group("name")
            name = name_argument.literal()
            self._require(name and not any(c.isspace() or c in "\\{}" for c in name),
                          "environment_name", "Environment requires a literal nonempty name")
            self._require(name not in profile.grammar["forbidden_names"]
                          and not any(name.startswith(p) for p in profile.grammar["forbidden_prefixes"]),
                          "environment_name", "Environment name is reserved by this declaration recipe")
            count_argument, count, default = definitions.signature()
            opening = args.next_nonspace()
            self._require(opening is not None and opening.catcode == CatCode.BEGIN_GROUP,
                          "argument_required", "Environment processing code must be braced")
            body, closing = definitions.read_body(count)
            final = args.group("final_code", optional=True)
            # Final code defines a parameterless end command. Do not compile ##.
            if final is not None:
                self.validate_final(final)
            explicit_end = reader.position
        body_setting = context.lookup_capture_setting(recipe["body_name_setting"])
        body_name = body_setting.tokens[0].value if body_setting is not None else recipe["default_body_name"]
        if final is None:
            final = context.lookup_capture_setting(recipe["final_code_setting"])
        span = reader.source_span
        return EnvironmentDefinition(
            span=span(start, explicit_end), opening=span(start, opening.span.end),
            body=span(opening.span.end, closing.span.start), closing=span(closing.span.start, explicit_end),
            name_argument=name_argument, argument_count=count_argument, parameter_count=count,
            optional_default=default, body_tokens=body, final_code=final, body_name=body_name,
            default_final_commands=tuple(recipe["default_final_commands"]) if final is None else (),
            collector=dict(recipe["collector"]), declaration=profile.name,
            target_requirement=profile.grammar["target_requirement"], binding_id=profile.binding_id)

    @staticmethod
    def validate_final(argument):
        tokens = iter(argument.tokens)
        for token in tokens:
            if token.catcode == CatCode.PARAMETER:
                following = next(tokens, None)
                if following is None or following.catcode != CatCode.PARAMETER:
                    raise ReadingIssue("invalid_definition_parameter", "Final code requires doubled parameter markers")

    def collect(self, opening, definition):
        """Collect the entire invocation before any argument or body interpretation.

        Delimited TeX argument scanning hides begin/end tokens inside groups.
        At group depth zero every literal begin increments the nesting count;
        every end decrements it. Only the outer closing name is checked, matching
        the collector rather than pretending to validate nested environments.
        """
        reader, context = self.reader, self.context
        recipe = definition.collector
        self._require(recipe["handler"] == "balanced_environment_tokens",
                      "unsupported_environment_collector", "No token collector for this recipe")
        begin, end = recipe["begin_command"], recipe["end_command"]
        body_start = reader.position
        tokens, depth, nesting = [], 0, 1
        with context.argument_scanning():
            while (token := reader.next_token()) is not None:
                if token.catcode == CatCode.BEGIN_GROUP:
                    depth += 1
                elif token.catcode == CatCode.END_GROUP:
                    depth -= 1
                    self._require(depth >= 0, "unclosed_environment", "Collected body crosses an unmatched closing group")
                if depth == 0 and token.kind == TokenKind.CONTROL_SEQUENCE and token.value in (begin, end):
                    if token.value == begin:
                        nesting += 1
                        tokens.append(token)
                        continue
                    argument, envelope = self._end_name()
                    nesting -= 1
                    if nesting == 0:
                        self._require(argument.literal() == definition.name, "mismatched_environment",
                                      f"Collected environment {definition.name!r} has a different closing name")
                        span = reader.source_span
                        return CollectedEnvironment(
                            span(opening.start, reader.position), "environment_interpretation",
                            f"Collected {definition.name!r}; arguments, processing code, body substitution and final code remain unexecuted",
                            tuple(tokens), binding_id=definition.binding_id, name=definition.name,
                            opening=span(opening.start, body_start), body=span(body_start, token.span.start),
                            closing=span(token.span.start, reader.position), definition_id=definition.unit_id)
                    tokens.append(token)
                    tokens.extend(envelope)
                else:
                    tokens.append(token)
        raise ReadingIssue("unclosed_environment", f"EOF while collecting {definition.name!r}")

    def _end_name(self):
        """Read a bounded braced end argument, retaining every envelope token."""
        reader = self.reader
        envelope = []
        token = reader.next_token()
        while token is not None and token.catcode == CatCode.SPACE:
            envelope.append(token)
            token = reader.next_token()
        self._require(token is not None and token.catcode == CatCode.BEGIN_GROUP,
                      "argument_required", "Collected end requires a braced name")
        opening, depth, inner = token, 1, []
        envelope.append(token)
        while (token := reader.next_token()) is not None:
            envelope.append(token)
            if token.catcode == CatCode.BEGIN_GROUP:
                depth += 1
            elif token.catcode == CatCode.END_GROUP:
                depth -= 1
                if depth == 0:
                    return ScannedArgument("environment name", reader.source_span(opening.span.end, token.span.start), tuple(inner)), tuple(envelope)
            inner.append(token)
        raise ReadingIssue("unclosed_argument", "EOF while reading a collected end name")
