"""State-family semantics and a source-built, restored INITEX checkpoint."""
from pathlib import Path
import sys
import unittest
import json
import struct
import hashlib
import tempfile
from dataclasses import asdict

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.reading.contracts import ReadingBoundary
from src.reading.dispatcher import StructuralDispatcher
from src.reading.tex_reader import CatCode, TexReader
from src.engine.read_streams import ReadSource
from src.engine.format_builder import FormatBuilder


class FormatStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()

    def run_source(self, text, *, context=None, complete=True):
        resolver = BindingResolver(self.catalog, engine_profile="pdftex")
        context = context or resolver.new_context(primitive_initial_state=True)
        host = StructuralDispatcher(TexReader(text, catcodes=context.catcodes, endline_char=context.endlinechar),
                                    context, resolver, preparation=True, source_commands=True)
        items = list(host)
        if complete:
            self.assertFalse([i for i in items if isinstance(i, ReadingBoundary)], items[-1:])
        return host, items

    def result(self, host, name="result"):
        return "".join(t.value for t in host.context.lookup_definition(name).replacement_tokens)

    def token_records(self, tokens):
        return [(t.kind, t.value, t.catcode, t.span.basis.source_id, t.span.basis.occurrence_id,
                 t.span.basis.length, t.span.start, t.span.end, t.transformed, t.control_word) for t in tokens]

    def test_code_tables_case_categories_and_scope(self):
        host, _ = self.run_source(r"\lccode`A=`z {\lccode`A=`x\lowercase{\gdef\inside{A}}}"
                                  r"\lowercase{\def\result{A}}\uppercase{\def\upper{a}}")
        self.assertEqual(self.result(host), "z")
        self.assertEqual(self.result(host, "inside"), "x")
        self.assertEqual(self.result(host, "upper"), "A")
        self.assertEqual(host.context.lookup_definition("result").replacement_tokens[0].catcode, CatCode.LETTER)
        host, _ = self.run_source(r'\mathchardef\alpha="710B \edef\result{\number\alpha,\meaning\alpha}')
        self.assertEqual(self.result(host), '28939,\\mathchar"710B')

    def test_glue_orders_arithmetic_and_signed_division(self):
        host, _ = self.run_source(r"\skipdef\s=3 \s=1pt plus 2fil minus 3pt "
            r"\advance\s by 2pt plus 1fill minus -1pt \multiply\s by 3 \divide\s by -2 "
            r"\muskip0=3mu plus 2fil \count0=-7 \divide\count0 by 2 "
            r"\edef\result{\the\s;\the\muskip0;\the\count0}")
        self.assertEqual(self.result(host), "-4.5pt plus -1.5fill minus -3.0pt;3.0mu plus 2.0fil;-3")

    def test_store_parameters_and_global_restoration(self):
        host, _ = self.run_source(r"\parindent=2pc \baselineskip=12pt plus 1pt \everypar={A}"
            r"{\global\baselineskip=13pt \everypar={B}}\edef\result{\the\parindent;\the\baselineskip;\the\everypar}")
        self.assertEqual(self.result(host), "24.0pt;13.0pt;A")
        host, _ = self.run_source(r"\dimen0=1.999999999sp \edef\result{\number\dimen0}")
        self.assertEqual(self.result(host), "1")

    def test_arithmetic_failure_rolls_back_and_case_value_rejected(self):
        for operation in (r"\divide\skip0 by 0", r"\multiply\skip0 by 2147483647"):
            host, items = self.run_source(r"\skip0=1pt " + operation, complete=False)
            self.assertIn(items[-1].reason, {"arithmetic_overflow", "division_by_zero"})
            self.assertEqual(host.context.state_cells.read("skip:0").width, 65536)
        _, items = self.run_source(r"\lccode65=256 ", complete=False)
        self.assertEqual(items[-1].reason, "code_table_value")
        _, items = self.run_source(r"\mag=1200 \dimen0=1truept \mag=1000 \dimen0=1truept ", complete=False)
        self.assertEqual(items[-1].reason, "magnification")

    def test_readline_keeps_raw_categories_and_unbalanced_text(self):
        context = BindingResolver(self.catalog).new_context(primitive_initial_state=True)
        context.read_streams.configure({"data": ReadSource.from_text("data", "{\\x%#  \n")})
        host, _ = self.run_source(r"\openin0=data \readline0 to\raw\edef\result{\meaning\raw}", context=context)
        raw = context.lookup_meaning("raw").replacement_tokens
        self.assertEqual("".join(t.value for t in raw), "{\\x%#\r")
        self.assertTrue(all(t.catcode == CatCode.OTHER for t in raw))

    def test_afterassignment_replacement_and_aftergroup_order(self):
        host, _ = self.run_source(r"\count0=0 \def\a{\global\advance\count0 by 1 }"
            r"\def\b{\global\multiply\count0 by 10 }\afterassignment\b\afterassignment\a\count1=2 "
            r"{\aftergroup\a\aftergroup\b}\edef\result{\the\count0}")
        self.assertEqual(self.result(host), "20")

    @staticmethod
    def metric():
        # A minimal zero-character TFM with design size 10pt, seven parameters.
        header = struct.pack(">12H", 19, 2, 1, 0, 1, 1, 1, 1, 0, 0, 0, 7)
        return header + struct.pack(">2I", 0, 10 << 20) + bytes(16) + struct.pack(">7i", 0, 1 << 19, 0, 0, 1 << 18, 1 << 20, 0)

    def test_font_metrics_selection_family_and_global_properties(self):
        context = BindingResolver(self.catalog).new_context(primitive_initial_state=True)
        context.fonts.configure({"toy.tfm": self.metric()})
        host, _ = self.run_source(r"\font\f=toy at 12pt \f\textfont2=\f "
            r"{\hyphenchar\f=64 \fontdimen7\f=2pt}\dimen0=1em "
            r"\edef\result{\the\fontdimen2\f;\the\dimen0;\number\hyphenchar\f;\the\fontdimen7\f}", context=context)
        self.assertEqual(self.result(host), "6.0pt;12.0pt;64;2.0pt")

    def test_format_build_dump_restore_and_inventory_guard(self):
        builder = FormatBuilder({"base.ini": r"\catcode123=1 \catcode125=2 \catcode35=6 "
            r"\input state.tex \message{built:\the\skip0}\dump",
            "state.tex": r"\countdef\n=5 \n=7 \skip0=2pt plus 1fil \def\macro#1{[#1]}\let\alias\macro",
            "resume.tex": r"\advance\n by 2 \edef\answer{\macro{X}:\the\n}\message{\answer}\dump"})
        first = builder.build("base.ini")
        self.assertEqual(first.status, "dumped", first.receipt())
        restored = builder.restore(first.snapshot)
        self.assertIs(restored[0].lookup_definition("macro"), restored[0].lookup_definition("alias"))
        second = builder.build("resume.tex", restored=restored)
        self.assertEqual(second.status, "dumped", second.receipt())
        self.assertEqual(second.messages, ("[X]:9",))
        self.assertEqual(first.context.integer_parameters.read("count:5"), 7)
        changed = FormatBuilder({"base.ini": "different"})
        with self.assertRaisesRegex(ValueError, "inventory"):
            changed.restore(first.snapshot)
        envelope = json.loads(first.snapshot)
        envelope["payload"] += " "
        with self.assertRaisesRegex(ValueError, "checksum"):
            builder.restore(json.dumps(envelope))

    def test_format_failure_reports_source_and_cannot_dump_partial_state(self):
        builder = FormatBuilder({"base.ini": r"\count0=8 \unsupported\dump"})
        result = builder.build("base.ini")
        self.assertEqual(result.status, "boundary")
        self.assertEqual(result.boundary["source"], "base.ini")
        self.assertEqual(result.context.integer_parameters.read("count:0"), 8)
        self.assertIsNone(result.snapshot)
        self.assertEqual(FormatBuilder({"a": r"\count0=1 "}).build("a").status, "missing_dump")
        # Native input is expandable. An edef must not silently freeze it as
        # an unexpandable command when that consumer lacks physical I/O.
        expanded = FormatBuilder({"a": r"\catcode123=1 \catcode125=2 \edef\x{\input a}\dump"}).build("a")
        self.assertEqual(expanded.status, "boundary")
        self.assertIsNone(expanded.context.lookup_definition("x"))

    def test_native_format_fixture_build_and_restore(self):
        root = PROJECT / "tests/fixtures/engine"
        config = json.loads((root / "state-format.inventory.json").read_text())
        expected = json.loads((root / "state-format.expected.json").read_text())
        sources = {name: (root / path).read_bytes().decode() for name, path in config["sources"].items()}
        metrics = {name: (root / path).read_bytes() for name, path in config["metrics"].items()}
        self.assertEqual(hashlib.sha256(metrics["cmr10.tfm"]).hexdigest(), expected["metric_sha256"])
        builder = FormatBuilder(sources, metrics=metrics)
        built = builder.build(config["entry"])
        self.assertEqual(built.status, "dumped", built.receipt())
        self.assertEqual(list(built.messages), expected["build"])
        restored = builder.restore(built.snapshot)
        resumed = builder.build("state-format-resume.tex", restored=restored, require_dump=False)
        self.assertEqual(resumed.status, "completed", resumed.receipt())
        self.assertEqual(list(resumed.messages), expected["resume"])
        self.assertEqual(resumed.context.state_cells.read("jobname"), "state-format-resume")

    def test_snapshot_restored_provenance_scope_and_independent_documents(self):
        builder = FormatBuilder({"base": r"\catcode123=1 \catcode125=2 \catcode35=6 "
            r"\lowercase{\def\a{ABC}}\def\b#1{#1}\let\same\a\toks0={\a}\dump",
            "document": r"{\def\a{LOCAL}\global\count0=3}\edef\answer{\a}\dump",
            "broken": r"\skip0=1mu \dump"})
        built = builder.build("base")
        self.assertEqual(built.status, "dumped", built.receipt())
        restored = builder.restore(built.snapshot)
        a = restored[0].lookup_definition("a")
        self.assertEqual(self.token_records(a.replacement_tokens),
                         self.token_records(built.context.lookup_definition("a").replacement_tokens))
        self.assertIs(a.span.basis, a.replacement_tokens[0].span.basis)
        self.assertIs(a, restored[0].lookup_definition("same"))
        first = builder.build("document", restored=restored)
        second = builder.build("document", restored=restored)
        self.assertEqual(first.status, "dumped", first.receipt())
        self.assertEqual(first.messages, second.messages)
        self.assertEqual(self.token_records(first.context.lookup_definition("answer").replacement_tokens),
                         self.token_records(second.context.lookup_definition("answer").replacement_tokens))
        self.assertNotIn("count:0", restored[0].integer_parameters.values)
        self.assertTrue(restored[1], "Case conversion origins must survive snapshot restoration")
        self.assertEqual(builder.build("broken", restored=restored).status, "boundary")
        self.assertNotIn("skip:0", restored[0].state_cells.values)

    def test_unavailable_and_uncertain_state_never_becomes_zero(self):
        context = BindingResolver(self.catalog).new_context(primitive_initial_state=True)
        cause = TexReader("x", catcodes=context.catcodes, endline_char=context.endlinechar).basis.whole
        context.state_cells.invalidate(cause)
        host, items = self.run_source(r"\edef\result{\the\skip25}", context=context, complete=False)
        self.assertEqual(items[-1].reason, "uncertain_state")
        self.assertIsNone(context.lookup_definition("result"))

    def test_invalid_dump_and_output_owner_fail_explicitly(self):
        for code, reason in ((r"\begingroup\dump", "format_dump_state"),
                             (r"\immediate\write18{echo test}\dump", "output_stream"),
                             (r"\write16{later}\dump", "deferred_write")):
            result = FormatBuilder({"a": r"\catcode123=1 \catcode125=2 " + code}).build("a")
            self.assertEqual(result.status, "boundary")
            self.assertEqual(result.boundary["reason"], reason)
            self.assertIsNone(result.snapshot)

    def test_preparation_preserves_state_commands_and_serializes_glue(self):
        from src.prepare.pipeline import preprocess_paper
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            root = Path(folder)
            (root / "main.tex").write_text(r"\documentclass{article}\skip0=1pt plus 2fil "
                r"\def\a{\global\advance\skip0 by 1pt }\afterassignment\a\count0=1 "
                r"\edef\result{\the\skip0}\aftergroup\a" + "\nTEXT", encoding="utf-8")
            text, manifest, _, _ = preprocess_paper(str(root))
            self.assertFalse(manifest.unresolved)
            self.assertIn(r"\skip0=1pt plus 2fil", text)
            self.assertIn(r"\aftergroup\a TEXT", text)
            json.dumps(asdict(manifest))

    def test_clock_initialization_is_explicit_fingerprinted_and_refreshed(self):
        sources = {"base": r"\catcode123=1 \catcode125=2 \edef\saved{\the\year}\year=2000 \dump",
                   "resume": r"\message{\saved:\the\year}\end"}
        missing = FormatBuilder(sources).build("base")
        self.assertEqual(missing.boundary["reason"], "unavailable_integer")
        builder = FormatBuilder(sources, initialization={"year": 2026})
        result = builder.build("base")
        self.assertEqual(result.status, "dumped", result.receipt())
        resumed = builder.build("resume", restored=builder.restore(result.snapshot), require_dump=False)
        self.assertEqual(resumed.messages, ("2026:2026",))
        with self.assertRaisesRegex(ValueError, "inventory"):
            FormatBuilder(sources, initialization={"year": 2027}).restore(result.snapshot)


if __name__ == "__main__":
    unittest.main()
