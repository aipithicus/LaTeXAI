import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine.content_builder import ContentBuilder
from src.engine.causal import Recorder, semantic
from src.validation.record_diff import Index, compare, normalized_records
from src.validation.vocab_roundtrip import extract, project, TRUSTED, ProjectionError

INIT = r"\catcode123=1 \catcode125=2 \catcode35=6 "


def build(body, name="main.tex", record=True):
    return ContentBuilder({name: INIT + body}, record=record).build(name)


class CausalTests(unittest.TestCase):
    def test_noexpand_preserves_the_raw_token_unread_contract(self):
        from src.engine.causal import attach
        from src.engine.catalog import CORE_OPERATIONS
        from src.engine.expansion import ExpansionCursor
        from src.reading.tex_reader import TexReader
        builder = ContentBuilder({"main.tex": ""})
        context = builder.initial_context("main")
        recorder = Recorder()
        attach(context, recorder)
        reader = TexReader(r"\noexpand\relax", catcodes=context.catcodes, endline_char=context.endlinechar)
        cursor = ExpansionCursor(reader, context, builder.resolver, CORE_OPERATIONS)
        token = cursor.next_expanded()
        cursor.unread_token(token)
        self.assertEqual(cursor.next_token().value, "relax")
        self.assertTrue(any(e["relation"] == "returns_token" for e in recorder.edges))

    def test_recording_preserves_execution_and_connects_arguments_to_output(self):
        source = r"\def\a#1{#1}\a{X}\a{X}\end"
        traced, ordinary = build(source), build(source, record=False)
        self.assertEqual(traced.status, "completed", traced.boundary)
        self.assertEqual(traced.messages, ordinary.messages)
        self.assertEqual(semantic(traced.context.state_cells.values), semantic(ordinary.context.state_cells.values))
        def strip(value):
            if isinstance(value, dict):
                return {k: strip(v) for k, v in value.items() if k not in {"origin_event", "causal_record"}}
            return [strip(v) for v in value] if isinstance(value, list) else value
        self.assertEqual(strip(traced.content), ordinary.content)
        record = traced.record
        self.assertEqual(traced.content["causal_record"], record["run_id"])
        self.assertEqual(record["gaps"], [])
        macros = [e for e in record["events"] if e["operation"] == "macro_expand"]
        self.assertEqual(len(macros), 2)
        self.assertNotEqual(macros[0]["id"], macros[1]["id"])
        self.assertEqual(macros[0]["operands"], macros[1]["operands"])
        relations = {e["relation"] for e in record["edges"]}
        self.assertTrue({"argument_of", "captures_token", "produced_by", "consumes_token",
                         "constructed_by", "constructed_from", "node_contains"} <= relations)
        # Walk actual dependency edges from each retained X, not merely a census
        # of relation names somewhere in the record.
        outgoing = {}
        for edge in record["edges"]:
            outgoing.setdefault(edge["source"], []).append(edge)
        roots = [e["id"] for e in record["events"] if e["operation"] == "output_node"
                 and e["operands"]["kind"] == "character"]
        reached_calls = []
        for root in roots:
            seen, pending = set(), [root]
            while pending:
                identity = pending.pop()
                if identity in seen:
                    continue
                seen.add(identity)
                pending.extend(e["target"] for e in outgoing.get(identity, ())
                               if e["relation"] in {"constructed_from", "constructed_by", "consumes_token", "produced_by", "derived_from_token"})
            reached_calls.append(seen.intersection(e["id"] for e in macros))
        self.assertEqual(reached_calls, [{macros[0]["id"]}, {macros[1]["id"]}])
        list(normalized_records(record))  # No dangling event/version references.
        before = json.dumps(record, sort_keys=True)
        traced.context.integer_parameters.assign("count:9", 7, None)
        self.assertEqual(before, json.dumps(record, sort_keys=True))

    def test_read_versions_aliases_and_group_restoration(self):
        result = build(r"\count20=7 \def\a{old}\let\b=\a {\count20=9 \def\a{new}\message{\the\count20}\b}\message{\the\count20}\a\end")
        self.assertEqual(result.status, "completed", result.boundary)
        self.assertEqual(result.messages, ("9", "7"))
        record = result.record
        self.assertEqual(record["gaps"], [])
        versions = {v["id"]: v for v in record["versions"]}
        reads = [versions[e["target"]] for e in record["edges"] if e["relation"] == "reads_version"]
        self.assertTrue(any(v["key"].endswith("count:20") and v["value"] == 9 for v in reads))
        self.assertTrue(any(v["key"].endswith("count:20") and v["value"] == 7 for v in reads))
        restored = [e for e in record["edges"] if e["relation"] == "restores_from"]
        self.assertTrue(restored)
        for edge in restored:
            self.assertEqual(versions[edge["source"]]["value"], versions[edge["target"]]["value"])

    def test_failed_execution_retains_attempts_and_restores_frontier(self):
        result = build(r"\count20=7 \def\bad{\count20=9 \undefined}\bad\end")
        self.assertEqual(result.status, "boundary")
        self.assertEqual(result.context.integer_parameters.read("count:20"), 7)
        self.assertTrue(any(e["status"] == "rolled_back" for e in result.record["events"]))
        self.assertTrue(any(v["status"] == "rolled_back" and v["value"] == 9 for v in result.record["versions"]))
        ids = {v["id"]: v for v in result.record["versions"]}
        self.assertTrue(all(ids[i]["status"] != "rolled_back" for i in result.record["frontier"].values()))
        self.assertEqual(compare(result.record, result.record)["status"], "incomplete")

    def test_paths_are_metadata_but_relationships_and_outputs_are_not(self):
        # jobname is an observable value, so keep it fixed for a relocation test.
        a, b = build(r"\def\a#1{#1}\a{X}\end", "left/main.tex"), build(r"\def\a#1{#1}\a{X}\end", "right/main.tex")
        self.assertEqual(compare(a.record, b.record)["status"], "matched")
        changed = copy.deepcopy(a.record)
        changed["edges"][-1]["relation"] = "different_relation"
        self.assertFalse(compare(a.record, changed)["record_equal"])
        changed = copy.deepcopy(a.record)
        changed["output"]["messages"] = ["different"]
        result = compare(a.record, changed)
        self.assertTrue(result["state_equal"])
        self.assertFalse(result["output_equal"])

    def test_global_write_cancels_old_restoration_and_local_saves_new_version(self):
        result = build(r"\count20=1 {\global\count20=2 \count20=3 }\message{\the\count20}\end")
        self.assertEqual(result.messages, ("2",))
        versions = {v["id"]: v for v in result.record["versions"]}
        edges = [e for e in result.record["edges"] if e["relation"] == "restores_from" and versions[e["source"]]["key"].endswith("count:20")]
        self.assertEqual([versions[e["target"]]["value"] for e in edges], [2])

    def test_equal_final_state_does_not_hide_changed_output(self):
        a, b = build(r"\message{A}\end"), build(r"\message{B}\end")
        result = compare(a.record, b.record)
        self.assertTrue(result["state_equal"])
        self.assertFalse(result["output_equal"])
        self.assertEqual(result["status"], "different")
        self.assertNotEqual(result["first_difference"]["actual"].get("operation"), "run")

    def test_catcode_restoration_has_a_version_edge(self):
        result = build(r"\catcode64=12 {\catcode64=11 }\end")
        versions = {v["id"]: v for v in result.record["versions"]}
        restored = [edge for edge in result.record["edges"] if edge["relation"] == "restores_from"
                    and versions[edge["source"]]["key"] == "catcode:64"]
        self.assertEqual([versions[e["target"]]["value"] for e in restored], [12])

    def test_unobserved_write_is_a_gap_not_attributed_to_the_reader(self):
        recorder = Recorder()
        recorder.write("cell", 1, scope="input")
        with recorder.event("reader"):
            recorder.read("cell", 2)
        current = recorder.live["cell"]
        self.assertEqual(recorder.gaps, ["unobserved_write:cell"])
        self.assertFalse(any(e["source"] == current and e["relation"] == "written_by" for e in recorder.edges))
        self.assertFalse(any(e["target"] == current and e["relation"] == "writes_version" for e in recorder.edges))
        receipt = recorder.receipt(status="completed", output=[], state={})
        self.assertEqual(compare(receipt, receipt)["status"], "incomplete")

    def test_box_updates_preserve_save_entries_and_have_writers(self):
        result = build(r"\setbox0=\hbox{A}{\wd0=5pt}\message{\the\wd0}"
                       r"{\setbox0=\hbox{B}\wd0=7pt\box0}\message{\the\wd0}\box0\end")
        self.assertEqual(result.status, "completed", result.boundary)
        self.assertEqual(result.messages, ("5.0pt", "5.0pt"))
        self.assertEqual(result.record["gaps"], [])
        versions = {v["id"]: v for v in result.record["versions"]}
        updates = [v for v in versions.values() if v["key"] == "state_cells:box:0" and v["scope"] == "update"]
        self.assertEqual(len(updates), 4)
        for version in updates:
            self.assertTrue(any(e["source"] == version["id"] and e["relation"] == "written_by" for e in result.record["edges"]))
        self.assertIsNone(versions[result.record["frontier"]["state_cells:box:0"]]["value"])


