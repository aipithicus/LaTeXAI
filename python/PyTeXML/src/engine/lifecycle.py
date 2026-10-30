"""Observe content-bearing effects without a page builder or filesystem writes."""
from .expansion import ExpansionCursor, TokenListInsertion
from .token_text import token_text
from ..reading.contracts import ScannedArgument, ReadingIssue
from ..reading.token_cursor import TokenCursor


def expand_tokens(host, tokens, span):
    source = TokenCursor(ScannedArgument("write", span, ()), "", host.context)
    cursor = ExpansionCursor(source, host.context, host.knowledge, host.operations, host=host)
    cursor.push(tokens)
    result = []
    while (token := cursor.next_expanded(copy_token_lists=True)) is not None:
        result.extend(token.tokens if isinstance(token, TokenListInsertion) else (token,))
    return tuple(result)


class Lifecycle:
    def __init__(self, insertion_roles=None, box_roles=None):
        self.insertion_roles = dict(insertion_roles or {})
        self.box_roles = dict(box_roles or {})
        self.records, self.drivers = [], []
        self.links, self.anchors = (), ()
        self.serial, self.shipments = 0, 0
        self.streams, self.outputs = {}, {}

    def checkpoint(self):
        return (list(self.records), list(self.drivers), self.links, self.anchors, self.serial, self.shipments,
                dict(self.streams), dict(self.outputs))

    def restore(self, saved):
        records, drivers, self.links, self.anchors, self.serial, self.shipments, streams, outputs = saved
        self.records, self.drivers = list(records), list(drivers)
        self.streams, self.outputs = dict(streams), dict(outputs)

    def identifier(self):
        self.serial += 1
        return self.serial

    def record(self, node, content):
        content.work += node.size
        if content.work > content.limit:
            raise ReadingIssue("content_budget", "Lifecycle references exhausted the content budget")
        self.records.append(node)

    def write(self, content, host, node, *, shipment=None):
        from .primitives.content_events import token_nodes
        tokens = (node.payload if node.get("timing") == "immediate" else
                  expand_tokens(host, node.payload, node.span))
        text = "".join(token_text(t, host.context, double_parameters=True) for t in tokens)
        stream = node.get("stream")
        destination = self.streams.get(stream)
        if destination is not None:
            self.outputs[destination] = (*self.outputs[destination], (text, node.span))
        self.record(content.node(host, "write_observation", node.span, token_nodes(content, host, tokens),
            write_id=node.get("write_id"), stream=stream, shipment=shipment,
            text=text, timing=node.get("timing"), destination=destination or ("log" if stream < 0 else "terminal_log"),
            execution="expanded"), content)

    def stream(self, node):
        index = node.get("stream")
        if node.get("operation") == "open":
            name = node.get("filename")
            self.streams[index] = name
            self.outputs[name] = ()
        else:
            self.streams.pop(index, None)

    def shipout(self, content, host, box, span):
        self.shipments += 1
        shipment = self.shipments
        def visit(node):
            if node.kind == "write" and node.get("timing") == "shipout":
                self.write(content, host, node, shipment=shipment)
            elif node.kind == "output_stream" and node.get("timing") == "shipout":
                self.stream(node)
            # TeX suppresses writes in leaders; unprocessed insertions and
            # adjustments are not a substitute for an output routine.
            elif node.kind in {"hbox", "vbox", "vtop"}:
                for child in node.children:
                    visit(child)
        visit(box)
