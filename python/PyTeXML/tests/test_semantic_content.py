"""Local measurement, driver state, delayed content and honest layout boundaries."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.engine.content_builder import ContentBuilder
from src.engine.semantic_drivers import DRIVER, SOURCE_SHA256
from src.validation.local_measurement import FIXTURES, build as measured_build
from test_content_construction import INIT, nodes, text


class SemanticContentTests(unittest.TestCase):
    def build(self, source, *, status="completed", driver=False, **kwargs):
        sources = {"main.tex": INIT + r"\catcode64=11 " + source}
        if driver:
            sources["hpdftex.def"] = (FIXTURES / "drivers/hpdftex.def").read_text()
            kwargs["semantic_drivers"] = {"hpdftex.def": DRIVER}
        r = ContentBuilder(sources, metrics={"cmr10.tfm": (FIXTURES / "cmr10.tfm").read_bytes()}, **kwargs).build("main.tex")
        self.assertEqual(r.status, status, r.boundary)
        return r

    def test_native_measurement_receipt_and_source_pins(self):
        receipt = json.loads((FIXTURES / "local-measurement.expected.json").read_text())
        for name, digest in receipt["sources"].items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest)
        r = measured_build()
        self.assertEqual(r.status, "completed", r.boundary)
        self.assertEqual(list(r.messages), receipt["expected"])

    def test_measurement_controls_real_state_and_content(self):
        r = self.build(r"\font\f=cmr10 \f\setbox0=\hbox{office}\ifdim\wd0<23pt \count0=7 A\else\count0=9 B\fi\message{\the\count0}\end")
        self.assertEqual(text(r), "A")
        self.assertEqual(r.messages, ("7",))

    def test_paragraph_dependency_preserves_body_and_stops_quantity_branch(self):
        r = self.build(r"\setbox0=\vbox{Readable body\par}\copy0 \ifdim\ht0>1pt X\else Y\fi", status="boundary")
        self.assertEqual(text(r), "Readablebody")
        self.assertEqual(r.boundary["reason"], "unknown_box_dimension")
        requirements = nodes(r, "vbox")[0]["attributes"]["measurement_requirements"]
        self.assertEqual(requirements[0][0], "paragraph_breaking")

    def test_explicit_width_preserves_other_unknown_dimensions(self):
        r = self.build(r"\setbox0=\hbox to10pt{$x$}\message{\the\wd0}\copy0\end")
        box = nodes(r, "hbox")[0]["attributes"]
        self.assertEqual(r.messages, ("10.0pt",))
        self.assertIsNone(box["height"])
        self.assertEqual(box["measurement_requirements"][0][0], "math_layout")

    def test_deferred_writes_expand_at_each_shipout(self):
        r = self.build(r"\def\word{A}\setbox0=\hbox{\write1{\word}}\def\word{B}\shipout\copy0\def\word{C}\shipout\box0\end")
        records = r.content["lifecycle"]
        self.assertEqual([x["attributes"]["text"] for x in records], ["B", "C"])
        self.assertEqual([x["attributes"]["shipment"] for x in records], [1, 2])
        self.assertEqual(records[0]["attributes"]["write_id"], records[1]["attributes"]["write_id"])

    def test_discarded_boxes_and_leaders_do_not_execute_deferred_writes(self):
        r = self.build(r"\setbox0=\hbox{\write1{discarded}\immediate\write16{now}}\shipout\hbox{\leaders\hbox{\write1{leader}}\hskip2pt}\end")
        self.assertEqual([x["attributes"]["text"] for x in r.content["lifecycle"]], ["now"])

    def test_failed_macro_rolls_back_effects(self):
        r = self.build(r"\def\bad{\immediate\write1{not-published}\undefined}\bad", status="boundary")
        self.assertEqual(r.content["lifecycle"], [])

    def test_auxiliary_output_reenters_the_same_engine(self):
        r = self.build(r"\immediate\openout1=labels.aux \def\value{old}\setbox0=\hbox{\write1{\string\def\string\ref{\value}}}"
                       r"\def\value{new}\shipout\box0\immediate\closeout1 \input labels.aux \ref\end")
        self.assertEqual(text(r), "new")
        self.assertEqual(r.content["virtual_outputs"]["labels.aux"]["text"], "\\def\\ref{new}\n")
        self.assertTrue(r.content["virtual_outputs"]["labels.aux"]["sources"])
        self.assertEqual(nodes(r, "character")[0]["source"]["source"], "labels.aux")

    def test_deferred_stream_open_close_and_reopen(self):
        r = self.build(r"\shipout\hbox{\openout1=a.aux \write1{first}\closeout1\write1{closed}}"
                       r"\immediate\openout1=a.aux \immediate\write1{second}\immediate\closeout1\end")
        self.assertEqual(r.content["virtual_outputs"]["a.aux"]["text"], "second\n")
        self.assertEqual([n["attributes"]["destination"] for n in r.content["lifecycle"]],
                         ["a.aux", "terminal_log", "a.aux"])

    def test_open_output_reinput_has_a_timing_boundary(self):
        r = self.build(r"\immediate\openout1=a.aux \input a.aux", status="boundary")
        self.assertEqual(r.boundary["reason"], "output_input_timing")

    def test_explicit_footnote_and_float_roles_preserve_unplaced_content(self):
        r = self.build(r"\insert254{Footnote\par}\insert2{Other\par}\setbox3=\vbox{Float\par}\end",
                       insertion_roles={254: "footnote"}, box_roles={3: "float"})
        self.assertEqual([x["attributes"]["role"] for x in nodes(r, "insert")], ["footnote", "unclassified"])
        record = r.content["lifecycle"][0]
        self.assertEqual(record["attributes"]["role"], "float")
        self.assertEqual(record["attributes"]["placement"], "unresolved")
        self.assertEqual(record["children"][0]["children"][0]["kind"], "paragraph")

    def test_driver_links_anchors_aliases_and_scopes(self):
        self.assertEqual(hashlib.sha256((FIXTURES / "drivers/hpdftex.def").read_bytes()).hexdigest(), SOURCE_SHA256)
        r = self.build(r"\input hpdftex.def \hyper@anchorstart{sec.one}\ifHy@activeanchor A\fi\hyper@anchorend"
                       r"\ifHy@activeanchor B\else C\fi\let\link=\hyper@linkurl\count0=1 "
                       r"\link{\count0=2 URL}{https://example.org}\message{\the\count0}\end", driver=True)
        self.assertEqual(text(r), "ACURL")
        self.assertEqual(r.messages, ("1",))
        events = [n["attributes"] for n in nodes(r, "driver_event")]
        self.assertEqual([n["action"] for n in events], ["anchor_start", "anchor_end", "link_start", "link_end"])
        self.assertEqual(events[2]["destination"], "https://example.org")
        self.assertEqual(events[2]["identifier"], events[3]["identifier"])

    def test_driver_redefinition_and_metadata(self):
        r = self.build(r"\input hpdftex.def \pdfinfo{/Title (Title)}{\def\hyper@linkurl#1#2{#1}\hyper@linkurl{A}{x}}"
                       r"\hyper@linkurl{B}{y}\end", driver=True)
        self.assertEqual(text(r), "AB")
        self.assertEqual(len(nodes(r, "driver_event")), 3)
        self.assertEqual(nodes(r, "driver_event")[0]["attributes"]["dictionary"], "/Title (Title)")

    def test_url_retains_outer_scope_during_colour_aftergroup(self):
        r = self.build(r"\input hpdftex.def \count0=1\def\set{\count0=9 A}"
                       r"\hyper@linkurl{\aftergroup\set B}{x}\message{\the\count0}\end", driver=True)
        self.assertEqual(text(r), "BA")
        self.assertEqual(r.messages, ("1",))

    def test_driver_failures_are_explicit(self):
        for source, reason in [(r"\hyper@linkend", "driver_link_stack"),
                               (r"\hyper@anchorstart{x}\hyper@anchorstart{y}", "driver_anchor_stack"),
                               (r"\pdfstartlink", "undefined_control_sequence")]:
            r = self.build(r"\input hpdftex.def " + source, driver=True, status="boundary")
            self.assertEqual(r.boundary["reason"], reason)
        r = ContentBuilder({"main.tex": INIT + r"\input hpdftex.def", "hpdftex.def": "changed"},
                           semantic_drivers={"hpdftex.def": DRIVER}).build("main.tex")
        self.assertEqual(r.boundary["reason"], "driver_source")

    def test_unqualified_driver_options_and_filters_stop(self):
        for setup, reason in [(r"\let\ifHy@colorlinks\iftrue", "driver_option"),
                              (r"\def\HyperDestNameFilter#1{prefix.#1}", "driver_destination_filter"),
                              (r"\def\Hy@href@nextactionraw{/Next 1 0 R}", "driver_hook")]:
            r = self.build(r"\input hpdftex.def " + setup + r"\hyper@anchorstart{x}", driver=True, status="boundary")
            self.assertEqual(r.boundary["reason"], reason)
        r = self.build(r"\input hpdftex.def \let\ifHy@colorlinks\iffalse\def\HyperDestNameFilter#1{#1}"
                       r"\hyper@anchorstart{x}\hyper@anchorend\end", driver=True)
        self.assertEqual(len(nodes(r, "driver_event")), 2)

    def test_pinned_native_lifecycle_and_driver_receipt(self):
        from src.validation.semantic_native import python_driver
        receipt = json.loads((FIXTURES / "semantic-content.expected.json").read_text())
        for name, digest in receipt["sources"].items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest)
        r = python_driver()
        self.assertEqual(r.status, "completed", r.boundary)
        self.assertEqual(list(r.messages), receipt["expected"]["driver"]["messages"])
        events = [n["attributes"] for n in nodes(r, "driver_event")]
        for key, action in (("links", "link_start"), ("anchors", "anchor_start")):
            self.assertEqual([e["destination"] for e in events if e["action"] == action], receipt["expected"]["driver"][key])
        r = ContentBuilder({p.name: p.read_text() for p in FIXTURES.glob("lifecycle*.tex")}).build("lifecycle.tex")
        self.assertEqual(r.status, "completed", r.boundary)
        self.assertEqual(r.content["virtual_outputs"]["references.aux"]["text"], receipt["expected"]["auxiliary"])
        self.assertEqual([n["attributes"]["text"] for n in r.content["lifecycle"] if n["attributes"]["stream"] == 16],
                         receipt["expected"]["writes"])


if __name__ == "__main__":
    unittest.main()