class MerkleTests(unittest.TestCase):
    def test_cached_indexes_are_immutable_snapshots(self):
        record = self.record(3)
        index = Index.build(record)
        record["events"][0]["operands"]["value"] = 99
        self.assertFalse(compare(index, Index.build(record))["record_equal"])
        with self.assertRaises(TypeError):
            index.records[0]["operands"]["value"] = 99
        with self.assertRaises(TypeError):
            index.source["output"] = [99]

    def record(self, count=2048):
        recorder = Recorder()
        for i in range(count):
            recorder.point("operation", {"value": i})
        return recorder.receipt(status="completed", output=[], state={})

    def test_equal_blocks_pruned_and_first_change_matches_linear_scan(self):
        original = self.record()
        changed = copy.deepcopy(original)
        changed["events"][1700]["operands"]["value"] = -1
        left, right = Index.build(original), Index.build(changed)
        result = compare(left, right)
        linear = next(i for i, (a, b) in enumerate(zip(left.records, right.records)) if a != b)
        self.assertEqual(result["first_difference"]["record_index"], linear)
        self.assertEqual(linear, 1700)
        self.assertLess(result["merkle"]["visited"], 30)
        self.assertGreater(result["merkle"]["pruned"], 0)
        self.assertEqual(compare(left, left)["merkle"]["visited"], 1)

    def test_insertions_use_declared_fallback_and_corrupt_edges_reject(self):
        a, b = self.record(3), self.record(4)
        self.assertEqual(compare(a, b)["merkle"]["algorithm"], "linear_unequal_length")
        b["edges"].append({"source": "e0", "relation": "reads", "target": "missing"})
        with self.assertRaises(ValueError):
            Index.build(b)


class VocabularyTests(unittest.TestCase):
    def test_executes_authors_and_projects_only_trusted_vocabulary(self):
        result, math = extract(TRUSTED + r"\def\ratio#1{\frac{#1^2}{2}}", r"\ratio{x}+y_1")
        canonical = project(math)
        self.assertIn(r"\frac", canonical)
        self.assertNotIn("ratio", canonical)
        self.assertIn("^", canonical)
        self.assertIn("_", canonical)
        self.assertEqual(result.record["gaps"], [])
        _, shadowed = extract(r"\def\frac#1#2{#1+#2}", r"\frac{x}{2}")
        self.assertNotIn(r"\frac", project(shadowed))
        self.assertIn('202B', project(shadowed))

    def test_unknown_nodes_and_attributes_are_not_silently_projected(self):
        _, math = extract("", "x")
        with self.assertRaises(ProjectionError):
            project(replace(math.children[0], kind="unknown"))
        with self.assertRaises(ProjectionError):
            project(math.children[0].with_value("unqualified", True))


if __name__ == "__main__":
    unittest.main()
