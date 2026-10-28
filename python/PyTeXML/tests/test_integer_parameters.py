"""Scoped cells, copied parameter meanings, and deferred-write invalidation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.bindings.catalog import BindingCatalog
from src.bindings.resolver import BindingResolver
from src.prepare.pipeline import preprocess_paper
from src.reading.context import ExecutionMode
from src.reading.contracts import DeferredRegion, ReadingBoundary, ReadingIssue, SourceCommand
from src.reading.dispatcher import StructuralDispatcher
from src.reading.effect_summary import EffectSummary
from src.reading.mouth_profiles import ProfileError
from src.reading.options import OptionScope
from src.reading.tex_reader import CatCode, TexReader
from reader_support import requested_options


class IntegerParameterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BindingCatalog()
        cls.oracle = json.loads((PROJECT / "tests/fixtures/engine/integer-parameters.expected.json").read_text())

    def host(self, text, *, preparation=False, context=None, engine_profile="etex"):
        knowledge = BindingResolver(self.catalog, engine_profile=engine_profile)
        context = context or knowledge.new_context()
        reader = TexReader(text, source_id="parameters.tex", catcodes=context.catcodes,
                           endline_char=context.endlinechar)
        return StructuralDispatcher(reader, context, knowledge, preparation=preparation)

    def read(self, text, **kwargs):
        host = self.host(text, **kwargs)
        items = list(host)
        self.assertFalse([i for i in items if isinstance(i, ReadingBoundary)], items)
        return host, items

    def value(self, host, key="widowpenalty"):
        return host.context.integer_parameters.read(key)

    def test_gauntlet_setup_assignment_preserves_active_format_constant(self):
        first = (PROJECT / "tests/fixtures/specimens/gauntlet-master/master.tex").read_text().splitlines()[0]
        host, items = self.read(first + r"\chardef\saved=\active", engine_profile="pdftex")
        self.assertEqual(self.value(host, "pdfoutput"), 1)
        self.assertEqual(host.context.lookup_meaning("saved").value, 13)
        self.assertIsNone(host.context.lookup_meaning("active").uncertain)
        self.assertEqual(items[0].action, "integer_parameter_assignment")

    def test_initial_parameter_values_are_not_guessed(self):
        for name in ("pdfoutput", "widowpenalty", "clubpenalty"):
            with self.subTest(name=name):
                host = self.host("\\chardef\\saved=\\" + name, engine_profile="pdftex")
                self.assertEqual(list(host)[-1].reason, "unavailable_integer")
                self.assertIsNone(host.context.lookup_meaning("saved"))

    def test_internal_parameter_read_does_not_assign_the_operand(self):
        host, _ = self.read(r"\widowpenalty=17\relax\clubpenalty=\widowpenalty\chardef\saved=\clubpenalty")
        self.assertEqual(self.value(host), 17)
        self.assertEqual(self.value(host, "clubpenalty"), self.oracle["internal"])
        self.assertEqual(host.context.lookup_meaning("saved").value, 17)

    def test_assignment_supports_shared_expansion_and_radix(self):
        host, _ = self.read(r"\def\sign{--+}\def\digits{'17}\widowpenalty=\sign\digits\relax")
        self.assertEqual(self.value(host), self.oracle["expanded"])

    def test_aliases_share_a_cell_after_original_spelling_is_redefined(self):
        host, _ = self.read(r"\let\saved\widowpenalty\widowpenalty=17 "
                            r"\def\widowpenalty{BAD}\saved=23 \chardef\readback=\saved")
        self.assertEqual(self.value(host), self.oracle["alias"])
        self.assertEqual(host.context.lookup_meaning("readback").value, 23)

    def test_nested_local_assignments_restore_the_cell(self):
        host, items = self.read(r"\widowpenalty=11{\widowpenalty=22{\widowpenalty=33}"
                                r"\chardef\inner=\widowpenalty}\chardef\outer=\widowpenalty")
        observed = [i.metadata["value"] for i in items
                    if isinstance(i, SourceCommand) and i.action == "character_code_assignment"]
        self.assertEqual(observed, [self.oracle["inner"], self.oracle["outer"]])
        self.assertEqual(self.value(host), 11)

    def test_group_exit_restores_an_unavailable_initial_value(self):
        host = self.host(r"{\widowpenalty=17}\chardef\saved=\widowpenalty")
        self.assertEqual(list(host)[-1].reason, "unavailable_integer")
        self.assertEqual(host.context.scope_depth, 0)

    def test_reassignment_reads_the_old_value(self):
        host, _ = self.read(r"\widowpenalty=17 \widowpenalty=-\widowpenalty")
        self.assertEqual(self.value(host), self.oracle["old_value"])

    def test_full_signed_integer_range_is_available(self):
        for key in ("minimum", "maximum"):
            value = self.oracle[key]
            with self.subTest(value=value):
                host, _ = self.read(r"\widowpenalty=" + str(value))
                self.assertEqual(self.value(host), value)

    def test_integer_range_failure_preserves_the_previous_cell(self):
        host = self.host(r"\widowpenalty=17 \widowpenalty=2147483648 ")
        self.assertEqual(list(host)[-1].reason, "invalid_assignment")
        self.assertEqual(self.value(host), 17)

    def test_pending_replacement_execution_does_not_publish_assignment(self):
        host = self.host(r"\widowpenalty=17 \def\value{23\relax}\widowpenalty=\value")
        self.assertEqual(list(host)[-1].reason, "integer_continuation")
        self.assertEqual(self.value(host), 17)

    def test_global_prefix_remains_a_boundary_without_a_partial_write(self):
        host = self.host(r"\widowpenalty=17 {\global\widowpenalty=23}")
        self.assertEqual(list(host)[-1].reason, "assignment_prefix")
        self.assertEqual(self.value(host), 17)

    def test_copy_and_restore_include_cells_and_their_scope_journals(self):
        host, _ = self.read(r"\widowpenalty=11")
        saved = host.context.copy()
        nested = self.host(r"{\widowpenalty=22", context=host.context)
        nested.next_item()
        nested.next_item()
        self.assertEqual(self.value(host), 22)
        host.context.restore_from(saved)
        self.assertEqual(self.value(host), 11)
        self.assertEqual(host.context.scope_depth, 0)

    def test_copied_contexts_do_not_share_parameter_cells(self):
        host, _ = self.read(r"\widowpenalty=11")
        copied = host.context.copy()
        self.read(r"\widowpenalty=22", context=copied)
        self.assertEqual(self.value(host), 11)
        self.assertEqual(copied.integer_parameters.read("widowpenalty"), 22)

    def test_option_replay_uses_shared_cells_and_rolls_back_failed_requests(self):
        for ending, expected in (("", 23), (r"\unknown", 11)):
            with self.subTest(ending=ending):
                source = (r"\widowpenalty=11 \def\value{23 }\DeclareOption{x}{"
                          r"\widowpenalty=\value" + ending + r"}\ProcessOptions")
                host = self.host(source)
                host.options = OptionScope("local", requested_options(host.context, ("x",)))
                items = list(host)
                self.assertEqual(isinstance(items[-1], ReadingBoundary), bool(ending))
                self.assertEqual(self.value(host), expected)
                self.assertEqual(host.options.processed, not bool(ending))

    def test_inactive_mode_does_not_assign_a_parameter(self):
        host = self.host(r"\widowpenalty=17")
        host.context.mode = ExecutionMode.STORED_DEFINITION
        self.assertEqual(host.next_item().reason, "inactive_context")
        self.assertEqual(host.context.integer_parameters.values, {})

    def test_unexecuted_alias_writer_invalidates_only_its_parameter(self):
        host, items = self.read(r"\widowpenalty=11 \clubpenalty=22 \let\saved\widowpenalty"
                                r"\def\writer{\saved=33 }\writer", preparation=True)
        region = next(i for i in items if isinstance(i, DeferredRegion))
        self.assertEqual(region.effect_summary.registers, ("widowpenalty",))
        with self.assertRaisesRegex(ReadingIssue, "may have changed"):
            self.value(host)
        self.assertEqual(self.value(host, "clubpenalty"), 22)
        self.assertIsNone(host.context.lookup_meaning("active").uncertain)

    def test_deferred_local_parameter_write_restores_at_group_exit(self):
        host, _ = self.read(r"\widowpenalty=11 {\def\writer{\widowpenalty=33 }\writer}"
                            r"\chardef\saved=\widowpenalty", preparation=True)
        self.assertEqual(host.context.lookup_meaning("saved").value, 11)

    def test_unknown_execution_invalidates_saved_outer_parameter_values(self):
        host = self.host(r"\widowpenalty=11 {\widowpenalty=22 \unknown}"
                         r"\chardef\saved=\widowpenalty", preparation=True)
        boundary = list(host)[-1]
        self.assertEqual(boundary.reason, "uncertain_integer")
        self.assertTrue(boundary.causes)
        self.assertEqual(host.context.scope_depth, 0)
        self.assertIsNone(host.context.lookup_meaning("saved"))

    def test_unknown_execution_preserves_cause_when_outer_value_was_absent(self):
        host = self.host(r"{\widowpenalty=22 \unknown}\chardef\saved=\widowpenalty", preparation=True)
        boundary = list(host)[-1]
        self.assertEqual(boundary.reason, "uncertain_integer")
        self.assertTrue(boundary.causes)

    def test_explicit_assignment_can_reestablish_a_value_after_unknown_effects(self):
        host, _ = self.read(r"\widowpenalty=11 \unknown\widowpenalty=22\chardef\saved=\widowpenalty",
                            preparation=True)
        self.assertEqual(host.context.lookup_meaning("saved").value, 22)

    def test_global_deferred_write_invalidates_all_saved_values(self):
        host, _ = self.read(r"\widowpenalty=11")
        host.context.push_scope()
        span = host.reader.basis.span(0, 1)
        host.context.integer_parameters.assign("widowpenalty", 22, span)
        host.context.invalidate_writes(EffectSummary(scope="global", registers=("widowpenalty",)), span)
        host.context.pop_scope()
        with self.assertRaisesRegex(ReadingIssue, "may have changed"):
            self.value(host)

    def test_catalog_requires_parameter_identity_and_supported_grammar(self):
        original = {"name": r"\legacyparameter", "family": "parameter_assignment",
                    "grammar": {"handler": "integer_parameter_assignment"},
                    "metadata": {"parameter": "legacyparameter"}}
        for key in (None, "", r"\widowpenalty"):
            command = deepcopy(original)
            command["metadata"]["parameter"] = key
            with self.subTest(key=key), self.assertRaises(ProfileError):
                self.catalog._validate_reading({"commands": [command]}, Path("test.yaml"))

    def test_preparation_preserves_numeric_macro_operand_and_its_separator(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\pdfoutput=1" + "\n"
                r"\documentclass{article}\def\value{17 }\widowpenalty=\value" + "\nTEXT",
                encoding="utf-8", newline="\n")
            text, manifest, _, _ = preprocess_paper(str(root))
            self.assertEqual(manifest.unresolved, [])
            self.assertIn(r"\pdfoutput=1", text)
            self.assertIn(r"\widowpenalty=\value TEXT", text)
            self.assertFalse(any(c["reason"] == "unknown_construct" for c in manifest.uncertainty_causes))

    def test_parameter_separator_guard_retains_affected_child(self):
        scratch = PROJECT / "temp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root = Path(directory)
            (root / "main.tex").write_text(r"\documentclass{article}\input{child}", encoding="utf-8")
            child = r"\def\value{17 }\catcode32=12\relax\widowpenalty=\value" + "\nTEXT"
            (root / "child.tex").write_text(child, encoding="utf-8", newline="\n")
            text, manifest, output, _ = preprocess_paper(str(root))
            self.assertEqual(manifest.unresolved[0]["reason"], "assignment_separator")
            self.assertIn(r"\input{child.tex}", text)
            self.assertEqual((output / "child.tex").read_text(), child)


if __name__ == "__main__":
    unittest.main()
