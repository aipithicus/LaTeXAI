"""Materialize declared external literal resources without interpreting their text."""
from pathlib import Path
import re

from ..reading.configuration import configured_options
from ..reading.contracts import EffectiveReadingProfile, LiteralRegion, ReadingIssue
from .records import source_reference


def prepare_external_literal(session, command):
    path = session.resolve(command.value("target"), [""], command.span)
    session.edge(command, path, "external_literal")
    document = session.store.document(path)
    role = command.metadata["semantic_role"]
    action = session.policy.get_role_action(role)
    environment = command.metadata["inline_environment"]
    if command.argument("star"):
        environment = command.metadata.get("starred_environment", environment)
    reason = None
    if action == "inline":
        try:
            profile = session.resolver.resolve_environment(environment)
            if isinstance(profile, EffectiveReadingProfile):
                profile = session.resolver.resolve_environment(environment,
                    configured_options(profile, command.argument("options"), session.context).values)
            if not isinstance(profile, EffectiveReadingProfile):
                raise ReadingIssue(profile.reason.value, profile.detail)
            if (profile.interpolations or profile.catcode_overrides
                    or profile.span_classification.category != "opaque_literal"):
                raise ReadingIssue("literal_options", "Reading-affecting options require a retained external resource")
            if re.search(profile.terminator.regex_pattern, document.text, re.MULTILINE):
                raise ReadingIssue("literal_terminator_collision", "File contains the inline environment's terminator")
            if not session.frames[-1].emit:
                raise ReadingIssue("local_literal", "Transclusion inside retained local code uses a payload reference")
        except ReadingIssue as error:
            reason = error
    elif action != "preserve":
        reason = ReadingIssue("policy_action", f"Unsupported external literal action {action!r}")
    record = {**source_reference(session.units.records[command.unit_id]),
              "target": session.name(path), "kind": "external_literal"}
    session.manifest.resources.append(record)
    if action == "inline" and reason is None:
        options = command.argument("options")
        header = "\\begin{" + environment + "}"
        if options is not None:
            header += "[" + session.raw(options.span) + "]"
        session.omit(command.span, "External literal reference transcluded")
        session.emit(command.span, header + "\n", command=command, operation="LITERAL_OPEN")
        reader = session.open_source(path)
        body = reader.source_span(0, len(document.text))
        empty = reader.source_span(0, 0)
        end = reader.source_span(len(document.text), len(document.text))
        session.observe(LiteralRegion(body, empty, body, end, environment, profile.binding_id))
        session.emit(body, operation="IDENTITY")
        separator = "" if document.text.endswith(("\r", "\n")) else "\n"
        session.emit(command.span, separator + "\\end{" + environment + "}\n", command=command, operation="LITERAL_CLOSE")
        record["disposition"] = "inlined"
    else:
        # An external file can contain the block terminator or reading options.
        # Keep exactly one necessary resource, with a payload-relative reference.
        target = (Path("literal-resources") / session.name(path)).as_posix()
        session.literal_payloads[path] = target
        arg = command.argument("target")
        a, b = arg.span.start - command.span.start, arg.span.end - command.span.start
        raw = session.raw(command.span)
        replacement = raw[:a] + target + raw[b:]
        if session.frames[-1].emit:
            session.emit(command.span, replacement, command=command, operation="REBASE_LITERAL_RESOURCE",
                          source_edits=((arg.span, target),))
        else:
            session.edit_payload(arg.span, target)
        record.update(disposition="retained", payload=target)
        if reason:
            session.require(command.span, reason.reason, reason.detail, stage="preparation", unit_id=command.unit_id)
