"""Behavioral content contracts: live input, current meanings, scopes and residue."""
import unittest
import sys
import json
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine.content_builder import ContentBuilder
from src.engine.format_builder import FormatBuilder


INIT = r"\catcode123=1 \catcode125=2 \catcode36=3 \catcode94=7 \catcode95=8 \catcode35=6 \catcode38=4 "


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node["children"])


def nodes(result, kind):
    roots = [*result.content["children"], *(n for f in result.content["open_lists"] for n in f["children"])]
    return [n for n in walk(roots) if n["kind"] == kind]


def text(result):
    return "".join(n["attributes"]["text"] for n in nodes(result, "character"))


class ContentTests(unittest.TestCase):
    def build(self, source, *, status="completed", inventory=None):
        result = ContentBuilder({"main.tex": INIT + source, **(inventory or {})}).build("main.tex")
        self.assertEqual(result.status, status, result.boundary)
        return result

    def test_text_paragraphs_and_macro_arguments(self):
        r = self.build(r"\def\pair#1{A#1}\noindent\pair{B} C\par D\end")
        self.assertEqual(text(r), "ABCD")
        self.assertEqual([n["attributes"]["indent"] for n in nodes(r, "paragraph")], [False, True])
        self.assertEqual(nodes(r, "character")[1]["source"]["source"], "main.tex")
        self.assertEqual(nodes(r, "character")[1]["source"]["start"], (INIT + r"\def\pair#1{A#1}\noindent\pair{").__len__())

    def test_pinned_native_observations(self):
        from src.validation.content_native import FIXTURES, fixture_build, observations
        expected = json.loads((FIXTURES / "content-construction.expected.json").read_text())
        for name, digest in expected["sources"].items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest)
        result = fixture_build()
        self.assertEqual(result.status, "completed", result.boundary)
        self.assertEqual(observations(result), expected["expected"])

    def test_live_box_catcodes(self):
        r = self.build(r"\hbox{\catcode33=11 \def\hello!{X}\hello!}Z\end")
        self.assertEqual(text(r), "XZ")

    def test_box_opening_macro_and_character_alias(self):
        r = self.build(r"\let\open=\hbox\let\letter=A\def\start{\open{}\hbox\bgroup}\let\bgroup={\start\letter}\end")
        self.assertEqual(text(r), "A")
        self.assertEqual(len(nodes(r, "hbox")), 2)

    def test_copy_take_and_local_restore(self):
        r = self.build(r"\setbox0=\hbox{A}{\setbox0=\hbox{B}\copy0}\copy0\box0\copy0\end")
        self.assertEqual(text(r), "BAA")

    def test_taking_box_without_local_assignment_does_not_restore_it(self):
        r = self.build(r"\setbox0=\hbox{A}{\box0}\copy0\end")
        self.assertEqual(text(r), "A")

    def test_global_box_assignment(self):
        r = self.build(r"\setbox0=\hbox{A}{\global\setbox0=\hbox{B}}\copy0\end")
        self.assertEqual(text(r), "B")

    def test_unbox_and_lastbox(self):
        r = self.build(r"\setbox0=\hbox{A}\hbox{B\unhcopy0\unhbox0\hbox{C}\setbox1=\lastbox}\copy1\end")
        self.assertEqual(text(r), "BAA")  # register 1 assignment is local to the enclosing hbox

    def test_box_dimensions_unknown_and_explicit(self):
        r = self.build(r"\setbox0=\hbox to 10pt{A}\message{\the\wd0}\wd0=12pt\message{\the\wd0}\end")
        self.assertEqual(r.messages, ("10.0pt", "12.0pt"))
        r = self.build(r"\hbox{X}\setbox0=\hbox{A}\message{\the\wd0}Z", status="boundary")
        self.assertEqual(r.boundary["reason"], "unknown_box_dimension")
        self.assertEqual(text(r), "X")

    def test_afterassignment_and_everybox_order(self):
        r = self.build(r"\everyhbox{E}\afterassignment A\setbox0=\hbox{B}\copy0\end")
        self.assertEqual(text(r), "AEB")
        r = self.build(r"\everyhbox{E}\def\build{\afterassignment A\setbox0=\hbox{B}}\build\copy0\end")
        self.assertEqual(text(r), "AEB")

    def test_everypar_runs_before_a_macro_character(self):
        r = self.build(r"\everypar{E}\def\word{AB}\word\end")
        self.assertEqual(text(r), "EAB")

    def test_box_dimension_mutates_current_box_without_new_save_entry(self):
        r = self.build(r"\setbox0=\hbox to10pt{}{\wd0=12pt}\message{\the\wd0}{\setbox0=\hbox to3pt{}\wd0=4pt}\message{\the\wd0}\end")
        self.assertEqual(r.messages, ("12.0pt", "12.0pt"))

    def test_aftergroup_content(self):
        r = self.build(r"\hbox{A\aftergroup Z}B\end")
        self.assertEqual(text(r), "AZB")

    def test_glue_kern_penalty_and_tail_queries(self):
        r = self.build(r"\hbox{A\hskip2pt plus1fil\message{\the\lastskip}\unskip\kern3pt\message{\the\lastkern}\unkern\penalty7\message{\the\lastpenalty}\unpenalty B}\end")
        self.assertEqual(r.messages, ("2.0pt plus 1.0fil", "3.0pt", "7"))
        self.assertFalse(nodes(r, "glue") + nodes(r, "kern") + nodes(r, "penalty"))

    def test_rule_and_leaders(self):
        r = self.build(r"\hbox{\vrule width2pt height3pt depth1pt\leaders\hbox{A}\hskip10pt}\end")
        self.assertEqual(nodes(r, "rule")[0]["attributes"]["height"], 3 * 65536)
        self.assertEqual(nodes(r, "leaders")[0]["attributes"]["glue"]["width"], 10 * 65536)

    def test_math_codes_scripts_classes(self):
        r = self.build(r'\mathcode43="202B $x_1^{ab}+\mathop{f}\limits_0$\end')
        self.assertEqual(len(nodes(r, "sup")), 1)
        self.assertEqual(len(nodes(r, "sub")), 2)
        self.assertIn("bin", [n["attributes"]["class_"] for n in nodes(r, "noad")])
        self.assertEqual([n["attributes"].get("limits") for n in nodes(r, "noad") if n["attributes"]["class_"] == "op"], ["limits"])

    def test_math_fraction_delimiters_radical_and_choice(self):
        r = self.build(r'\delcode40="028300 \delcode41="029301 $\left({a\over b}\right)\radical"270370{x}\mathchoice{D}{T}{S}{s}$\end')
        self.assertEqual(len(nodes(r, "fraction")), 1)
        self.assertEqual(len(nodes(r, "delimited")), 1)
        self.assertEqual(len(nodes(r, "choice")[0]["children"]), 4)

    def test_mathchardef_and_family_scope(self):
        r = self.build(r'\mathchardef\alpha="010B $\fam=3 x{\fam=4 y}z\alpha$\end')
        self.assertEqual([n["attributes"]["family"] for n in nodes(r, "math_character")], [3, 4, 3, 1])

    def test_display_and_everymath(self):
        r = self.build(r"\everymath{a}$b$\par $$c$$\end")
        self.assertEqual([n["attributes"]["display"] for n in nodes(r, "math")], [False, True])

    def test_modes_box_predicates_and_dimension_conditionals(self):
        r = self.build(r"\ifvmode\message{vertical}\fi\ifvoid0\message{void}\fi"
            r"\setbox0=\hbox to2pt{\ifhmode\message{horizontal}\fi\ifinner\message{inner}\fi"
            r"$\ifmmode x\fi\ifinner y\fi$}\ifhbox0\message{hbox}\fi"
            r"\ifdim\wd0>1pt\message{wide}\fi\end")
        self.assertEqual(r.messages, ("vertical", "void", "horizontal", "inner", "hbox", "wide"))

    def test_double_script_keeps_previous_content(self):
        r = self.build(r"$x^1^2$", status="boundary")
        self.assertEqual(r.boundary["reason"], "double_script")
        self.assertEqual(len(nodes(r, "sup")), 1)

    def test_failed_macro_rolls_back_nodes_and_assignments(self):
        r = self.build(r"\hbox{A}\def\bad{\count0=7 B\undefined}\bad", status="boundary")
        self.assertEqual(text(r), "A")
        self.assertNotIn("count:0", r.context.integer_parameters.values)
        self.assertEqual(r.boundary["remainder"]["start"], r.boundary["start"])
        self.assertEqual(r.boundary["remainder"]["source"], "main.tex")

    def test_input_uses_same_content_and_live_scope(self):
        r = self.build(r"\hbox{A\input child B}\end", inventory={"child.tex": "C"})
        self.assertEqual(text(r), "ACB")

    def test_restore_format_into_content(self):
        inventory = {"format.tex": INIT + r"\def\word{OK}\dump", "main.tex": r"\word\end"}
        fmt = FormatBuilder(inventory).build("format.tex")
        self.assertEqual(fmt.status, "dumped", fmt.boundary)
        builder = ContentBuilder(inventory)
        r = builder.build("main.tex", restored=builder.restore(fmt.snapshot))
        self.assertEqual(r.status, "completed", r.boundary)
        self.assertEqual(text(r), "OK")

    def test_insert_mark_write_shipout(self):
        r = self.build(r"\def\word{A}\mark{\word}\write1{\word}\immediate\write16{\word}\insert2{B\par}\shipout\hbox{C}\end")
        self.assertEqual(nodes(r, "mark")[0]["children"][0]["attributes"]["value"], "A")
        writes = nodes(r, "write")
        self.assertEqual([n["attributes"]["expansion"] for n in writes], ["deferred", "captured"])
        self.assertEqual(writes[0]["children"][0]["attributes"]["value"], "word")
        self.assertEqual(len(nodes(r, "shipout")), 1)

    def test_alignment_templates_omit_and_noalign(self):
        r = self.build(r"\halign{L#R&#\cr A&B\cr\noalign{\vskip2pt}\omit C&D\cr}\end")
        self.assertEqual(text(r), "LARBCD")
        self.assertEqual(len(nodes(r, "row")), 2)
        self.assertEqual(len(nodes(r, "cell")), 4)
        self.assertTrue(nodes(r, "cell")[2]["attributes"]["omit"])
        self.assertEqual(len(nodes(r, "noalign")), 1)

    def test_alignment_live_catcodes(self):
        r = self.build(r"\halign{#\cr\catcode33=11 \def\a!{A}\a!\cr}\end")
        self.assertEqual(text(r), "A")

    def test_alignment_template_math(self):
        r = self.build(r"\halign{$#$&#\cr x^2&A\cr}\end")
        self.assertEqual(len(nodes(r, "math")), 1)

    def test_explicit_boundaries(self):
        for source, reason in [(r"\hbox{A", "unclosed_group"), (r"$x", "unclosed_group"),
                               (r"\halign{##\cr}", "alignment_preamble"),
                               (r"\halign{#\cr A&B\cr}", "alignment_columns"),
                               (r"\hbox{\vskip1pt}", "content_mode"),
                               (r"$x}", "content_group"),
                               (r'\delcode40="028300 $\left(x}', "content_group"),
                               (r"\hbox{A\/\message{\the\lastkern}}", "unknown_italic_correction")]:
            with self.subTest(source=source):
                self.assertEqual(self.build(source, status="boundary").boundary["reason"], reason)

    def test_empty_vtop_and_explicit_math_space(self):
        r = self.build(r"\setbox0=\vtop to2pt{}\message{\the\ht0,\the\dp0}$a\ b$\end")
        self.assertEqual(r.messages, ("0.0pt,2.0pt",))
        self.assertEqual(len(nodes(r, "space")), 1)

    def test_content_budgets_cover_depth_and_shared_box_expansion(self):
        r = self.build(r"\hbox{" * 65 + "A" + "}" * 65, status="boundary")
        self.assertEqual(r.boundary["reason"], "content_budget")
        r = self.build(r"\setbox0=\hbox{A}" + r"\setbox0=\hbox{\copy0\copy0}" * 20, status="boundary")
        self.assertEqual(r.boundary["reason"], "content_budget")


if __name__ == "__main__":
    unittest.main()
